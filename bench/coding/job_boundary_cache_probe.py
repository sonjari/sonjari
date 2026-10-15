# -*- coding: utf-8 -*-
"""판 사이 앞머리 캐시 실험 — 무엇을 어디에 두면 새 판의 첫 호출이 다시 읽지 않는가 (2026-10-07).

`prefix_cache_probe.py` 는 「판 도중 도구 목록이 바뀌면」을 잰다. 이것은 **판과 판 사이**다 — 시각 줄을 시스템 끝 ·
요청 메시지 앞 · 둘째 시스템 메시지에 둘 때, 그리고 사이에 다른 짧은 호출이 낄 때 서버가 어디로 되돌아가 몇 토큰을 읽나.
운영 모델이 체크포인트 자리로만 되돌리는 종류(서버 기록의 `context checkpoint`)인지도 여기서 보인다.

    python job_boundary_cache_probe.py [A B C D E]

운영과 같은 모델·같은 컨텍스트·같은 keep_alive 로 부른다(다르면 모델이 내려간다). 한 호출은 토큰 하나만 쓴다.
호출마다 서버 기록(%LOCALAPPDATA%/Ollama/server.log)에서 그 호출의 줄만 뽑아 요약한다.
"""
import io
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
OLLAMA = "http://127.0.0.1:11434"
LOG = Path(os.environ["LOCALAPPDATA"]) / "Ollama" / "server.log"
DOC = Path(__file__).resolve().parents[2] / "docs" / "헤르메스_코딩하네스_전수조사_1003.ko.md"      # 긴 고정 글로 쓴다

TOOLS = [
    {"type": "function", "function": {
        "name": f"probe_tool_{i}", "description": f"시험용 도구 {i}. 경로의 글을 읽어 돌려준다.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "line_start": {"type": "integer"}},
                       "required": ["path"]}}}
    for i in range(12)
]


def loaded() -> tuple[str, int]:
    with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=10) as response:
        models = json.load(response).get("models") or []
    if not models:
        raise SystemExit("올라와 있는 모델이 없다")
    return str(models[0]["name"]), int(models[0].get("context_length") or 0)


def call(model: str, num_ctx: int, messages: list[dict], tools: list[dict] | None) -> dict:
    body = {"model": model, "stream": False, "think": False, "keep_alive": "24h", "messages": messages,
            "options": {"temperature": 0.0, "num_predict": 1, "num_ctx": num_ctx}}
    if tools:
        body["tools"] = tools
    before = LOG.stat().st_size
    request = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.load(response)
    wall = time.monotonic() - started
    time.sleep(0.4)
    with LOG.open("rb") as handle:
        handle.seek(before)
        text = handle.read().decode("utf-8", "replace")
    created = [int(n) for n in re.findall(r"created context checkpoint \d+ of \d+ \(pos_min = \d+, pos_max = \d+, n_tokens = (\d+)", text)]
    restored = re.findall(r"restored context checkpoint \(pos_min = \d+, pos_max = \d+, n_tokens = (\d+)", text)
    against = re.findall(r"against (\d+)\.\.\.", text)
    evaluated = re.findall(r"prompt eval time =\s+([\d.]+) ms /\s+(\d+) tokens", text)
    return {
        "wall": round(wall, 2),
        "prompt_tokens": payload.get("prompt_eval_count"),
        "read_sec": round(float(payload.get("prompt_eval_duration") or 0) / 1e9, 2),
        "read_tokens": int(evaluated[-1][1]) if evaluated else None,
        "common_prefix": int(against[0]) if against else None,
        "restored_at": int(restored[-1]) if restored else None,
        "full_reprocess": "forcing full prompt re-processing" in text,
        "checkpoints_made": created,
    }


def show(label: str, row: dict) -> None:
    print(f"{label:<46} 프롬프트 {row['prompt_tokens']:>6}토큰 · 다시 읽음 {row['read_tokens']!s:>6}토큰 {row['read_sec']:>5}초 · "
          f"같은 앞머리 {row['common_prefix']!s:>6} · 되돌린 자리 {row['restored_at']!s:>6} · 전체 다시 {row['full_reprocess']} · 새 체크포인트 {row['checkpoints_made']}")


