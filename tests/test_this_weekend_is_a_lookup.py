"""이번 주 토요일이 며칠인지는 모델이 더해서는 안 된다.

2026-09-04(금)에 「이번주 토일 갈 수 있는 숙소」를 시켰더니 **9/6~9/7** 로 찾았다.
맞는 값은 9/5~9/6 이다. 오늘 날짜와 요일은 프롬프트에 있었지만, 거기서 「이번 주
토요일」로 가려면 여전히 모델이 더해야 했다 — 그리고 틀렸다. 그 날짜로 숙소를
찾으면 엉뚱한 밤을 예약한다.

요일을 계산하지 말라고 적어 둔 것과 같은 처방이다: 찾아 쓸 수 있게 펼쳐 둔다.
"""

from __future__ import annotations

from datetime import datetime

from alture_jarvis.clock import KST, now_line_ko, upcoming_days_ko


def _friday() -> datetime:
    return datetime(2026, 9, 4, 23, 45, tzinfo=KST)


def test_this_weekend_can_be_looked_up_not_computed() -> None:
    """실제로 틀렸던 그 판."""
    text = upcoming_days_ko(_friday())
    assert "9월 5일 토요일" in text
    assert "9월 6일 일요일" in text
    assert "9월 6일 토요일" not in text, "자비스가 답했던 틀린 값"


def test_today_tomorrow_and_the_day_after_are_labelled() -> None:
    text = upcoming_days_ko(_friday())
    assert "9월 4일 금요일 (오늘)" in text
    assert "9월 5일 토요일 (내일)" in text
    assert "9월 6일 일요일 (모레)" in text


def test_it_crosses_a_month_boundary() -> None:
    text = upcoming_days_ko(datetime(2026, 8, 30, 9, 0, tzinfo=KST))
    assert "8월 30일 일요일 (오늘)" in text
    assert "9월 1일 화요일 (모레)" in text


def test_the_upcoming_days_ride_along_with_the_clock() -> None:
    """시각 줄에 붙어 있어야 한다 — 따로 만들어 놓고 안 쓰면 없는 것과 같다."""
    line = now_line_ko(_friday())
    assert "9월 5일 토요일" in line
    assert "- 요일: 금요일" in line


def test_the_changing_part_still_sits_last() -> None:
    """캐시 규칙을 깨지 않는다 — 시각 블록은 시스템 프롬프트 맨 뒤다.

    여기서는 그 블록 **안에서** 순서만 확인한다: 고정 문구가 앞, 펼친 날짜가 뒤.
    """
    line = now_line_ko(_friday())
    assert line.index("현재 한국 시각") < line.index("앞으로의 날짜")
