"""표의 두 칸이 모든 줄에서 똑같으면, 쓴 직후에 알린다 (2026-10-14).

어머님 부탁(쿠팡 캣타워 · 부산 노트북 4B)으로 만든 엑셀에서 「평점 수」 칸과 「리뷰 수」 칸에 같은 숫자가
세 줄 모두 들어갔다(784개 · 1,275개 · 808개). 화면에는 별점 · 상품평 수 · 「만족했어요」가 따로 있었다 —
한 칸에 들어갈 값을 두 칸에 나눠 적은 것이다. 모델의 판단이 아니라 표의 모양이라, 쓰기 직후에 짚을 수 있다.

막지 않는다 — 정말로 같은 값인 표도 있다(가격과 판매가가 같은 가게). 짚어 주고 모델이 다시 보게 한다.

지키는 약속:
- `twin_column_notes(rows)` 는 머리줄 아래 값이 **두 줄 이상** 있고, 서로 다른 두 칸의 값이 **모든 줄에서** 같으면
  그 두 칸의 이름이 든 알림을 하나 돌려준다. 아니면 빈 목록.
- 두 칸이 모두 비어 있는 것은 같은 값으로 치지 않는다(아직 못 채운 칸이다).
- 값이 한 줄뿐이면 우연일 수 있으니 짚지 않는다.
- `write_document` 의 결과에 `twin_columns` 로 붙는다(엑셀 · CSV · 워드 표 모두). 없으면 그 키가 없다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.documents import twin_column_notes, write_document

CAT_TOWERS = [
    ["상품명", "가격", "평점 수", "배송비", "리뷰 수", "링크"],
    ["캣타워 스크래 기둥", "14,150원", "784개", "무료", "784개", "https://example.test/1"],
    ["New World 캣타워", "38,400원", "1,275개", "무료", "1,275개", "https://example.test/2"],
    ["하루꿈 대형 캣타워", "48,000원", "808개", "무료", "808개", "https://example.test/3"],
]


def test_two_columns_that_match_on_every_row_are_named() -> None:
    notes = twin_column_notes(CAT_TOWERS)
    assert len(notes) == 1
    assert "평점 수" in notes[0] and "리뷰 수" in notes[0]


def test_one_row_that_differs_clears_it() -> None:
    rows = [row[:] for row in CAT_TOWERS]
    rows[2][4] = "1,301개"
    assert twin_column_notes(rows) == []


def test_columns_that_are_all_blank_are_not_twins() -> None:
    rows = [["상품명", "평점", "별점"], ["가", "", ""], ["나", "", ""]]
    assert twin_column_notes(rows) == []


def test_a_single_value_row_is_not_enough() -> None:
    assert twin_column_notes(CAT_TOWERS[:2]) == []
    assert twin_column_notes(CAT_TOWERS[:1]) == []
    assert twin_column_notes([]) == []


def test_the_note_rides_on_the_write_result(tmp_path: Path) -> None:
    got = write_document(tmp_path / "캣타워.xlsx", "xlsx", {"rows": CAT_TOWERS})
    assert got.get("twin_columns") and "리뷰 수" in got["twin_columns"][0]

    clean = [row[:] for row in CAT_TOWERS]
    for row in clean[1:]:
        row[4] = row[4].replace("개", "") + "0개"
    got = write_document(tmp_path / "고친.xlsx", "xlsx", {"rows": clean})
    assert "twin_columns" not in got


def test_a_word_table_is_checked_too(tmp_path: Path) -> None:
    blocks = [{"type": "heading", "level": 1, "text": "캣타워"}, {"type": "table", "rows": CAT_TOWERS}]
    got = write_document(tmp_path / "캣타워.docx", "docx", {"blocks": blocks})
    assert got.get("twin_columns")
