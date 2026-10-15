"""「| 분야 | 주요 내용 |」 표의 첫 칸은 분류 이름이다 (2026-10-01 운영 뉴스 판).

「오늘자 국내 뉴스 네이버에서 알아봐 줘」에 네이버 뉴스 검색·주요뉴스·목록을 거쳐 일곱 걸음을 읽고 제대로
답했는데, 끝의 요약 표 첫 칸(「정치/안보」·「경제/금융」)을 이름으로 잡아 「읽지 않고 적은 것이 있습니다」를 붙였다.
틀린 경고는 사람이 진짜 경고를 안 읽게 만든다.
"""

from alture_jarvis.agent import BrowserAgent

PAGE = "김여정 DMZ 지뢰 자작극 반박 ... DSR 적용 예외 비중 70% ... 청년미래적금 2차 모집 10월 7일 ... 일본 인구 317만명 감소"
MESSAGES = [
    {"role": "user", "content": "오늘자 국내 뉴스 네이버에서 한번 알아봐줄수있나"},
    {"role": "tool", "content": PAGE},
]


def _answer(first_header: str) -> str:
    return (
        f"| {first_header} | 주요 내용 |\n| :--- | :--- |\n"
        "| **정치/안보** | 김여정 DMZ 지뢰 책임 부인 |\n"
        "| **경제/금융** | DSR 예외 비중 70% 돌파 / 청년미래적금 2차 모집 |\n"
        "| **사회** | 일본 인구 317만명 감소 |\n"
    )


def test_field_column_of_a_news_summary_is_not_checked_as_names():
    assert BrowserAgent._listed_entity_grounding_check(_answer("분야"), MESSAGES) == ""


def test_other_category_headers_too():
    for header in ("부문", "영역", "주제"):
        assert BrowserAgent._listed_entity_grounding_check(_answer(header), MESSAGES) == "", header


def test_a_name_column_is_still_checked():
    # 머리가 분류가 아니면 첫 칸은 여전히 이름이다 — 안 읽은 회사는 잡힌다.
    answer = "| 회사 | 내용 |\n| :--- | :--- |\n| 도담스페이스 | 정규직 |\n| 바름터 | 경력 3년 |\n"
    warning = BrowserAgent._listed_entity_grounding_check(answer, MESSAGES)
    assert "도담스페이스" in warning and "바름터" in warning