def main() -> None:
    model, num_ctx = loaded()
    static = DOC.read_text(encoding="utf-8")[:18000]
    time_a = "\n\n현재 한국 시각 (KST)\n- 날짜: 2026년 10월 7일\n- 요일: 수요일\n- 시각: 18:32\n날짜·요일·시각을 물으면 위 값을 그대로 쓴다."
    time_b = time_a.replace("18:32", "18:34")
    day_only = "\n\n오늘 (KST)\n- 날짜: 2026년 10월 7일\n- 요일: 수요일"
    goal_1 = "tests 의 실패를 고쳐줘. 과제 하나."
    goal_2 = "README 에 설치 방법을 한 줄 더해줘. 과제 둘."
    which = set(sys.argv[1:]) or {"A", "B", "C", "D"}
    print(f"모델 {model} · 컨텍스트 {num_ctx}\n")

    if "A" in which:
        print("[A] 지금 모양 — 시각 줄이 시스템 메시지 끝")
        show("A1 처음", call(model, num_ctx, [{"role": "system", "content": static + time_a}, {"role": "user", "content": goal_1}], TOOLS))
        show("A2 같은 것 한 번 더", call(model, num_ctx, [{"role": "system", "content": static + time_a}, {"role": "user", "content": goal_1}], TOOLS))
        show("A3 시스템은 같고 요청만 다름", call(model, num_ctx, [{"role": "system", "content": static + time_a}, {"role": "user", "content": goal_2}], TOOLS))
        show("A4 시각 줄이 2분 지남(새 판)", call(model, num_ctx, [{"role": "system", "content": static + time_b}, {"role": "user", "content": goal_1}], TOOLS))
        print()
    if "B" in which:
        print("[B] 시각 줄을 첫 사용자 메시지 앞으로")
        show("B1 처음", call(model, num_ctx, [{"role": "system", "content": static}, {"role": "user", "content": time_a.strip() + "\n\n" + goal_1}], TOOLS))
        show("B2 시각도 요청도 다름(새 판)", call(model, num_ctx, [{"role": "system", "content": static}, {"role": "user", "content": time_b.strip() + "\n\n" + goal_2}], TOOLS))
        show("B3 다시 첫 요청(새 판)", call(model, num_ctx, [{"role": "system", "content": static}, {"role": "user", "content": time_a.strip() + "\n\n" + goal_1}], TOOLS))
        print()
    if "C" in which:
        print("[C] 시각 줄을 둘째 시스템 메시지로")
        show("C1 처음", call(model, num_ctx, [{"role": "system", "content": static}, {"role": "system", "content": time_a.strip()}, {"role": "user", "content": goal_1}], TOOLS))
        show("C2 시각도 요청도 다름(새 판)", call(model, num_ctx, [{"role": "system", "content": static}, {"role": "system", "content": time_b.strip()}, {"role": "user", "content": goal_2}], TOOLS))
        print()
    if "D" in which:
        print("[D] 시스템 끝에 날짜만(시·분 없음) — 하루 안에서는 같은 글")
        show("D1 처음", call(model, num_ctx, [{"role": "system", "content": static + day_only}, {"role": "user", "content": goal_1}], TOOLS))
        show("D2 요청만 다름(새 판)", call(model, num_ctx, [{"role": "system", "content": static + day_only}, {"role": "user", "content": goal_2}], TOOLS))
        print()
    if "E" in which:
        print("[E] 사이에 전혀 다른 짧은 호출이 끼면(기억 뽑기 같은 곁가지)")
        show("E1 처음", call(model, num_ctx, [{"role": "system", "content": static}, {"role": "user", "content": time_a.strip() + "\n\n" + goal_1}], TOOLS))
        show("E2 곁가지(짧은 시스템·도구 없음)", call(model, num_ctx, [{"role": "system", "content": "너는 사실만 뽑는 도구다. JSON 만 답한다."}, {"role": "user", "content": "안녕"}], None))
        show("E3 원래 모양으로 새 판", call(model, num_ctx, [{"role": "system", "content": static}, {"role": "user", "content": time_b.strip() + "\n\n" + goal_2}], TOOLS))


if __name__ == "__main__":
    main()
