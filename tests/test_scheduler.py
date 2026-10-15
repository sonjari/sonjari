from __future__ import annotations

import time
from pathlib import Path

from alture_jarvis.events import EventBus
from alture_jarvis.models import RiskLevel
from alture_jarvis.scheduler import TaskScheduler


def test_schedule_persists_and_dispatches(tmp_path: Path) -> None:
    calls: list[tuple[str, str, dict, RiskLevel]] = []

    def enqueue(kind: str, title: str, payload: dict, risk: RiskLevel) -> dict:
        calls.append((kind, title, payload, risk))
        return {"id": "job-1"}

    scheduler = TaskScheduler(tmp_path / "jarvis.db", EventBus(), enqueue)
    row = scheduler.create({"title": "점검", "prompt": "상태 점검", "delay_minutes": 0.001})
    assert row["status"] == "pending"
    scheduler.start()
    deadline = time.time() + 3
    while not calls and time.time() < deadline:
        time.sleep(0.05)
    scheduler.stop()

    assert calls[0][0] == "chat"
    assert calls[0][2]["scheduled"] is True
    assert scheduler.get(row["id"])["status"] == "dispatched"
