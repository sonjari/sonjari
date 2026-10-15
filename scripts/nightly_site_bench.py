"""밤마다 사이트 벤치 한 판 — 사이트가 바뀌어 온텔릭이 못 하게 된 것을 **사람보다 먼저** 안다 (2026-09-18).

## 왜

사이트는 우리가 안 바꿔도 바뀐다. MS 스토어는 어느 날 전부 섀도 DOM 이 됐고, YES24 는 결과 2위에 광고를 끼웠다.
그때마다 알게 된 것은 사람이 시켜 보고 실패한 뒤였다. 벤치(`bench/browser_agents/shadow_dom_bench.py`)는 있었지만
사람이 기억해서 돌려야 했다.

## 하는 일

1. 운영 온텔릭이 **놀고 있을 때만** 돈다(사람이 시킨 일과 줄을 다투지 않는다). 바쁘면 30분까지 기다렸다가 건너뛴다.
2. 벤치 4과제를 1판씩 돌린다(약 10~15분).
3. 결과를 `bench/browser_agents/results/nightly/history.jsonl` 에 한 줄 덧붙인다 — **진 판도 지우지 않는다**(전략안 §12).
4. **같은 과제가 이틀 연속 틀리거나**, 한 밤에 절반 이상 틀리면 알림을 띄운다. 하루 한 번 틀린 것은 흔들림일 수 있다.
5. 새 도구(`browser_page_data` 등)가 지난 24시간 실제 판에서 몇 번 불렸는지도 같이 적는다 — 만들고 안 쓰이는 것이
   이 저장소의 반복 병이다.

작업 스케줄러가 부른다(`RoboMetaFit-Ontelic-NightlyBench`). 이 파일은 C: 사본에서 돈다 — 한글 경로를 스케줄러
인자로 넘기면 깨진다(사고 J-2). 저장소 경로는 파이썬 안에서만 쓴다.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(os.environ.get("ONTELIC_REPO_ROOT", r"C:\work\monorepo\tools\alture-jarvis"))
RUNTIME = Path(os.environ.get("ONTELIC_RUNTIME_ROOT", r"C:\RoboMetaFit\tools\alture-jarvis"))
PYTHON = RUNTIME / ".venv" / "Scripts" / "python.exe"
BENCH = REPO / "bench" / "browser_agents" / "shadow_dom_bench.py"
RESULTS = REPO / "bench" / "browser_agents" / "results" / "shadow_dom"
NIGHTLY = REPO / "bench" / "browser_agents" / "results" / "nightly"
HEALTH = os.environ.get("ONTELIC_HEALTH_URL", "http://127.0.0.1:8091/health")
TASKS = ("ms_search", "ms_detail", "wa_search", "yes24_ctrl")
NEW_TOOLS = ("browser_page_data", "browser_site_sources", "ui_read_value", "browser_click_at", "browser_type_at")


def _idle() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=5) as response:
            state = str(json.loads(response.read().decode("utf-8")).get("state") or "")
    except Exception:  # noqa: BLE001 — 꺼져 있으면 벤치를 돌 수 없다
        return False
    return state == "idle"


def _wait_for_idle(limit_sec: float = 1800) -> bool:
    deadline = time.monotonic() + limit_sec
    while time.monotonic() < deadline:
        if _idle():
            return True
        time.sleep(60)
    return False


def _run_bench(label: str) -> int:
    done = subprocess.run([str(PYTHON), str(BENCH), label, "1"], cwd=str(REPO), timeout=3600,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    (NIGHTLY / f"{label}.log").write_text((done.stdout or "") + (done.stderr or ""), encoding="utf-8")
    return done.returncode


def _results(label: str) -> dict[str, bool | None]:
    """과제마다 맞았나. 결과 파일이 없으면 None(=「못 쟀다」, 틀림과 다르다)."""
    found: dict[str, bool | None] = {task: None for task in TASKS}
    for path in RESULTS.glob(f"{label}_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        task = str(data.get("task") or "")
        if task in found:
            found[task] = bool(data.get("correct"))
    return found


def _new_tool_calls(hours: int = 24) -> dict[str, int]:
    """지난 24시간 실제 판에서 새 도구가 몇 번 불렸나(운영 DB 사본을 읽기만 한다)."""
    import shutil
    import tempfile

    source = RUNTIME / "data" / "jarvis.db"
    counts = {name: 0 for name in NEW_TOOLS}
    if not source.exists():
        return counts
    work = Path(tempfile.mkdtemp(prefix="nightly-db-"))
    for suffix in ("", "-wal", "-shm"):  # WAL 도 같이 — 본체만 뜨면 최근 것이 안 보인다
        if (source.parent / (source.name + suffix)).exists():
            shutil.copy(source.parent / (source.name + suffix), work / (source.name + suffix))
    since = time.time() - hours * 3600
    with sqlite3.connect(work / source.name) as conn:
        for (raw,) in conn.execute("SELECT result_json FROM jobs WHERE created_at >= ? AND result_json IS NOT NULL", (since,)):
            try:
                steps = (json.loads(raw or "{}").get("agent_trace") or {}).get("steps") or []
            except ValueError:
                continue
            for step in steps:
                name = str(step.get("tool") or "")
                if name in counts:
                    counts[name] += 1
    shutil.rmtree(work, ignore_errors=True)
    return counts


def judge(history: list[dict[str, Any]]) -> list[str]:
    """**순수 함수.** 알릴 까닭 목록. 비면 조용히 지나간다.

    - 한 밤에 절반 이상 틀림(못 잰 것은 세지 않는다)
    - 같은 과제가 이틀 연속 틀림 — 하루 한 번은 흔들림일 수 있다(판마다 편차가 이 저장소의 실측이다)
    - 벤치 자체가 못 돎(과제가 전부 None)
    """
    if not history:
        return []
    last = history[-1].get("tasks") or {}
    reasons: list[str] = []
    measured = {task: ok for task, ok in last.items() if ok is not None}
    if not measured:
        return ["벤치가 한 과제도 못 쟀습니다(결과 파일 없음)"]
    wrong = [task for task, ok in measured.items() if ok is False]
    if len(wrong) * 2 >= len(measured):
        reasons.append(f"한 밤에 {len(wrong)}/{len(measured)} 과제가 틀렸습니다: {', '.join(wrong)}")
    if len(history) >= 2:
        before = history[-2].get("tasks") or {}
        twice = [task for task in wrong if before.get(task) is False]
        if twice:
            reasons.append(f"이틀 연속 틀린 과제: {', '.join(twice)}")
    return reasons


def _notify(title: str, message: str) -> None:
    sys.path.insert(0, str(RUNTIME / "src"))
    try:
        from alture_jarvis.events import EventBus
        from alture_jarvis.notifications import NotificationService

        NotificationService(EventBus()).notify(title, message)
    except Exception:  # noqa: BLE001 — 알림이 실패해도 기록은 남는다(ALERT 파일)
        pass


def main() -> int:
    NIGHTLY.mkdir(parents=True, exist_ok=True)
    label = "nightly" + _dt.datetime.now().strftime("%Y%m%d")
    record: dict[str, Any] = {"label": label, "started_at": _dt.datetime.now().isoformat(timespec="seconds")}
    if not _wait_for_idle():
        record["skipped"] = "운영 온텔릭이 30분 동안 바빴거나 꺼져 있었다"
    else:
        record["exit"] = _run_bench(label)
        record["tasks"] = _results(label)
    record["new_tool_calls_24h"] = _new_tool_calls()
    history_path = NIGHTLY / "history.jsonl"
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    history = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    reasons = judge([row for row in history if "tasks" in row])
    if reasons and "tasks" in record:
        (NIGHTLY / "ALERT.txt").write_text(label + "\n" + "\n".join(reasons) + "\n", encoding="utf-8")
        _notify("Ontelic 밤 벤치: 사이트가 바뀐 것 같습니다", " · ".join(reasons))
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
