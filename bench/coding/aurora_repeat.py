"""AURORA 코딩 과제를 n 번 연속으로 돌려 한 표로 요약한다 (2026-09-21).

한 판의 결과(n=1)는 주장이 못 된다 — 같은 과제·같은 빌드가 390~1186초로 3배 갈렸다.
이 스크립트는 **같은 조건으로 여러 번** 돌려 분포로 말하게 한다.

사용:  python bench/coding/aurora_repeat.py --n 3 --tag after_pushback_narrowing

- 실행 중인 자비스 백엔드(8091)의 `/v1/chat` 을 Code 모드로 부른다.
- 판마다 결과 JSON 을 `--out` 아래에 저장한다(잡 `result` 통째로 — `diagnosis` 포함).
- 토큰은 파일에서 읽어 헤더에만 쓴다. **어디에도 출력하지 않는다.**
- 판과 판 사이에 백엔드를 건드리지 않는다. 부하(빌드·git)는 사람이 통제한다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8091"
TOKEN_FILE = Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\control.token")
WORKSPACE = r"C:\Users\user\Documents\JARVIS\ontelic-aurora-efficiency-replay"

PROMPT = (
    "AURORA라는 한밤의 오로라 항해 관측소를 index.html 단일 파일로 만들어줘. "
    "깊은 밤 색감과 빛나는 오로라를 사용하고, 서로 다른 3개 관측 목적지 카드와 "
    "각 목적지의 관측 확률을 보여줘. 카드와 버튼은 클릭해 반응해야 해. "
    "완성 뒤 local_preview_page로 열고 browser_open, browser_snapshot, browser_click으로 "
    "화면과 상호작용을 직접 확인해. local_run_project_command로 검증하고 "
    "검증용 임시 파일은 삭제해."
)

_DONE = {"completed", "failed", "cancelled", "needs_input"}


def _token() -> str:
    return TOKEN_FILE.read_text(encoding="utf-8-sig").strip()


def call(path: str, body: dict | None = None, timeout: float = 60.0) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json", "X-JARVIS-TOKEN": _token()},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def run_once(index: int, out_dir: Path, tag: str, limit_sec: int) -> dict:
    Path(WORKSPACE).mkdir(parents=True, exist_ok=True)
    session = f"aurora-{tag}-{index}-{int(time.time())}"
    started = time.time()
    created = call("/v1/chat", {
        "prompt": PROMPT, "session_id": session, "origin": "workspace",
        "workspace_mode": "code", "delivery": "screen", "agent_mode": "auto",
        "code_workspace": WORKSPACE, "measurement": True,
    }, timeout=120)
    job = str(created.get("id") or created.get("job_id") or "")
    if not job:
        return {"index": index, "status": "no_job", "seconds": 0.0, "error": str(created)[:200]}
    row: dict = {}
    while time.time() - started < limit_sec:
        time.sleep(10)
        try:
            row = call(f"/v1/jobs/{job}", timeout=30)
        except Exception:  # noqa: BLE001 — 한 번 못 물어봤다고 판을 버리지 않는다
            continue
        if str(row.get("status") or "") in _DONE:
            break
    row = call(f"/v1/jobs/{job}", timeout=60)
    seconds = time.time() - started
    (out_dir / f"{tag}_{index}.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    result = row.get("result") or {}
    steps = (result.get("agent_trace") or {}).get("steps") or []
    tools = [str(step.get("tool") or "") for step in steps]
    return {
        "index": index, "job": job[:8], "status": row.get("status"), "build": row.get("build"),
        "seconds": round(seconds, 1), "steps": len(steps),
        "ran_project_command": tools.count("local_run_project_command"),
        "clicked": sum(1 for t in tools if t.startswith("browser_click")),
        "error": row.get("error") or "",
        "diagnosis": result.get("diagnosis") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument("--tag", default="aurora")
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    parser.add_argument("--limit-sec", type=int, default=2400)
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for index in range(1, args.n + 1):
        row = run_once(index, out_dir, args.tag, args.limit_sec)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    done = [r for r in rows if r["status"] == "completed"]
    print(f"\n완료 {len(done)}/{len(rows)}", flush=True)
    if done:
        secs = [r["seconds"] for r in done]
        steps = [r["steps"] for r in done]
        print(f"시간 {min(secs):.0f}~{max(secs):.0f}초 (중앙 {statistics.median(secs):.0f}) "
              f"· 걸음 {min(steps)}~{max(steps)}", flush=True)
    silent = [r for r in rows if r["status"] == "failed" and not r.get("diagnosis")]
    if silent:
        print(f"⚠ 실패인데 diagnosis 가 없는 판 {len(silent)}개 — 패치가 안 올라갔을 수 있다", flush=True)
    sys.exit(0 if len(done) == len(rows) else 1)


if __name__ == "__main__":
    main()
