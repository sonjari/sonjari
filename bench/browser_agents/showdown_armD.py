"""arm D — 자비스 배선 + 프런티어 모델(껍데기 경유).

어제와 **같은 4 과제 · 같은 예산 · 같은 측정 경로**(run_jarvis_one.py)로 돌린다.
바뀐 것은 자비스가 부르는 모델 하나뿐이다.

    로컬 gemma4-qat 26B   →   claude-sonnet-5 (ollama_anthropic_shim 경유)

전제: 껍데기가 11500 에 떠 있고, 자비스 .env 에
      JARVIS_OLLAMA_BASE_URL=http://127.0.0.1:11500 이 들어간 채로 재시작돼 있을 것.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).parent
JV_PY = pathlib.Path(r"C:\work\monorepo\tools\alture-jarvis\.venv\Scripts\python.exe")
USAGE = HERE / "shim_usage.jsonl"
BUDGET = 600

TASKS = [
    ("saramin.co.kr",   "사람인에서 여수 회계 채용 공고 3개의 고용형태와 마감일을 알려줘"),
    ("kyobobook.co.kr", "교보문고에서 회계 관련 책 3권의 쪽수와 출판사를 알려줘"),
    ("yes24.com",       "YES24에서 파이썬 책 3권의 쪽수와 ISBN을 알려줘"),
    ("wishket.com",     "위시켓에서 AI 에이전트 관련 프로젝트 3개의 예상 기간과 지원자 수를 알려줘"),
]


def usage_lines() -> int:
    try:
        return sum(1 for _ in USAGE.open(encoding="utf-8"))
    except OSError:
        return 0


def tokens_between(start: int) -> dict:
    """이 판이 태운 토큰 — 껍데기 기록에서 그 구간만 뽑는다."""
    tin = tout = calls = 0
    rows = 0
    try:
        for i, line in enumerate(USAGE.open(encoding="utf-8")):
            if i < start:
                continue
            d = json.loads(line)
            tin += int(d.get("in") or 0)
            tout += int(d.get("out") or 0)
            calls += int(d.get("calls") or 0)
            rows += 1
    except OSError:
        pass
    return {"model_calls": rows, "tokens_in": tin, "tokens_out": tout, "tool_calls": calls}


rows = []
for host, prompt in TASKS:
    print(f"\n{'=' * 66}\n[armD] {host}", flush=True)
    mark = usage_lines()
    out = HERE / f"armd_{host.split('.')[0]}.json"
    t0 = time.time()
    subprocess.run(
        [str(JV_PY), str(HERE / "run_jarvis_one.py"), "--prompt", prompt,
         "--host", host, "--budget", str(BUDGET), "--out", str(out)],
        capture_output=True, timeout=BUDGET + 180,
    )
    try:
        r = json.loads(out.read_text(encoding="utf-8"))
    except Exception as exc:
        r = {"error": f"no output: {exc}", "steps": 0, "elapsed_sec": round(time.time() - t0, 1)}
    r["host"] = host
    r["arm"] = "D_jarvis_sonnet"
    r.update(tokens_between(mark))
    # ★ 껍데기가 터진 판을 성공으로 세지 않는다 (2026-09-07 에 그렇게 속았다).
    #   겉으로는 「8걸음 33.6초 부족신고 False」로 멀쩡해 보였고, 답만 열어 보니
    #   여덟 번 다 400 이었다. 재는 자가 거짓말한 자리라 여기서 못 박는다.
    blob = str(r.get("answer_head") or "") + str(r.get("answer") or "")
    r["rig_broken"] = "[shim error]" in blob
    if r["rig_broken"]:
        print("  ★ 리그 고장 — 이 판은 결과가 아니다:", blob[:160], flush=True)
    rows.append(r)
    print(f"  걸음 {r.get('steps')}  {r.get('elapsed_sec')}s  도달 {r.get('reached_host')}  "
          f"부족신고 {r.get('flagged_shortfall')}  "
          f"모델호출 {r['model_calls']}  토큰 in {r['tokens_in']:,} / out {r['tokens_out']:,}",
          flush=True)
    print(f"  도구: {r.get('tools')}", flush=True)
    (HERE / "results" / "armD_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

print("\n완료 — results/armD_results.json")
