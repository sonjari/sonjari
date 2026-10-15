"""본 창이 시킨 판의 답이 **판 밖에서** 칠해지는가 — 실제 판으로 확인 (2026-10-07).

본 창과 같은 모양(`origin: workspace` · `delivery: screen`)으로 과제 하나를 보내고, 그 판의 사건 시각을 늘어놓는다.
기대: 답 조각이 오는 도중에 `job_completed` 가 오고, 그 뒤에도 조각이 이어지다가 `agent_answer_painted` 로 끝난다.
소리는 나지 않는다(화면 전달). 읽기만 하는 과제다.

    python paint_apart_probe.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
RUNTIME = os.environ.get("JARVIS_RUNTIME_ROOT", r"C:\RoboMetaFit\tools\alture-jarvis")
BASE = "http://127.0.0.1:8091"
TOKEN = (Path(RUNTIME) / "data" / "control.token").read_text(encoding="utf-8").strip()
PROMPT = "https://example.com 을 열어 읽고, 그 페이지가 무엇을 위한 것인지 다섯 문장으로 설명해줘. 파일은 만들지 마."


def call(path: str, body: dict | None = None):
    request = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"X-JARVIS-TOKEN": TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> None:
    last = call("/v1/events?after=0&limit=1")
    # 가장 최근 사건 번호를 찾는다 — 그 뒤의 것만 본다.
    after = 0
    while True:
        batch = call(f"/v1/events?after={after}&limit=200")
        if not batch:
            break
        after = int(batch[-1].get("seq") or after)
        if len(batch) < 200:
            break
    del last
    job = call("/v1/chat", {"prompt": PROMPT, "origin": "workspace", "delivery": "screen", "agent_mode": "auto",
                            "workspace_mode": "cowork", "session_id": f"paint-apart-probe-{int(time.time())}"})
    job_id = str(job.get("id") or job.get("job_id"))
    started = time.time()
    while time.time() - started < 240:
        time.sleep(0.5)
        state = call(f"/v1/jobs/{job_id}")
        if state.get("status") in {"completed", "failed", "cancelled", "waiting_continuation", "waiting_approval"}:
            break
    finished_seen = time.time()
    time.sleep(8)                      # 판이 끝난 뒤에도 조각이 오는지 본다
    rows = []
    while True:
        batch = call(f"/v1/events?after={after}&limit=200")
        if not batch:
            break
        rows.extend(batch)
        after = int(batch[-1].get("seq") or after)
        if len(batch) < 200:
            break
    mine = [r for r in rows if str((r.get("payload") or {}).get("job_id") or "") == job_id]
    stamp = lambda r: float(r.get("timestamp") or 0)  # noqa: E731
    base = stamp(mine[0]) if mine else 0.0
    deltas = [r for r in mine if r.get("event") == "agent_answer_delta"]
    done = next((r for r in mine if r.get("event") == "job_completed"), None)
    painted = next((r for r in mine if r.get("event") == "agent_answer_painted"), None)
    reset = next((r for r in mine if r.get("event") == "agent_answer_reset"), None)
    print(f"판 {job_id[:8]} · 상태 {state.get('status')} · 본 사건 {len(mine)}건 · 물어서 끝난 것을 안 시각 +{finished_seen - started:.1f}초")
    if reset:
        print(f"  칠하기 시작 +{stamp(reset) - base:6.2f}초 · 판 밖에서 칠한다고 알림: {bool((reset.get('payload') or {}).get('apart'))}")
    if deltas:
        print(f"  답 조각 {len(deltas)}개 · 첫 조각 +{stamp(deltas[0]) - base:6.2f}초 · 마지막 조각 +{stamp(deltas[-1]) - base:6.2f}초")
    if done:
        after_done = sum(1 for r in deltas if stamp(r) > stamp(done))
        print(f"  판이 끝남     +{stamp(done) - base:6.2f}초 · 그 뒤에 온 조각 {after_done}개")
    if painted:
        print(f"  다 칠했다     +{stamp(painted) - base:6.2f}초" + (f" (판이 끝난 뒤 {stamp(painted) - stamp(done):.2f}초)" if done else ""))
    answer = str(((state.get("result") or {}).get("answer")) or "")
    print(f"  답 {len(answer)}자 · 조각을 이은 글과 같은가: {''.join(str((r.get('payload') or {}).get('delta') or '') for r in deltas) == answer}")


if __name__ == "__main__":
    main()
