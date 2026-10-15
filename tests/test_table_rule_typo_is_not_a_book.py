"""표 구분줄 오타 하나가 **틀린 정직 경고**로 번지지 않는다 (2026-09-30 홈페이지 촬영 판).

모델이 구분줄을 `| :--- | :--- | :---0 |` 로 냈다(끝에 0). 그러자 둘이 한꺼번에 무너졌다.

- 화면: 마크다운 해석기가 표를 못 알아봐 「| 제목 | 판매가 | …」를 글로 뭉개 보였다.
- 검사기: 머리줄을 못 알아봐 **열 이름 「제목」을 책 이름으로 세고**, 세 권을 다 직접 읽은 맞는 답에
  「⚠ 읽지 않고 적은 것이 있습니다: 제목」을 붙였다. 시킨 것도 3/3 이 아니라 2/3 으로 찍혔다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent, repair_table_rules

#: 촬영 판(잡 4d467b9b) 답의 표 그대로.
REAL_ANSWER = (
    "**[조사 결과 요약]**\n\n"
    "| 제목 | 판매가 | 적립 포인트 |\n"
    "| :--- | :--- | :---0 |\n"
    "| 초보자를 위한 파이썬(Python) 200제 | 18,000원 | 1,000P |\n"
    "| 파이썬(Python) 3학년 머신러닝의 구조 | 16,200원 | 900P |\n"
    "| Do it! 점프 투 파이썬 | 19,800원 | 1,100P |\n"
)
READ = [{"role": "tool", "tool_name": "browser_extract", "content": (
    "초보자를 위한 파이썬(Python) 200제 18,000원 적립 1,000P\n"
    "파이썬(Python) 3학년 머신러닝의 구조 16,200원 900P\n"
    "Do it! 점프 투 파이썬 19,800원 1,100P"
)}]


def test_a_typo_in_the_rule_line_does_not_make_the_header_a_book() -> None:
    note = BrowserAgent._listed_entity_grounding_check(REAL_ANSWER, READ)

    assert note == "", f"열 이름을 책 이름으로 셌다: {note[:120]}"


def test_a_made_up_book_is_still_caught_in_the_same_table() -> None:
    """반대 방향 — 너그러워진 것은 구분줄뿐이다. 안 읽은 책은 여전히 잡는다."""
    answer = REAL_ANSWER + "| 혼자 공부하는 파이썬 | 22,000원 | 1,200P |\n"

    note = BrowserAgent._listed_entity_grounding_check(answer, READ)

    # 경고는 이름을 **원래 표기**로 적는다(2026-10-01 — 대조는 공백을 지우고 하지만, 「CorsairDarkCore」처럼 읽기 어려웠다).
    named = note.split("있습니다:")[1].split(".**")[0]
    assert "혼자 공부하는 파이썬" in named
    assert "제목" not in named


def test_the_answer_shown_on_screen_gets_a_proper_rule_line() -> None:
    fixed = repair_table_rules(REAL_ANSWER)

    assert "| :--- | :--- | :--- |" in fixed
    assert ":---0" not in fixed
    # 나머지 줄은 한 글자도 안 건드린다.
    assert fixed.replace("| :--- | :--- | :--- |", "") == REAL_ANSWER.replace("| :--- | :--- | :---0 |", "")


def test_repair_leaves_good_tables_and_plain_text_alone() -> None:
    good = "| 가 | 나 |\n| ---: | :---: |\n| 1 | 2 |\n"
    prose = "대시로 쓴 줄\n---\n그 아래 글"
    lonely = "| --- | ---x |"  # 위에 머리줄이 없으면 표가 아니다

    assert repair_table_rules(good) == good
    assert repair_table_rules(prose) == prose
    assert repair_table_rules(lonely) == lonely


def test_a_run_without_an_answer_does_not_crash() -> None:
    """답이 없는 판(None)을 그대로 돌려준다 — `.split` 을 불러 판을 죽였다(2026-09-30 촬영 판 5f45a7e3)."""
    assert repair_table_rules(None) is None
    assert repair_table_rules("") == ""
