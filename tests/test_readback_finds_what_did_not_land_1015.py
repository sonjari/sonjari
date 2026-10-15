"""저장한 문서에서 글을 다시 꺼내, 쓰려던 내용이 빠지거나 바뀐 곳을 찾는다 (2026-10-15).

레딧 r/AI_Agents 댓글이 짚은 빈틈: 지금 손자리는 파일이 있는지 · 비지 않았는지 · 빠진 블록이 있는지 · 표의 숫자가 읽은 페이지에
있는지까지만 본다. 파일을 다시 열어 **쓰려던 내용과 견주지는 않아서**, 중간에 끊긴 파일이나 다듬어 바꾼 문장이 든 파일은 통과한다.
제안 그대로: 먼저 꾸밈(띄어쓰기 · 따옴표 모양 · 제목 기호)을 맞추고, **문장이 빠졌거나 바뀐 것만** 실패로 본다.

지키는 약속 — `alture_jarvis.readback.readback_gaps(path, fmt, payload)`:
- `payload` 는 `documents.write_document` 에 준 것과 같은 모양이다: `rows`(표의 줄 목록) · `blocks`(제목 · 문단 · 표) · `text`.
- 쓰려던 단위: `rows` 와 표 블록의 **비지 않은 칸 하나하나**, 제목 · 문단 블록의 글, `text` 의 줄 하나하나. 두 글자보다 짧은 것은 세지 않는다.
- 저장된 파일에서 글을 꺼낸다: docx(문단 + 표 칸) · xlsx(모든 시트의 칸 값) · md · txt.
- 견주기 전에 양쪽을 같은 모양으로 맞춘다: 유니코드 NFKC · 둥근 따옴표를 곧은 따옴표로 · 연속 공백 하나로 · 마크다운 제목 기호(#) 와 굵게(**) 빼기.
- 쓰려던 단위가 꺼낸 글 안에 **그대로 들어 있지 않으면** 빠진 것이다. 빠진 단위를 쓰려던 순서대로 돌려준다(없으면 빈 목록).
- 이 함수가 못 읽는 형식(hwpx · pptx 등)은 `None` 을 돌려준다 — 「확인 못 함」이지 「통과」가 아니다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.documents import write_document
from alture_jarvis.readback import readback_gaps

BLOCKS = [
    {"type": "heading", "level": 1, "text": "무선 마우스 가격 비교"},
    {"type": "paragraph", "text": "세 가게의 판매가를 오늘 기준으로 비교했습니다."},
    {"type": "table", "rows": [["가게", "상품명", "가격"], ["다나와", "로지텍 MX Master 3S", "129,000원"],
                               ["11번가", "로지텍 MX Master 3S", "131,500원"]]},
    {"type": "paragraph", "text": "가장 싼 곳은 다나와였습니다."},
]
ROWS = [["가게", "상품명", "가격"], ["다나와", "로지텍 MX Master 3S", "129,000원"], ["G마켓", "로지텍 MX Master 3S", "133,900원"]]


def test_a_document_that_landed_in_full_has_no_gaps(tmp_path: Path) -> None:
    path = tmp_path / "비교.docx"
    write_document(path, "docx", {"blocks": BLOCKS})
    assert readback_gaps(path, "docx", {"blocks": BLOCKS}) == []


def test_a_document_that_stops_halfway_is_caught(tmp_path: Path) -> None:
    import docx

    path = tmp_path / "비교.docx"
    write_document(path, "docx", {"blocks": BLOCKS})
    document = docx.Document(str(path))
    last = [p for p in document.paragraphs if "가장 싼 곳" in p.text][0]
    last._element.getparent().remove(last._element)
    document.save(str(path))
    assert readback_gaps(path, "docx", {"blocks": BLOCKS}) == ["가장 싼 곳은 다나와였습니다."]


def test_a_tidied_up_paraphrase_is_caught(tmp_path: Path) -> None:
    import docx

    path = tmp_path / "비교.docx"
    write_document(path, "docx", {"blocks": BLOCKS})
    document = docx.Document(str(path))
    for paragraph in document.paragraphs:
        if paragraph.text.startswith("세 가게의"):
            paragraph.text = "여러 가게의 가격을 살펴봤습니다."
    document.save(str(path))
    assert readback_gaps(path, "docx", {"blocks": BLOCKS}) == ["세 가게의 판매가를 오늘 기준으로 비교했습니다."]


def test_formatting_differences_are_not_failures(tmp_path: Path) -> None:
    path = tmp_path / "메모.md"
    path.write_text("# 오늘의 메모\n\n**회의는**   “3시”에   시작합니다.\n", encoding="utf-8")
    payload = {"blocks": [{"type": "heading", "level": 1, "text": "오늘의 메모"},
                          {"type": "paragraph", "text": '회의는 "3시"에 시작합니다.'}]}
    assert readback_gaps(path, "md", payload) == []


def test_a_spreadsheet_with_a_changed_cell_is_caught(tmp_path: Path) -> None:
    import openpyxl

    path = tmp_path / "가격.xlsx"
    write_document(path, "xlsx", {"rows": ROWS})
    assert readback_gaps(path, "xlsx", {"rows": ROWS}) == []

    book = openpyxl.load_workbook(str(path))
    sheet = book.worksheets[0]
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value == "133,900원":
                cell.value = "확인 필요"
    book.save(str(path))
    assert readback_gaps(path, "xlsx", {"rows": ROWS}) == ["133,900원"]


def test_text_lines_and_short_units(tmp_path: Path) -> None:
    path = tmp_path / "노트.txt"
    path.write_text("첫 줄입니다.\n둘째 줄입니다.\n", encoding="utf-8")
    payload = {"text": "첫 줄입니다.\n둘째 줄입니다.\n셋째 줄입니다.\n-\n"}
    assert readback_gaps(path, "txt", payload) == ["셋째 줄입니다."]


def test_a_format_it_cannot_read_is_not_a_pass(tmp_path: Path) -> None:
    path = tmp_path / "보고서.hwpx"
    path.write_bytes(b"PK")
    assert readback_gaps(path, "hwpx", {"blocks": BLOCKS}) is None
