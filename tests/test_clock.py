from __future__ import annotations

from datetime import datetime

import pytest

from alture_jarvis.clock import KST, now_line_ko


def test_the_line_states_date_weekday_and_time_in_korean() -> None:
    # 2026-08-03 is a Monday.
    line = now_line_ko(datetime(2026, 8, 3, 23, 27, tzinfo=KST))
    assert "2026년 8월 3일" in line
    assert "월요일" in line
    assert "23:27" in line
    assert "KST" in line


def test_seconds_are_dropped_so_the_prompt_is_stable_between_messages() -> None:
    # A second-by-second string invalidates the model's cached prefix on every
    # single message and buys nothing.
    early = now_line_ko(datetime(2026, 8, 3, 23, 27, 1, tzinfo=KST))
    late = now_line_ko(datetime(2026, 8, 3, 23, 27, 59, tzinfo=KST))
    assert early == late


def test_it_tells_the_model_not_to_guess() -> None:
    # The whole point: without this the model answers "오늘 며칠이야?" from its
    # training data, confidently and wrongly.
    assert "그대로 쓴다" in now_line_ko(datetime(2026, 8, 3, 9, 5, tzinfo=KST))


def test_the_weekday_is_labelled_and_must_not_be_recomputed() -> None:
    # Measured: with the fields run together in one sentence, the model copied
    # the date and the time correctly and then worked out the weekday itself --
    # and got it wrong (일요일 for a Monday).
    line = now_line_ko(datetime(2026, 8, 3, 23, 33, tzinfo=KST))
    assert "- 요일: 월요일" in line
    assert "직접 계산하지 마라" in line


@pytest.mark.parametrize(
    "day,weekday",
    [(3, "월"), (4, "화"), (5, "수"), (6, "목"), (7, "금"), (8, "토"), (9, "일")],
)
def test_every_weekday_maps_correctly(day: int, weekday: str) -> None:
    assert f"{weekday}요일" in now_line_ko(datetime(2026, 8, day, 12, 0, tzinfo=KST))


def test_the_assistant_and_the_agent_are_told_the_same_time() -> None:
    # They used to build their own strings, in different formats and different
    # timezones, so a dispatched agent could be working on a different "today"
    # than the assistant that sent it.
    from alture_jarvis import agent as agent_module
    from alture_jarvis import runtime as runtime_module

    assert agent_module.now_line_ko is runtime_module.now_line_ko
