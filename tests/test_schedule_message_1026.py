"""정해진 문구 알림 — 그 시각에 모델 없이 글 그대로 디스코드로, 매일 되풀이 (2026-10-26 나래)."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from alture_jarvis.events import EventBus
from alture_jarvis.scheduler import TaskScheduler

TEXT = "[08:30] 나래, 오늘 할 일 딱 하나만 적어."


def _scheduler(tmp_path: Path, sent: list[str], fail: bool = False) -> TaskScheduler:
    def send(text: str) -> None:
        if fail:
            raise RuntimeError("discord down")
        sent.append(text)

    def no_enqueue(*_args, **_kwargs):
        raise AssertionError("정해진 문구 알림은 모델 잡을 만들지 않는다")

    return TaskScheduler(tmp_path / "j.db", EventBus(), no_enqueue,
                         config=SimpleNamespace(scheduler_enabled=True, data_dir=tmp_path), send_discord=send)


def test_message_goes_out_as_is_and_repeats_daily(tmp_path: Path) -> None:
    sent: list[str] = []
    scheduler = _scheduler(tmp_path, sent)
    made = scheduler.create({"kind": "message", "message": TEXT, "run_at": time.time() + 1, "repeat_every": "daily"})
    assert made["kind"] == "message"
    assert scheduler._claim_due() is None  # 아직 시각 전
    time.sleep(1.2)
    scheduler._dispatch(scheduler._claim_due())
    assert sent == [TEXT]
    after = scheduler.get(made["id"])
    assert after["status"] == "pending" and after["run_at"] > time.time() + 23 * 3600
    assert json.loads(after["last_result"])["ok"] is True


def test_failed_send_keeps_the_schedule(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path, [], fail=True)
    made = scheduler.create({"kind": "message", "message": TEXT, "run_at": time.time() + 1, "repeat_every": "daily"})
    time.sleep(1.2)
    scheduler._dispatch(scheduler._claim_due())
    after = scheduler.get(made["id"])
    assert after["status"] == "pending"
    assert json.loads(after["last_result"])["ok"] is False


def test_empty_message_and_unknown_channel_are_refused(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path, [])
    with pytest.raises(ValueError):
        scheduler.create({"kind": "message", "message": "", "run_at": time.time() + 60})
    with pytest.raises(ValueError):
        scheduler.create({"kind": "message", "message": TEXT, "channel": "slack", "run_at": time.time() + 60})
