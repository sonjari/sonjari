"""조사 판이 **갈래 밖의 손**을 부르는가 — 도구 목록을 전체로 보여 준 뒤의 확인 (2026-10-07).

웹 조사 판에도 전체 도구 목록을 보여 주고 갈래 밖의 손은 부르면 되돌려 보내게 바꿨다(`agent._route_hands`).
좁혔던 까닭(2026-09-09: 책 조사 판이 진로DB 를 6번 불렀다)이 지금 모델에서도 나는지 실제 조사 과제로 센다.

    python research_route_probe.py <결과.jsonl> [반복=1]

판마다: 상태 · 걸린 시간 · 걸음 · 갈래 거절(`not_this_route`) 횟수와 그 도구 · 쓴 도구 종류. 읽기만 하는 과제다.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
RUNTIME = os.environ.get("JARVIS_RUNTIME_ROOT", r"C:\RoboMetaFit\tools\alture-jarvis")
BASE = "http://127.0.0.1:8091"
TOKEN = (Path(RUNTIME) / "data" / "control.token").read_text(encoding="utf-8").strip()

TASKS = {
    "books": "교보문고에서 파이썬 입문 책 3권을 찾아 제목과 정가, 쪽수를 표로 알려줘. 파일은 만들지 마.",
    "hn": "해커뉴스(news.ycombinator.com) 첫 페이지에서 지금 점수가 가장 높은 글 3개의 제목과 점수를 알려줘.",
    "wiki": "한국어 위키백과에서 '훈민정음' 문서를 열어 읽고, 반포된 해와 만든 사람을 문서에 적힌 대로 알려줘.",
}


def call(path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"X-JARVIS-TOKEN": TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def run(task: str, n: int, timeout: float = 420.0) -> dict:
    job = call("/v1/chat", {"prompt": TASKS[task], "origin": "mcp", "display_prompt": f"갈래 확인 {task}#{n}",
                            "open_results": False, "session_id": f"route-probe-{task}-{n}-{int(time.time())}",
                            "measurement": True})
    job_id = str(job.get("id") or job.get("job_id") or "")
    started = time.monotonic()
    status = ""
    while time.monotonic() - started < timeout:
        time.sleep(3)
        state = call(f"/v1/jobs/{job_id}")
        status = str(state.get("status") or "")
        if status in {"completed", "failed", "cancelled", "waiting_continuation", "waiting_approval"}:
            break
    else:
        try:
            call(f"/v1/jobs/{job_id}/cancel", {})
        except Exception:  # noqa: BLE001
            pass
        status = "timeout"
    con = sqlite3.connect("file:" + os.path.join(RUNTIME, "data", "jarvis.db") + "?mode=ro", uri=True)
    row = con.execute("select result_json, started_at, finished_at from jobs where id = ?", (job_id,)).fetchone()
    result = json.loads(row[0]) if row and row[0] else {}
    steps = ((result.get("agent_trace") or {}).get("steps")) or []
    refused = [str(s.get("tool")) for s in steps if str(s.get("error") or "") == "not_this_route"]
    tools = sorted({str(s.get("tool")) for s in steps})
    off_route = sorted({t for t in tools if not t.startswith(("browser_", "site_", "ui_", "local_", "artifact_", "sandbox_", "ask_user", "skill_", "self_"))})
    return {
        "task": task, "run": n, "job": job_id[:8], "status": status,
        "sec": round((row[2] or 0) - (row[1] or 0), 1) if row and row[1] and row[2] else None,
        "steps": len(steps), "route_refusals": len(refused), "refused_tools": refused,
        "tools_outside_web_prefixes": off_route, "tools": tools,
        "answer_chars": len(str(result.get("answer") or "")),
        "state": str(result.get("completion_state") or ""),
    }


def main() -> None:
    out = Path(sys.argv[1])
    repeats = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    for n in range(1, repeats + 1):
        for task in TASKS:
            row = run(task, n)
            with out.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{task}#{n} {row['status']} · {row['sec']}초 · 걸음 {row['steps']} · 갈래 거절 {row['route_refusals']} {row['refused_tools']} · "
                  f"웹 갈래 밖 도구 {row['tools_outside_web_prefixes']} · {row['state']}")


if __name__ == "__main__":
    main()
