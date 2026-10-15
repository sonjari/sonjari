"""3회 반복 — 「한 번 통과는 한 번만 증명한다」.

## 왜 이것만 남았나

2026-09-07~08 에 등급별로 한 번씩 쟀다. 결과는 좋았지만 **각 1회**다.
n=1 로 큰 숫자를 말하면 신뢰를 잃는 가장 빠른 길이고, 그 신뢰가 이 기획의 자산이다.

여기서 재는 것은 **평균이 아니라 분산**이다. 세 번 중 한 번 창작하면 그것이 진짜
창작률이고, 세 번 다 깨끗하면 그때 「창작 0건」이라고 쓸 수 있다.

## 무엇을 세나

    도달       그 사이트에 실제로 갔나
    근거없음   답의 숫자 중 도구가 준 적 없는 것  ← 창작 지표
    걸음·시간  분산을 보려고
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, r"E:\evidence-ledger\src")
from evidence_ledger import numbers_claimed_in  # noqa: E402

HERE = pathlib.Path(__file__).parent
PY = HERE / ".venv" / "Scripts" / "python.exe"
TOKEN = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token").read_text().strip()
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
LABEL = sys.argv[2] if len(sys.argv) > 2 else "tier"

TASKS = [
    ("wishket", "wishket.com", "위시켓에서 AI 에이전트 관련 프로젝트 2개의 예상 기간을 알려줘"),
    ("yes24", "yes24.com", "YES24에서 파이썬 책 2권의 쪽수와 ISBN을 알려줘"),
    ("saramin", "saramin.co.kr", "사람인에서 여수 회계 채용 공고 2개의 회사명과 고용형태를 알려줘"),
]


def latest_job() -> dict:
    req = urllib.request.Request(
        "http://127.0.0.1:8091/v1/jobs?limit=1", headers={"X-Jarvis-Token": TOKEN})
    rows = json.load(urllib.request.urlopen(req, timeout=25))
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return rows[0] if rows else {}


rows = []
for round_no in range(1, ROUNDS + 1):
    for name, host, prompt in TASKS:
        out = HERE / f"rep_{LABEL}_{name}_{round_no}.json"
        started = time.time()
        subprocess.run([str(PY), str(HERE / "run_jarvis_one.py"), "--prompt", prompt,
                        "--host", host, "--budget", "600", "--out", str(out)],
                       capture_output=True, timeout=900)
        try:
            row = json.loads(out.read_text(encoding="utf-8"))
        except Exception as exc:
            row = {"error": str(exc)}
        job = latest_job()
        res = job.get("result") or {}
        trace = res.get("agent_trace") or {}
        seen = set(trace.get("tool_numbers") or []) | set(trace.get("tool_numbers_body") or [])
        answer = str(res.get("answer") or "")
        claimed = numbers_claimed_in(answer)
        row.update({
            "round": round_no, "task": name, "label": LABEL,
            "job": str(job.get("id") or "")[:8],
            "tool_numbers_seen": len(seen),
            "answer_numbers": len(claimed),
            "unsupported": sorted(claimed - seen)[:10],
            "wall_sec": round(time.time() - started, 1),
        })
        rows.append(row)
        print(f"[{LABEL} r{round_no}] {name:9} 걸음 {row.get('steps'):>3} · "
              f"{row.get('elapsed_sec')}s · 도달 {row.get('reached_host')} · "
              f"★근거없음 {len(row['unsupported'])} {row['unsupported'][:4]}", flush=True)
        (HERE / "results" / f"repeat_{LABEL}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"\n완료 — results/repeat_{LABEL}.json")
