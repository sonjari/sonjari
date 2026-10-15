"""만든 엑셀을 사람이 **받자마자 쓸 수 있는가** — 숫자는 숫자, 주소는 하이퍼링크, 머리줄은 서식.

2026-09-29 헤르메스 대결 T1 H8·H9: 헤르메스 엑셀은 숫자·하이퍼링크·머리줄 색이 있었고, 우리 것은 값은 맞는데 전부 글자 칸이었다.
"""
from openpyxl import load_workbook

from alture_jarvis.document_reader import preview_of_file
from alture_jarvis.documents import write_document

T1_ROWS = [
    ["순위", "제목", "판매가", "적립 포인트", "ISBN", "출간", "URL"],
    ["1", "혼자 공부하는 파이썬", "16,200", "900", "9791169210034", "2022", "https://product.kyobobook.co.kr/detail/S000001810158"],
    ["2", "Do it! 점프 투 파이썬", "19,800", "1,100", "9791163034735", "2023"],  # 칸이 모자란 줄도 받는다
]


def _book(tmp_path):
    target = tmp_path / "t1.xlsx"
    write_document(target, "xlsx", {"sheets": {"파이썬 책": T1_ROWS}})
    return target, load_workbook(target)["파이썬 책"]


def test_money_becomes_a_number_with_commas(tmp_path):
    _, sheet = _book(tmp_path)
    assert sheet["C2"].value == 16200 and sheet["C2"].number_format == "#,##0"
    assert sheet["D3"].value == 1100 and sheet["D3"].number_format == "#,##0"
    assert sheet["D2"].value == 900 and sheet["A2"].value == 1


def test_identifiers_and_header_stay_text(tmp_path):
    _, sheet = _book(tmp_path)
    assert sheet["E2"].value == "9791169210034"  # 13자리 — 숫자로 바꾸면 9.79E+12 로 보인다
    assert sheet["F2"].value == 2022 and sheet["F2"].number_format == "General"  # 연도에 쉼표를 찍지 않는다
    assert [cell.value for cell in sheet[1]][:3] == ["순위", "제목", "판매가"]


def test_url_cell_is_a_link_and_header_is_dressed(tmp_path):
    _, sheet = _book(tmp_path)
    assert sheet["G2"].hyperlink is not None
    assert sheet["G2"].hyperlink.target == T1_ROWS[1][6]
    assert sheet["A1"].font.bold and sheet.freeze_panes == "A2" and sheet.auto_filter.ref


def test_readers_still_see_the_same_values(tmp_path):
    """값 대조(답 ↔ 파일)는 쉼표를 떼고 비교한다 — 숫자 칸이 돼도 대조가 그대로 돈다."""
    target, _ = _book(tmp_path)
    text = preview_of_file(target, chars=6000)
    assert "16200" in text and "혼자 공부하는 파이썬" in text and "9791169210034" in text
