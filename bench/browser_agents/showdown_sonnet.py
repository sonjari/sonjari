"""대조군 — 같은 4 과제를 Browser Use + claude-sonnet-5 로.

목적 하나: "로컬 26B 로 돌려놓고 못한다고 하네" 라는 반론을 없앤다.
소네트도 같은 실패를 하면 모델이 아니라 배선이다.
"""
from __future__ import annotations
import json, pathlib, subprocess, sys, time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).parent
BU_PY = HERE / ".venv" / "Scripts" / "python.exe"
BUDGET = 600

TASKS = [
    ("saramin.co.kr",  "사람인에서 여수 회계 채용 공고 3개의 고용형태와 마감일을 알려줘"),
    ("kyobobook.co.kr","교보문고에서 회계 관련 책 3권의 쪽수와 출판사를 알려줘"),
    ("yes24.com",      "YES24에서 파이썬 책 3권의 쪽수와 ISBN을 알려줘"),
    ("wishket.com",    "위시켓에서 AI 에이전트 관련 프로젝트 3개의 예상 기간과 지원자 수를 알려줘"),
]

rows = []
for host, prompt in TASKS:
    print(f"\n=== [sonnet] {host}", flush=True)
    out = HERE / f"sonnet_{host.split('.')[0]}.json"
    t0 = time.time()
    subprocess.run([str(BU_PY), str(HERE / "run_bu.py"), "--prompt", prompt,
                    "--host", host, "--budget", str(BUDGET), "--max-steps", "30",
                    "--provider", "anthropic", "--frontier-model", "claude-sonnet-5",
                    "--out", str(out)],
                   capture_output=True, timeout=BUDGET + 180)
    try:
        r = json.loads(out.read_text(encoding="utf-8"))
    except Exception as exc:
        r = {"error": f"no output: {exc}", "urls": [], "steps": 0, "seconds": round(time.time()-t0,1), "answer": ""}
    r["host"] = host
    rows.append(r)
    print(f"  걸음{r.get('steps')} {r.get('seconds')}s 도달{r.get('reached')} "
          f"URL{len(r.get('urls',[]))} err={r.get('error','')[:60]}", flush=True)
    (HERE / "sonnet_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

print("\n완료 — sonnet_results.json")
