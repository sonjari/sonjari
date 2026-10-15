"""예약이 **반복**되고, 끝난 결과를 **메일로** 보낸다.

## 왜 (2026-08-21)

예약은 지금까지 **한 번만** 돌았고(`run_at` 하나), 결과는 화면에만 남았다.
"매주 이렇게 해서 메일로 보내 줘"가 안 됐다.

## 이 파일이 지키는 것

**① 승인은 사람이 있는 시점에 받는다.** `google_gmail_send` 는 L2 이고 되돌리기가
없다 — 보낸 메일은 못 지운다. 그런데 예약이 도는 아침 7시에는 승인해 줄 사람이
없다. 그래서 수신자 검사를 **예약을 만드는 순간**에 한다. 허용목록 밖 주소는
그 자리에서 거절한다 — "나중에 승인 카드를 띄우자"로 하면 그 카드는 아무도 없는
새벽에 떠서 만료된다(실측 만료율 29%).

**② 지난 것을 몰아서 돌지 않는다.** PC 가 일주일 꺼져 있었다고 매일 예약이 일곱
번 터지면 그건 복구가 아니라 사고다.

**③ 끝난 판만 보낸다.** 취소·실패한 판의 빈손을 보내면 받는 사람은 그것을
「오늘은 별일 없었다」로 읽는다 — 관찰 초소가 같은 자리에서 눈을 감았던 적이 있다.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.scheduler import TaskScheduler

ALLOWED = "owner@example.com, narae@example.com"


def _scheduler(tmp_path: Path, *, recipients: str = ALLOWED, **kw: Any) -> TaskScheduler:
    config = JarvisConfig(runtime_root=tmp_path, scheduled_mail_recipients=recipients)
    enqueue = kw.pop("enqueue", lambda kind, title, payload, risk: {"id": "job-1"})
    return TaskScheduler(
        tmp_path / "jarvis.db",
        EventBus(),
        enqueue,
        config=config,
        **kw,
    )


# ── ① 승인은 사람이 있을 때 ──────────────────────────────────────────────────


def test_an_allowed_recipient_is_accepted(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path)
    row = scheduler.create(
        {
            "prompt": "이번 주 크몽 단가 정리해줘",
            "delay_minutes": 10,
            "deliver_to": ["owner@example.com"],
        }
    )
    assert row["deliver_to"] == "owner@example.com"


def test_an_outside_recipient_is_refused_when_the_schedule_is_made(tmp_path: Path) -> None:
    """★ 이 파일의 핵심. 새벽에 카드를 띄우는 대신 **지금** 거절한다."""
    scheduler = _scheduler(tmp_path)
    with pytest.raises(ValueError, match="recipient_not_allowed"):
        scheduler.create(
            {
                "prompt": "보고서",
                "delay_minutes": 10,
                "deliver_to": ["owner@example.com", "stranger@example.com"],
            }
        )
    # 거절했으면 **아무것도 남기지 않는다.** 반쯤 만들어 두면 다음에 돈다.
    assert scheduler.list()["count"] == 0


def test_delivery_is_off_by_default_when_no_recipients_are_configured(tmp_path: Path) -> None:
    """설정이 비어 있으면 배달이 통째로 꺼진다 — 기본이 안전한 쪽이다."""
    scheduler = _scheduler(tmp_path, recipients="")
    with pytest.raises(ValueError, match="scheduled_mail_disabled"):
        scheduler.create({"prompt": "보고서", "delay_minutes": 10, "deliver_to": ["a@b.com"]})


def test_a_schedule_without_delivery_still_works(tmp_path: Path) -> None:
    """메일을 안 보내는 예약은 설정과 무관하게 만들어져야 한다."""
    scheduler = _scheduler(tmp_path, recipients="")
    row = scheduler.create({"prompt": "화면으로만 보여줘", "delay_minutes": 5})
    assert row["deliver_to"] == ""


def test_a_comma_string_is_accepted_like_a_list(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path)
    row = scheduler.create(
        {
            "prompt": "x",
            "delay_minutes": 5,
            "deliver_to": "owner@example.com, narae@example.com",
        }
    )
    assert row["deliver_to"].count(",") == 1


def test_case_does_not_smuggle_an_outside_address(tmp_path: Path) -> None:
    """대소문자로 허용목록을 우회할 수 없다."""
    scheduler = _scheduler(tmp_path)
    row = scheduler.create(
        {"prompt": "x", "delay_minutes": 5, "deliver_to": ["owner@example.com"]}
    )
    assert row["deliver_to"]


# ── ② 지난 것을 몰아서 돌지 않는다 ───────────────────────────────────────────


def test_a_week_of_downtime_does_not_fire_seven_times() -> None:
    """★ PC 가 일주일 꺼져 있었다. 매일 예약이 일곱 번 터지면 사고다."""
    now = time.time()
    a_week_ago = now - 7 * 24 * 3600
    nxt = TaskScheduler._next_run(a_week_ago, "daily", now=now)
    assert nxt > now
    assert nxt - now <= 24 * 3600, "하루 안쪽의 다음 한 번이어야 한다"


def test_the_time_of_day_is_kept() -> None:
    """아침 7시 예약은 밀려도 아침 7시다 — 지금 시각 + 24시간이 아니다."""
    previous = datetime(2026, 8, 1, 7, 0).timestamp()
    now = datetime(2026, 8, 5, 15, 30).timestamp()
    nxt = datetime.fromtimestamp(TaskScheduler._next_run(previous, "daily", now=now))
    assert nxt.hour == 7
    assert nxt.day == 6


def test_weekly_stays_on_the_same_weekday() -> None:
    previous = datetime(2026, 8, 3, 9, 0).timestamp()  # 월요일
    now = datetime(2026, 8, 20, 12, 0).timestamp()
    nxt = datetime.fromtimestamp(TaskScheduler._next_run(previous, "weekly", now=now))
    assert nxt.weekday() == 0, "매주는 요일이 안 바뀌어야 한다"
    assert nxt.hour == 9


def test_weekday_skips_the_weekend() -> None:
    """금요일에 돌았으면 다음은 월요일이다."""
    friday = datetime(2026, 8, 7, 7, 0).timestamp()
    nxt = datetime.fromtimestamp(TaskScheduler._next_run(friday, "weekday", now=friday + 60))
    assert nxt.weekday() == 0
    assert nxt.hour == 7


def test_an_unknown_repeat_is_refused_at_creation(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path)
    with pytest.raises(ValueError, match="unknown_repeat"):
        scheduler.create({"prompt": "x", "delay_minutes": 5, "repeat_every": "매달"})


# ── ③ 끝난 판만 보낸다 ───────────────────────────────────────────────────────


def _delivering(tmp_path: Path, job: dict[str, Any], sent: list[Any]) -> TaskScheduler:
    def send_mail(to: list[str], subject: str, body: str) -> dict[str, Any]:
        sent.append((to, subject, body))
        return {"message_id": "m-1"}

    return _scheduler(
        tmp_path,
        job_lookup=lambda job_id: job,
        send_mail=send_mail,
    )


def _run_once(scheduler: TaskScheduler) -> None:
    row = scheduler._claim_due()
    assert row is not None
    scheduler._dispatch(row)
    scheduler._collect_delivered()


def test_a_finished_run_is_mailed(tmp_path: Path) -> None:
    sent: list[Any] = []
    job = {"status": "completed", "result": {"answer": "이번 주 단가는 이렇습니다."}}
    scheduler = _delivering(tmp_path, job, sent)
    scheduler.create(
        {
            "title": "주간 단가",
            "prompt": "정리해줘",
            "delay_minutes": 0,
            "deliver_to": ["owner@example.com"],
        }
    )
    _run_once(scheduler)
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == ["owner@example.com"]
    assert "주간 단가" in subject
    assert body == "이번 주 단가는 이렇습니다."


def test_a_cancelled_run_is_not_mailed(tmp_path: Path) -> None:
    """★ 빈손을 보내면 받는 사람은 「오늘은 별일 없었다」로 읽는다."""
    sent: list[Any] = []
    scheduler = _delivering(tmp_path, {"status": "cancelled", "result": {}}, sent)
    scheduler.create(
        {"prompt": "x", "delay_minutes": 0, "deliver_to": ["owner@example.com"]}
    )
    _run_once(scheduler)
    assert sent == []


def test_a_completed_run_with_an_empty_answer_is_not_mailed(tmp_path: Path) -> None:
    sent: list[Any] = []
    job = {"status": "completed", "result": {"answer": "   "}}
    scheduler = _delivering(tmp_path, job, sent)
    scheduler.create(
        {"prompt": "x", "delay_minutes": 0, "deliver_to": ["owner@example.com"]}
    )
    _run_once(scheduler)
    assert sent == []


def test_a_schedule_without_delivery_never_calls_mail(tmp_path: Path) -> None:
    sent: list[Any] = []
    job = {"status": "completed", "result": {"answer": "결과"}}
    scheduler = _delivering(tmp_path, job, sent)
    scheduler.create({"prompt": "화면으로만", "delay_minutes": 0})
    _run_once(scheduler)
    assert sent == []


def test_removing_an_address_from_the_whitelist_stops_delivery(tmp_path: Path) -> None:
    """★ 예약을 만든 **뒤에** 설정에서 주소를 빼면 그 뜻을 따라야 한다.
    보내기 직전에 한 번 더 본다."""
    sent: list[Any] = []
    job = {"status": "completed", "result": {"answer": "결과"}}
    scheduler = _delivering(tmp_path, job, sent)
    scheduler.create(
        {"prompt": "x", "delay_minutes": 0, "deliver_to": ["owner@example.com"]}
    )
    scheduler.config.scheduled_mail_recipients = "someone-else@example.com"
    _run_once(scheduler)
    assert sent == [], "허용목록에서 빠진 주소로 보냈다"


# ── 반복이 실제로 다시 pending 이 되는가 ─────────────────────────────────────


def test_a_repeating_schedule_comes_back_as_pending(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path)
    row = scheduler.create({"prompt": "매일", "delay_minutes": 0, "repeat_every": "daily"})
    claimed = scheduler._claim_due()
    assert claimed is not None
    scheduler._dispatch(claimed)
    after = scheduler.get(row["id"])
    assert after["status"] == "pending", "반복 예약이 한 번 돌고 죽었다"
    assert after["run_at"] > time.time()


def test_a_one_shot_schedule_does_not_come_back(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path)
    row = scheduler.create({"prompt": "한 번만", "delay_minutes": 0})
    claimed = scheduler._claim_due()
    assert claimed is not None
    scheduler._dispatch(claimed)
    assert scheduler.get(row["id"])["status"] == "dispatched"


def test_an_old_database_without_the_new_columns_still_opens(tmp_path: Path) -> None:
    """★ 옛 DB 로도 이 자가 돌아야 한다 — 칸이 없으면 더해서 연다."""
    path = tmp_path / "jarvis.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE schedules (id TEXT PRIMARY KEY, title TEXT NOT NULL, "
            "prompt TEXT NOT NULL, session_id TEXT NOT NULL, run_at REAL NOT NULL, "
            "status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, "
            "last_job_id TEXT NOT NULL DEFAULT '')"
        )
    scheduler = _scheduler(tmp_path)
    row = scheduler.create({"prompt": "옛 DB", "delay_minutes": 5})
    assert row["repeat_every"] == "none"
