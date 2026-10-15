"""조사 판은 **읽은 자료에 없는 숫자로 파일을 쓰지 않는다** (2026-09-30 손자리 조사 판 e7dd3831).

MCP 로 맡긴 「초기 마케팅 회고 5건 → 엑셀」이 5행을 썼다. 원문과 대조하니 맞는 행 1(Tiiny.host) · 숫자·채널이 틀린 행 1(PostHog) ·
근거 없는 행 1(Plausible 「첫 해 $1M ARR」) · 주소부터 404 인 행 1(Lemon Squeezy 「첫 달 $100k MRR」).
숫자 근거 검사는 최종 답에만 걸렸고 판을 중간에 멈추자 검사 없이 파일만 남았다 — 그래서 **쓰는 순간** 본다.
"""

from __future__ import annotations

import inspect

from alture_jarvis.agent import (
    GROUNDED_WRITE_MIN,
    GROUNDED_WRITE_PUSHBACKS,
    GROUNDED_WRITE_TOOLS,
    BrowserAgent,
    numbers_read_in,
    ungrounded_write_numbers,
)
from alture_jarvis.evidence import numbers_in_body

TIINY_PAGE = (
    "Redditors love freebies and giving feedback on new products. ... we chucked in promocodes for 100% off. "
    "We then shared our post ... to the Front Page and 1500+ visitors. 29 Mar, 2020"
)


def _row(*cells: str) -> dict:
    return {"path": r"C:\Users\me\Documents\JARVIS\초기_마케팅_회고_5건.xlsx", "rows": [list(cells)]}


def test_a_row_backed_by_the_page_is_written() -> None:
    seen = numbers_in_body({"text": TIINY_PAGE})

    missing = ungrounded_write_numbers(
        _row("Tiiny.host", "레딧 100% 할인 코드", "Product Hunt 1,500+ 방문자", "https://tiiny.host/blog/first-paying-users/"),
        seen,
    )

    assert missing == []


def test_the_invented_rows_are_caught() -> None:
    seen = numbers_in_body({"text": TIINY_PAGE})

    missing = ungrounded_write_numbers(
        _row("Lemon Squeezy", "첫 달 $100k MRR 달성", "1,000개 이상의 크리에이터", "https://lemonsqueezy.com/blog/how-we-got-our-first-1000-users"),
        seen,
    )

    assert "1000" in missing, missing


def test_numbers_inside_urls_and_paths_are_not_values() -> None:
    missing = ungrounded_write_numbers(
        {"path": r"C:\data\2026_report_4812.xlsx", "rows": [["교보", "https://product.kyobobook.co.kr/detail/S000209068452"]]},
        set(),
    )

    assert missing == []


def test_the_gate_is_wired_before_the_write_and_is_bounded() -> None:
    source = inspect.getsource(BrowserAgent.run)

    assert "numbers_not_in_what_you_read" in source
    assert "grounded_write_pushbacks < GROUNDED_WRITE_PUSHBACKS" in source
    assert 'model_role != "code"' in source
    assert "written_without_grounds" in source, "돌려보내기를 다 쓴 뒤 쓴 숫자는 답에 경고로 남긴다"
    assert GROUNDED_WRITE_PUSHBACKS == 2
    assert ">= GROUNDED_WRITE_MIN" in source and "numbers_read_in(messages)" in source


def test_one_or_two_computed_values_are_not_a_fabrication() -> None:
    """운영 306판 재생: 1개 이상이면 11% 가 걸렸고 대부분 가격 × 5% 적립금 같은 계산값 한두 개였다."""
    assert GROUNDED_WRITE_MIN == 3


def test_what_the_tools_returned_counts_as_read_even_if_the_ledger_missed_it() -> None:
    messages = [
        {"role": "user", "content": "교보에서 파이썬 책"},
        {"role": "tool", "tool_name": "browser_extract", "content": '{"text": "판매가 34,200원 · ISBN 9791160468711"}'},
    ]

    seen = numbers_read_in(messages)

    assert "34200" in seen and "9791160468711" in seen


def test_our_own_refusal_does_not_become_evidence() -> None:
    refusal = '{"ok": false, "error": "numbers_not_in_what_you_read", "numbers": ["100000", "2000", "50"]}'

    assert numbers_read_in([{"role": "tool", "content": refusal}]) == set()
    assert "local_write_document" in GROUNDED_WRITE_TOOLS
