"""머리줄이 값의 **꼴**을 정하는 칸에서 값이 그 꼴과 안 맞으면 **알린다** (2026-10-14).

막지 않는다 — `column_shape_notes(rows)` 가 알림 목록을 주고, `write_document` 는
결과가 있을 때만 돌려주는 dict 에 `"column_shape"` 키로 붙인다.

꼴 넷:
- 평점/별점 (그리고 '수'·'개수' 아님) → 0~5점. 89% 같은 퍼센트는 아님.
- 가격/판매가/금액 → 금액.
- 링크/주소/URL(대소문자 무시) → http:// 또는 https:// 로 시작.
- 리뷰 수/평점 수/상품평/후기 수 → 개수.
"""
from __future__ import annotations

import pathlib
import tempfile

from alture_jarvis.documents import column_shape_notes, write_document


def _tmp(name: str) -> pathlib.Path:
    return pathlib.Path(tempfile.mkdtemp()) / name


# ── 평점 (0~5점) ──────────────────────────────────────────────

def test_rating_column_accepts_good_shapes() -> None:
    rows = [
        ["상품명", "평점"],
        ["A", "4.5"],
        ["B", "4.5점"],
        ["C", "★4.5"],
        ["D", "4.5/5"],
    ]
    assert column_shape_notes(rows) == []


def test_rating_column_flags_a_percent() -> None:
    rows = [
        ["상품명", "평점"],
        ["A", "89%"],
        ["B", "61%"],
        ["C", "40%"],
    ]
    notes = column_shape_notes(rows)
    assert len(notes) == 1
    assert "평점" in notes[0]
    assert "89%" in notes[0]


def test_rating_column_ignores_count_names() -> None:
    # '평점 수'·'리뷰 수' 는 개수 칸이다 — 평점(0~5)으로 보지 않는다.
    rows = [
        ["상품명", "평점 수"],
        ["A", "12345"],
        ["B", "67890"],
    ]
    assert column_shape_notes(rows) == []


# ── 금액 ───────────────────────────────────────────────────────

def test_price_column_accepts_money_shapes() -> None:
    rows = [
        ["상품명", "가격"],
        ["A", "14,150원"],
        ["B", "14150"],
        ["C", "₩14,150"],
    ]
    assert column_shape_notes(rows) == []


def test_price_column_flags_non_money() -> None:
    rows = [
        ["상품명", "판매가"],
        ["A", "14,150원"],
        ["B", "보통"],
        ["C", "나음"],
    ]
    notes = column_shape_notes(rows)
    assert len(notes) == 1
    assert "판매가" in notes[0]


# ── 링크 ───────────────────────────────────────────────────────

def test_link_column_accepts_urls() -> None:
    rows = [
        ["상품명", "링크"],
        ["A", "https://example.com/a"],
        ["B", "http://example.com/b"],
    ]
    assert column_shape_notes(rows) == []


def test_link_column_flags_a_plain_word() -> None:
    rows = [
        ["상품명", "URL"],
        ["A", "https://example.com/a"],
        ["B", "링크가 없습니다"],
        ["C", "찾아보세요"],
    ]
    notes = column_shape_notes(rows)
    assert len(notes) == 1
    assert "URL" in notes[0]


# ── 개수 ───────────────────────────────────────────────────────

def test_count_column_accepts_count_shapes() -> None:
    rows = [
        ["상품명", "리뷰 수"],
        ["A", "784"],
        ["B", "784개"],
        ["C", "1,275개"],
    ]
    assert column_shape_notes(rows) == []


def test_count_column_flags_non_count() -> None:
    rows = [
        ["상품명", "후기 수"],
        ["A", "784"],
        ["B", "많은 편입니다"],
        ["C", "중간"],
    ]
    notes = column_shape_notes(rows)
    assert len(notes) == 1
    assert "후기 수" in notes[0]


# ── 요구한 시험: 평점 칸에 '89%'·'61%' 가 든 세 줄 표 ─────────────

def test_only_the_rating_column_is_flagged_in_the_percent_table() -> None:
    rows = [
        ["상품명", "가격", "평점", "리뷰 수", "링크"],
        ["A", "14,150원", "89%", "784", "https://example.com/a"],
        ["B", "14150", "61%", "1,275개", "https://example.com/b"],
        ["C", "₩20,000", "55%", "999", "http://example.com/c"],
    ]
    notes = column_shape_notes(rows)
    # 평점 칸만 짚힌다 — 가격·리뷰 수·링크 는 그 꼴에 맞게 적혀 있어 조용하다.
    assert len(notes) == 1
    assert "평점" in notes[0]
    assert "가격" not in notes[0]
    assert "리뷰 수" not in notes[0]
    assert "링크" not in notes[0]


# ── write_document 가 "column_shape" 키로 붙인다 (결과가 있을 때만) ────

def test_write_document_attaches_column_shape_key() -> None:
    rows = [
        ["상품명", "평점"],
        ["A", "89%"],
        ["B", "61%"],
        ["C", "55%"],
    ]
    path = _tmp("shape.xlsx")
    result = write_document(path, "xlsx", {"rows": rows})
    assert "column_shape" in result
    assert isinstance(result["column_shape"], list)
    assert any("평점" in n for n in result["column_shape"])


def test_write_document_omits_column_shape_key_when_clean() -> None:
    rows = [
        ["상품명", "평점"],
        ["A", "4.5"],
        ["B", "4.0"],
        ["C", "★3.5"],
    ]
    path = _tmp("clean.xlsx")
    result = write_document(path, "xlsx", {"rows": rows})
    assert "column_shape" not in result


def test_write_document_sees_rows_from_blocks_too() -> None:
    blocks = [
        {
            "type": "table",
            "rows": [
                ["상품명", "평점"],
                ["A", "89%"],
                ["B", "61%"],
                ["C", "55%"],
            ],
        }
    ]
    path = _tmp("blocks.xlsx")
    result = write_document(path, "xlsx", {"blocks": blocks})
    assert "column_shape" in result
    assert any("평점" in n for n in result["column_shape"])


# ── 가져온 뒤 Claude 가 덧붙인 것 (2026-10-14) — 설명이 붙은 멀쩡한 값을 틀렸다고 짚지 않는다 ─────────────


def test_values_with_a_note_after_them_are_still_their_shape() -> None:
    rows = [
        ["상품명", "가격", "평점", "리뷰 수"],
        ["가", "118,810원 (쿠폰 적용 시)", "4.5 (808개)", "784개 리뷰"],
        ["나", "약 48,000원", "★4.8", "(1,275)"],
        ["다", "$14.99", "4점", "12"],
    ]
    assert column_shape_notes(rows) == []


def test_a_street_address_is_not_a_link() -> None:
    rows = [["매장", "주소"], ["강남점", "서울시 강남구 테헤란로 1"], ["부산점", "부산시 해운대구 1"]]
    assert column_shape_notes(rows) == []


def test_a_web_address_column_is_still_checked() -> None:
    rows = [["상품", "읽은 주소"], ["가", "쿠팡 상세"], ["나", "네이버 쇼핑"]]
    notes = column_shape_notes(rows)
    assert len(notes) == 1 and "읽은 주소" in notes[0]


def test_a_percent_is_still_not_a_rating_even_with_a_note() -> None:
    rows = [["상품", "평점"], ["가", "89% (만족)"], ["나", "61%"]]
    assert len(column_shape_notes(rows)) == 1
