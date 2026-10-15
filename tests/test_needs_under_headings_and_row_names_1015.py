"""「돌려받을 항목(needs)」 검사가 **제목 아래 목록**과 **첫 칸이 이름인 표**도 본다 (2026-10-15).

같은 날 바깥 AI 가 맡긴 조사 판: 답에 「좋게 보는 점」 · 「나쁘게 보는 점」 · 「평가 점수」를 제목 아래 다 썼는데 1/6 으로 셌다.
검사는 표 머리와 「이름: 값」 줄만 봤다. 그날까지의 17판에 옛 · 새 검사를 나란히 대 보니 바뀐 것은 3판 5항목이고
다섯 모두 답에 실제로 있었다. 낱말이 다른 항목(「회사 국적과 설립」 ↔ 「국가/위치」 · 「설립」)은 여전히 못 채운 것으로 센다.
표본 글은 지어낸 것이다.
"""
from __future__ import annotations

from alture_jarvis.outbound import check_needs


def _met(needs: list[str], answer: str) -> dict[str, bool]:
    return {item["label"]: item["met"] for item in check_needs(needs, answer)}


def test_a_heading_that_names_the_item_with_a_list_under_it_counts() -> None:
    answer = "## ① 가상 모델\n\n### 좋게 보는 점\n- 크기 대비 빠르다\n\n### 나쁘게 보는 점\n\n- 라이선스가 좁다\n\n## ④ 댓글 분위기\n대체로 반긴다\n"

    assert _met(["좋게 보는 점", "나쁘게 보는 점", "분위기"], answer) == {"좋게 보는 점": True, "나쁘게 보는 점": True, "분위기": True}


def test_a_heading_with_nothing_under_it_does_not_count() -> None:
    answer = "### 좋게 보는 점\n\n### 나쁘게 보는 점\n- 느리다\n"

    assert _met(["좋게 보는 점"], answer) == {"좋게 보는 점": False}


def test_a_short_heading_does_not_fill_a_longer_item() -> None:
    # 「정리」 제목 하나가 「정리 날짜」를 채운 것으로 세면 안 된다 — 제목이 이름을 담을 때만.
    answer = "### 정리\n- 이것저것\n"

    assert _met(["정리 날짜"], answer) == {"정리 날짜": False}


def test_a_table_whose_first_cell_names_the_item_counts() -> None:
    answer = "| 항목 | 값 |\n|---|---|\n| **라이선스** | **MIT** |\n| 크기 | 30B |\n"

    assert _met(["라이선스"], answer) == {"라이선스": True}


def test_a_row_name_inside_a_longer_item_does_not_fill_it() -> None:
    answer = "| 항목 | 내용 |\n|---|---|\n| 국가/위치 | 가상국 |\n| 설립 | 2023년 |\n"

    assert _met(["회사 국적과 설립"], answer) == {"회사 국적과 설립": False}


def test_a_row_with_only_blanks_beside_the_name_does_not_count() -> None:
    answer = "| 항목 | 값 |\n|---|---|\n| 라이선스 | - |\n"

    assert _met(["라이선스"], answer) == {"라이선스": False}
