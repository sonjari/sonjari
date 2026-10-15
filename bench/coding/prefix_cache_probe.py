"""도구 목록이 바뀌면 프리필 캐시가 깨지는가 — 로컬 Ollama 에서 **직접 잰다** (2026-09-22).

배경: Manus 의 컨텍스트 엔지니어링 글은 「작업 도중 도구를 빼면 도구 정의가 프롬프트 앞쪽에 있어서 캐시가 통째로 깨진다」고 쓴다.
우리는 판 도중에 손을 좁힌다(`code_tools_after_look_pushback`·`code_tools_after_coding_pushback`). 그게 로컬에서도 비싼지는 안 쟀다.
`_model_time_summary` 주석에는 「같은 앞부분이면 20K 토큰 재프리필이 0.5~1.4초」라고만 있다 — **도구가 바뀐 경우**는 없다.

생성은 1토큰만 시켜서(`num_predict=1`) 시간이 거의 전부 프리필이 되게 한다. 운영과 같은 모델·컨텍스트(`/api/ps`)를 쓴다
(다른 `num_ctx` 를 주면 Ollama 가 러너를 새로 띄워 운영 모델이 축출된다 — 이 저장소가 여러 번 겪은 것).

    python prefix_cache_probe.py
"""
from __future__ import annotations

import io
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import count_tools_offered as C  # noqa: E402  (stdout 래핑은 여기서 한 번만)
from alture_jarvis.code_runtime import select_code_tool_profile  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"
HANDS = {"local_run_project_command", "local_write_file", "local_apply_edit", "local_delete_file"}


def post(path: str, body: dict, timeout: float = 600) -> dict:
    request = urllib.request.Request(OLLAMA + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=timeout))


def resident() -> tuple[str, int]:
    running = json.load(urllib.request.urlopen(OLLAMA + "/api/ps", timeout=10)).get("models") or []
    if not running:
        raise SystemExit("올라와 있는 모델이 없다 — 운영 모델이 떠 있을 때 돌려라")
    return running[0]["name"], int(running[0].get("context_length") or 0)


def filler(seed: int, chars: int) -> str:
    """진짜 같은 한국어·코드 섞인 긴 글. 시드가 다르면 앞부분부터 달라진다(다른 실험의 캐시와 안 섞이게)."""
    rng = random.Random(seed)
    words = ["저장소", "함수", "테스트", "검증", "경로", "파일", "def", "return", "assert", "import", "오류", "결과", "index.html", "pytest", "diff"]
    out: list[str] = []
    total = 0
    while total < chars:
        line = f"[{rng.randint(1000, 9999)}] " + " ".join(rng.choice(words) for _ in range(rng.randint(8, 16))) + "\n"
        out.append(line)
        total += len(line)
    return "".join(out)


def call(model: str, ctx: int, messages: list[dict], tools: list[dict]) -> dict:
    started = time.time()
    out = post("/api/chat", {
        "model": model, "messages": messages, "tools": tools, "stream": False, "think": False,
        "options": {"num_ctx": ctx, "num_predict": 1, "temperature": 0.0}, "keep_alive": "24h",
    })
    return {
        "wall": round(time.time() - started, 2),
        "prompt_tokens": int(out.get("prompt_eval_count") or 0),
        "prefill_s": round(float(out.get("prompt_eval_duration") or 0) / 1e9, 2),
    }


def main() -> None:
    model, ctx = resident()
    defs = C.catalog()
    profile = select_code_tool_profile("test_calc.py 가 실패한다. calc.py 를 고치고 pytest 로 확인해.", force_sandbox=False, context="")
    full = [d for d in defs if d["function"]["name"] in set(profile.tool_names)]
    narrow = [d for d in full if d["function"]["name"] in HANDS]
    print(f"모델 {model} · 컨텍스트 {ctx:,} · 전체 도구 {len(full)}개 → 좁힌 도구 {len(narrow)}개\n")

    print(f"{'조건':<58}{'입력토큰':>9}{'프리필s':>9}{'벽시계s':>9}")
    for trial in (1, 2):
        base = [
            {"role": "system", "content": f"너는 코드 작업자다. (시험 {trial})\n" + filler(trial * 100, 60_000)},
            {"role": "user", "content": "test_calc.py 가 실패한다. 고쳐라."},
        ]
        grown = base + [{"role": "assistant", "content": "먼저 읽겠다."}, {"role": "user", "content": "읽은 결과: " + filler(trial * 100 + 1, 800)}]
        steps = [
            ("A0  첫 호출 (전체 도구)", base, full),
            ("A1  똑같이 다시 (전체 도구)  → 캐시 적중이어야 한다", base, full),
            ("A2  대화만 조금 늘어남 (전체 도구)  → 앞부분 재사용", grown, full),
            ("B   같은 대화인데 도구를 4개로 좁힘  ← 우리가 하는 것", grown, narrow),
            ("C   다시 전체 도구로 되돌림  ← 좁히기를 푼 뒤", grown, full),
            ("D   좁힌 채로 한 번 더 (연속 두 번째)", grown, narrow),
        ]
        print(f"--- 시험 {trial} ---")
        for label, messages, tools in steps:
            r = call(model, ctx, messages, tools)
            print(f"{label:<58}{r['prompt_tokens']:>9,}{r['prefill_s']:>9}{r['wall']:>9}")


if __name__ == "__main__":
    main()
