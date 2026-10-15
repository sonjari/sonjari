"""엑셀 표(`rows`)가 목록 대신 **글자열**로 와도 받는다 (2026-10-12 밤).

공식 9B · 4B(창 32K) 가격 조사에서 세 가게를 다 읽고도 파일이 안 나온 판의 까닭이었다. 이틀 동안 문서 쓰기 73번 중
`rows_or_sheets_required` 거절이 18번이고 전부 `rows` 가 글자열이었다 — 모델은 표를 넣었는데 도구는 「표가 있어야 합니다」라고
했고, 4B 한 판은 같은 표를 네 번 보내 네 번 거절당했다. 글자열이 된 까닭은 맨 끝의 괄호 하나였다(아래 세 모양).
줄(가게 한 줄)은 온전했다.

표본의 가게 · 상품 · 값은 지어낸 것이다. 깨진 **모양**만 그날 거절된 원문에서 가져왔다.
"""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

from alture_jarvis.documents import _as_rows, _rows_from_string, write_document

HEAD = ["가게", "상품 이름", "판매 가격", "배송비", "읽은 페이지 주소", "비고"]
ROW_A = ["가게 가", "[정품] 가상 마우스 X1 (블랙)", "129,000 원", "무료", "https://shop-a.example/item?code=101&cate=7", ""]
ROW_B = ["가게 나", "가상 마우스 X1, 화이트", 131500, "무료", "https://shop-b.example/products/202", "할인 전 가격"]
GOOD = json.dumps([HEAD, ROW_A, ROW_B], ensure_ascii=False)


def _sheet(path: Path) -> list[list[str]]:
    book = openpyxl.load_workbook(path)
    return [["" if cell is None else str(cell) for cell in row] for row in book.active.iter_rows(values_only=True)]


def test_a_clean_json_string_is_the_table() -> None:
    assert _rows_from_string(GOOD) == [HEAD, ROW_A, ROW_B]
    assert _as_rows(GOOD)[1][1] == "[정품] 가상 마우스 X1 (블랙)", "따옴표 안의 대괄호는 줄의 끝이 아니다"


@pytest.mark.parametrize("broken", [
    GOOD + ",",                 # 쉼표가 하나 더
    GOOD[:-1] + "}",            # 대괄호 대신 중괄호로 닫음
    GOOD + "]",                 # 대괄호가 하나 더
    GOOD[:-1],                  # 닫는 대괄호가 빠짐
])
def test_a_wrong_bracket_at_the_very_end_still_gives_every_row(broken: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        json.loads(broken)
    assert _rows_from_string(broken) == [HEAD, ROW_A, ROW_B]
    shape = write_document(tmp_path / "a.xlsx", "xlsx", {"rows": broken})
    assert shape
    rows = _sheet(tmp_path / "a.xlsx")
    assert rows[0] == HEAD and len(rows) == 3
    assert rows[2][0] == "가게 나" and rows[2][4] == "https://shop-b.example/products/202"


@pytest.mark.parametrize("tail", [
    ",\n<open>\nTrue",                       # 다음 인자의 꼬리표가 섞여 들어옴 — 고친 날 밤 4B 판의 모양
    ', "text": "가상 상품 가격 조사 메모"}',     # 다음 인자가 통째로 붙어 옴
])
def test_whatever_trails_a_table_that_closed_properly_is_not_the_table(tail: str, tmp_path: Path) -> None:
    assert _rows_from_string(GOOD + tail) == [HEAD, ROW_A, ROW_B]
    assert write_document(tmp_path / "t.xlsx", "xlsx", {"rows": GOOD + tail})
    assert len(_sheet(tmp_path / "t.xlsx")) == 3


def test_a_lone_list_of_words_followed_by_junk_is_not_taken_as_a_table() -> None:
    """줄(목록 · 사전)로 된 목록일 때만이다 — 낱말 목록 뒤에 글이 붙은 것까지 표로 읽지 않는다."""
    assert _rows_from_string('["가게", "값"] 그리고 나머지는 아래에') == []


def test_bare_empty_cells_are_empty_cells() -> None:
    """그날의 셋째 모양 — `["가게 다", "", , , , "확인 불가: …"]`. 빈 칸을 지어 채우지 않는다."""
    broken = GOOD[:-1] + ', ["가게 다", "", , , , "확인 불가: 다른 상품 화면"]]]'
    rows = _rows_from_string(broken)
    assert len(rows) == 4
    assert rows[3] == ["가게 다", "", "", "", "", "확인 불가: 다른 상품 화면"]
    assert len(rows[3]) == len(HEAD), "칸 수가 머리줄과 맞는다 — 값이 옆 칸으로 밀리지 않는다"


def test_a_trailing_comma_inside_a_row_is_not_an_extra_cell() -> None:
    assert _rows_from_string('[["가", "나", ], ["1", "2", ]],') == [["가", "나"], ["1", "2"]]


def test_a_row_we_cannot_read_means_no_rescue_at_all(tmp_path: Path) -> None:
    """줄 안의 따옴표가 깨진 표는 건지지 않는다 — 읽힌 줄만으로 세우면 줄이 빠진 엑셀이 「성공」으로 나간다."""
    broken = '[["가게", "상품 이름"], ["가게 가", "가상 "특가" 마우스"], ["가게 나", "가상 마우스"]],'
    assert _rows_from_string(broken) == []
    with pytest.raises(ValueError, match="rows_or_sheets_required"):
        write_document(tmp_path / "b.xlsx", "xlsx", {"rows": broken})


def test_words_that_are_not_a_table_are_not_a_table(tmp_path: Path) -> None:
    for text in ("", "   ", "표는 아래와 같습니다", "가게 가: 129,000원 / 가게 나: 131,500원", '{"가게": "가게 가"'):
        assert _rows_from_string(text) == []
    with pytest.raises(ValueError, match="rows_or_sheets_required"):
        write_document(tmp_path / "c.xlsx", "xlsx", {"rows": "표는 아래와 같습니다"})


def test_a_list_still_works_as_before() -> None:
    assert _as_rows([HEAD, ROW_A]) == [HEAD, [str(cell) for cell in ROW_A]]
    assert _as_rows([{"가게": "가게 가", "값": 1}]) == [["가게", "값"], ["가게 가", "1"]]
    assert _as_rows(None) == [] and _as_rows([]) == []


def test_a_long_run_of_spaces_does_not_hang() -> None:
    assert _rows_from_string('[["가", "나"' + " " * 20_000 + "x") == []
