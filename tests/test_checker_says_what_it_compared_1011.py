"""검사는 **무엇과 견줬는지**를 말하고, 견주지 못한 줄을 말없이 넘기지 않는다 (2026-10-11).

레딧에 「검사기가 틀려서 모델이 맞는 표를 두 번 고쳐 썼다」는 글을 올렸더니 이런 답이 달렸다(뜻만 옮김):

    검사기가 어느 칸과 어떤 두 값을 견줬는지 찍게 하고, 짝을 못 찾은 줄은 통과시키지 마라.
    무엇이 다른지 안 보여 주고 맞다 · 틀리다만 말하는 검사기는 모델에게 답을 비트는 법을 가르친다.

우리 경고는 두 값은 보여 줬지만(「229,020원 — 그 페이지 첫머리에는 279,290원」) **어느 자리의 값인지**는 말하지 않았다.
모델이 제 입으로 「검증이 첫머리 값만 기준으로 하므로 …」라고 추측했다. 그리고 짝을 못 찾은 줄은 판정 없이 지나갔다.

① 견준 것을 말한다 — 가게별 값 규칙이 있으면 그 칸 이름과 값(「판매가(할인 적용 …) 229,020원」), 없으면 「본문 앞 900자에 보이는 금액」.
② 주소를 적는 표에서 **주소가 안 적힌 줄**은 「어느 페이지에서 읽었는지 적히지 않아 대조하지 못한 줄」로 알린다.
   모델을 막지는 않는다(2026-09-28: 막고 다시 쓰게 한 세 판 모두 정답 0). 쓰는 순간의 안내와 답 끝의 경고에 같이 나간다.

표본의 상품 이름 · 값은 지어낸 것이다.
"""
from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent

from test_page_value_recipes_shops_1011 import DANAWA, DANAWA_BODY, ELEVEN, ELEVEN_DISCOUNT

NAME = "가상 무선 마우스 M3"
PLAIN = "https://shop.example/products/77"
PLAIN_BODY = f"{NAME} 블랙\n판매가 15,000원\n배송비 무료\n" + "상품 설명 " * 400
TITLES = {
    DANAWA: f"{NAME} (정품) (블랙) : 다나와 가격비교",
    ELEVEN: f"[정품] {NAME} 블랙 수신기 포함",
    PLAIN: f"{NAME} 블랙 - 어느 가게",
}
BODIES = {DANAWA: DANAWA_BODY, ELEVEN: ELEVEN_DISCOUNT, PLAIN: PLAIN_BODY}
HEADER = ["가게", "상품 이름", "판매 가격", "배송비", "읽은 페이지 주소", "비고"]


def _steps(rows: list[list[Any]], header: list[str] | None = None, pages: tuple[str, ...] = (DANAWA, ELEVEN, PLAIN)) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for number, url in enumerate(pages, start=1):
        steps.append({
            "step": number, "tool": "browser_extract", "ok": True,
            "evidence": {"url": url, "title": TITLES[url]},
            "evidence_record": {"type": "body_read", "ok": True, "source_id": url, "step": number, "job_id": "j"},
        })
    steps.append({
        "step": len(steps) + 1, "tool": "local_write_document", "ok": True,
        "arguments": {"format": "xlsx", "path": "가격조사.xlsx", "sheets": {"가격 비교": [header or HEADER, *rows]}},
        "evidence": {"action": "local_write_document", "format": "xlsx", "output_path": "가격조사.xlsx", "verified": True},
    })
    return steps


def _notes(rows: list[list[Any]], **kwargs: Any) -> str:
    bodies = {BrowserAgent._url_key(url): body for url, body in BODIES.items()}
    return BrowserAgent._row_page_binding_check("", _steps(rows, **kwargs), bodies)


# --- ① 무엇과 견줬는지 말한다 -------------------------------------------------------

def test_a_wrong_value_is_shown_next_to_the_named_field_it_was_compared_with() -> None:
    notes = _notes([["11번가", NAME, "226,730원", "무료", ELEVEN, ""]])

    assert "줄의 값이 그 페이지와 다릅니다" in notes and "226,730원" in notes
    assert "판매가(할인 적용 · 카드·페이 할인 제외) 229,020원" in notes, "그 가게의 값 규칙이 읽은 칸 이름과 값이 같이 나온다"
    assert "할인 전 판매가 279,290원" in notes
    assert "견준" in notes


def test_a_shop_without_a_rule_says_it_looked_at_the_top_of_the_text() -> None:
    notes = _notes([["어느 가게", NAME, "19,900원", "무료", PLAIN, ""]])

    assert "19,900원" in notes and "15,000원" in notes
    assert "본문 앞 900자" in notes, "규칙이 없으면 본 자리를 그대로 말한다 — 모델이 추측하지 않게"


def test_a_right_value_says_nothing() -> None:
    assert _notes([["11번가", NAME, "229,020원", "무료", ELEVEN, ""], ["다나와", NAME, "128,970원", "무료", DANAWA, ""]]) == ""


# --- ② 견주지 못한 줄을 말없이 넘기지 않는다 ------------------------------------------

def test_a_row_whose_address_cell_holds_no_address_is_named() -> None:
    notes = _notes([
        ["다나와", NAME, "128,970원", "무료", DANAWA, ""],
        ["11번가", NAME, "229,020원", "무료", "11번가 검색 결과 확인", ""],
        ["어느 가게", NAME, "15,000원", "무료", "", ""],
    ])

    assert "어느 페이지에서 읽었는지 적히지 않은 줄" in notes
    assert "「11번가」" in notes and "11번가 검색 결과 확인" in notes
    assert "「어느 가게」" in notes and "(빈칸)" in notes
    assert "「다나와」" not in notes, "주소가 적힌 줄은 여기 안 나온다"
    assert "대조하지 못했습니다" in notes


def test_a_table_that_never_carries_addresses_is_left_alone() -> None:
    """출처를 이름으로 적는 표(주소가 한 줄에도 없다)까지 건드리면 헛경고가 된다."""
    rows = [["다나와", NAME, "128,970원", "무료", "다나와 상품 페이지", ""], ["11번가", NAME, "229,020원", "무료", "11번가 상품 페이지", ""]]

    assert "어느 페이지에서 읽었는지" not in _notes(rows)


def test_a_table_without_an_address_column_is_left_alone() -> None:
    header = ["가게", "상품 이름", "판매 가격", "배송비"]
    rows = [["다나와", NAME, "128,970원", "무료"], ["11번가", NAME, "229,020원", "무료"]]

    assert "어느 페이지에서 읽었는지" not in _notes(rows, header=header)


def test_a_row_without_a_value_is_not_a_row_to_check() -> None:
    """값이 없는 줄(못 찾았다고 적은 줄 · 합계 설명 줄)은 대조할 것이 없다."""
    notes = _notes([
        ["다나와", NAME, "128,970원", "무료", DANAWA, ""],
        ["11번가", NAME, "—", "—", "", "이 가게에서는 상품을 못 찾음"],
    ])

    assert "어느 페이지에서 읽었는지" not in notes


def test_the_writing_time_note_tells_the_model_what_to_put_there() -> None:
    import inspect

    source = inspect.getsource(BrowserAgent._write_grounding_feedback)

    assert "주소 칸" in source and "읽은 페이지의 주소" in source
