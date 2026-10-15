"""줄의 값은 **값 칸**에서 읽는다 — 풀어 쓴 칸(비고) 속의 금액은 그 줄의 가격이 아니다 (2026-10-11).

실제 판 둘(스킬팩 영상 촬영 판 2ada3393 · 운영 판 bc618f94): 세 가게의 가격을 읽어 엑셀로 쓴 줄이
`["11번가", 상품 이름, "139,700원", "무료", 주소, "제주·도서산간 추가 5,000원. 카드·쿠폰 할인 제외"]` 였다. 판매 가격 139,700원은
그 페이지 앞머리에 그대로 있었다. 그런데 검사는 이름 칸을 뺀 **모든 칸의 금액**을 그 줄의 값으로 모아, 비고의 「5,000원」(도서산간
추가 배송비)이 페이지 앞머리에 없다고 「줄의 값이 그 페이지와 다릅니다: 11번가 5,000원 — 그 페이지 첫머리에는 139,700원」을 냈다.

이 판정은 파일을 **쓰는 순간**에도 불린다(`_write_grounding_feedback`). 모델은 자기 표가 맞다는 것을 알면서도(「실제로 읽은 값은
무료배송(도서산간 추가 5,000원)인데 검증이 첫머리 값만 기준으로 하므로…」) 검사를 통과하려고 엑셀을 두 번 고쳐 썼고,
마지막 답에는 헛경고가 그대로 붙었다.

지키는 것: 그 칸이 **값 그 자체**일 때(금액으로 시작하는 칸)만 그 줄의 값으로 센다. 문장 속에 금액이 섞인 칸은 설명이다.
원래 잡으려던 것(값 칸에 옆 책 · 추천 띠의 값을 적은 줄)은 그대로 잡는다.
"""
from __future__ import annotations

from alture_jarvis.agent import BrowserAgent

NAME = "[정품] 로지텍 MX Master 마스터 3S 블랙 무선마우스 수신기 포함"
HEAD = (
    "11번가 [정품] 로지텍 MX Master 마스터 3S 블랙 무선마우스 수신기 포함 온라인최저가 139,700원 138,310원 최대할인가 "
    "최대 적립 포인트 7,155P 최대 16개월 무이자 할부"
)
URL = "https://www.11st.co.kr/products/8852665861"


def test_an_amount_inside_a_note_is_not_the_rows_value() -> None:
    row = ["11번가", NAME, "139,700원", "무료", URL, "제주·도서산간 추가 5,000원. 카드·쿠폰 할인 제외"]

    assert BrowserAgent._row_value_mismatch(row, NAME, HEAD) is None


def test_several_amounts_inside_a_note_are_not_the_rows_values() -> None:
    row = ["G마켓", NAME, "139,700원", "무료(제주 3,000원/도서산간 7,000원)", URL,
           "제주 20,000원·도서산간 40,000원 추가. 쿠폰가 136,520원(2% 쿠폰 -2,780원)"]

    assert BrowserAgent._row_value_mismatch(row, NAME, HEAD) is None


def test_a_wrong_price_in_the_value_cell_is_still_caught() -> None:
    """원래 잡으려던 것(2026-09-28 T1 O3) — 값 칸에 그 페이지 앞머리에 없는 값을 적은 줄."""
    wrong = BrowserAgent._row_value_mismatch(["11번가", NAME, "27,000원", "무료", URL, ""], NAME, HEAD)

    assert wrong is not None and "27,000원" in wrong[0] and "139,700원" in wrong[1]


def test_a_value_cell_with_a_trailing_remark_is_still_a_value_cell() -> None:
    wrong = BrowserAgent._row_value_mismatch(["11번가", NAME, "27,000원 (10% 할인)", "무료"], NAME, HEAD)
    assert wrong is not None and "27,000원" in wrong[0]

    points = BrowserAgent._row_value_mismatch(["11번가", NAME, "139,700원", "12,600P (5% 적립 기준)"], NAME, HEAD)
    assert points is not None and "12,600P" in points[0]


def test_emphasis_does_not_hide_a_value_cell() -> None:
    for cell in ("**27,000원**", "  27,000원", "*27,000원*", "약 27,000원", "₩ 27,000원"):
        wrong = BrowserAgent._row_value_mismatch(["11번가", NAME, cell, "무료"], NAME, HEAD)
        assert wrong is not None and "27,000원" in wrong[0], cell


def test_the_right_price_with_a_note_passes_whatever_the_note_says() -> None:
    for note in ("할인 전 775,000원. 2026-10-11 기준", "80몰 중 최저가. 화이트 옵션은 131,510원", "배송비 2,500원 별도"):
        assert BrowserAgent._row_value_mismatch(["11번가", NAME, "139,700원", "무료", URL, note], NAME, HEAD) is None, note


def test_the_write_time_pushback_no_longer_fires_on_the_note() -> None:
    """쓰는 순간의 되돌림도 같은 판정을 쓴다 — 여기서 헛울리면 모델이 맞는 표를 고쳐 쓴다."""
    import inspect

    source = inspect.getsource(BrowserAgent._write_grounding_feedback)
    assert "_row_page_binding_check" in source, "쓰는 순간의 되돌림이 같은 판정을 쓴다는 전제"
    binding = inspect.getsource(BrowserAgent._row_page_binding_check)
    assert "_row_value_mismatch" in binding
