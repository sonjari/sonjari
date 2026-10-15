"""자비스가 **자기가 쓴 내용으로** 문서를 만든다.

## 무엇이 반쪽이었나 (2026-09-01)

문서를 만드는 통로가 셋 있었는데 전부 반쪽이었다:

    local_write_file              텍스트만
    artifact_from_observations    XLSX·DOCX 되지만 **도구가 관측한 step_id 로만**
    sandbox_run                   라이브러리는 다 있지만 **로컬 파일을 못 본다**

라이브러리는 이미 런타임에 들어 있었다(openpyxl · python-docx · python-pptx).
그런데 「받은 엑셀을 읽고 정리해서 다시 엑셀로」가 통째로 안 됐다 — 상자는 그 파일을
못 보고, artifact 는 관측한 것만 쓴다. **읽은 것으로 만들 길이 없었다.**

    받기   browser_download    ✅
    읽기   local_read_document ✅
    만들기 ───────────────── ❌  ← 이 칸

이 모듈이 그 칸이다.

## 설계 규율

- **모양을 강제하지 않는다.** 표는 `rows`, 글은 `blocks` 로 받되, 둘 다 없으면
  `text` 를 그대로 쓴다. 모델이 형식을 못 맞춰 실패하는 것이 제일 흔한 고장이다.
- **덮어쓰기는 되돌릴 수 있게.** 기존 파일을 고칠 때는 백업을 남긴다 —
  `local_write_file` 과 같은 약속이다.
- **셀 편집은 읽고 → 고치고 → 저장**이다. 통째로 다시 쓰지 않는다. 서식·수식·다른
  시트를 날리지 않기 위해서다.
"""

from __future__ import annotations

import ast
import csv
import json
import re
from pathlib import Path
from typing import Any

from .document_reader import preview_of_file

#: 한 셀에 넣을 수 있는 최대 글자. 엑셀 자체 한계가 32,767 이다.
CELL_MAX_CHARS = 32_000

#: 만들 수 있는 형식. 여기 없는 것은 **못 만든다고 말한다** — 조용히 txt 로 떨어뜨리면
#: 사람이 xlsx 를 열려다 실패한다.
WRITABLE = ("xlsx", "docx", "pptx", "hwpx", "csv", "md", "txt")


def _as_rows(value: Any) -> list[list[str]]:
    """무엇을 주든 표로 만든다.

    모델은 표를 세 가지 모양으로 준다 — 리스트의 리스트, 딕셔너리의 리스트,
    그리고 그냥 문자열. 셋 다 받는다. 형식을 못 맞췄다고 실패시키면 그게 제일
    흔한 고장이 된다.
    """
    if isinstance(value, str):
        # 목록 대신 **목록을 적은 글자열**로 온 표 (2026-10-12 · `_rows_from_string` 의 설명).
        value = _rows_from_string(value)
    if not isinstance(value, list) or not value:
        return []
    first = value[0]
    if isinstance(first, dict):
        headers = list(first.keys())
        rows = [headers]
        for item in value:
            row = item if isinstance(item, dict) else {}
            rows.append([str(row.get(key, ""))[:CELL_MAX_CHARS] for key in headers])
        return rows
    if isinstance(first, (list, tuple)):
        return [[str(cell)[:CELL_MAX_CHARS] for cell in row] for row in value]
    return [[str(item)[:CELL_MAX_CHARS]] for item in value]


def _sheet_rows(value: Any) -> list[list[str]]:
    """시트 하나. **칸 값만 늘어놓은 목록은 한 줄**이다(머리줄).

    ★ 2026-09-28 헤르메스 대결 T1 O2: 모델이 `{"파이썬 책": ["순위", "제목", …, "URL"]}` 로 머리줄만 보내고 칸 고치기로 값을 채웠는데,
    `_as_rows` 가 낱말마다 한 줄을 만들어 머리줄이 **세로로** 쪼개졌다(「순위」 아래로 「출판사·ISBN·URL」). 과거 기록에서 이 모양은
    2번 왔고 둘 다 머리줄이었다(`f3932fe2`·`cd1ab643`). 글에서 표를 뽑는 다른 자리는 `_as_rows` 그대로 둔다.
    """
    if isinstance(value, list) and value and all(not isinstance(item, (list, tuple, dict)) for item in value):
        return [[str(item)[:CELL_MAX_CHARS] for item in value]]
    # ★ 2026-09-28 T1 O10: `{"파이썬 책 정보": {"header": [...], "rows": [[...], ...]}}` 를 두 번 보냈는데 빈 시트가 됐고,
    #   도구는 「머리줄만 있다 — rows 로 채우세요」라고 답했다(이미 rows 였다). 모델은 값을 버리고 「확인 필요」로 끝냈다.
    if isinstance(value, dict):
        head = next((value[key] for key in ("header", "headers", "columns", "head") if isinstance(value.get(key), list)), None)
        body = next((value[key] for key in ("rows", "data", "values", "body") if isinstance(value.get(key), list)), None)
        if head is not None or body is not None:
            grid = [[str(cell)[:CELL_MAX_CHARS] for cell in head]] if head else []
            return grid + (_sheet_rows(body) if body and all(not isinstance(item, (list, tuple, dict)) for item in body)
                           else _as_rows(body or []))
    return _as_rows(value)


#: 값 칸의 숫자 — 천 단위 쉼표가 있거나, 앞에 0 이 없는 9자리 이하. ISBN(13자리)·전화번호(0 시작)는 글자로 둔다.
_XLSX_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+")
_XLSX_PLAIN = re.compile(r"0|[1-9]\d{0,8}")
_XLSX_URL = re.compile(r"https?://\S+")


def _xlsx_value(cell: str) -> Any:
    """값 칸을 **엑셀이 셀 수 있는 숫자**로. 글자 「16,200」은 합계·정렬이 안 된다.

    ★ 2026-09-29 헤르메스 대결 T1 H8·H9: 헤르메스가 만든 엑셀은 숫자가 숫자였고 주소가 하이퍼링크, 머리줄에 서식이 있었다.
    우리 파일은 값은 맞는데 전부 글자 칸이었다 — 사람이 받자마자 쓰는 쪽은 저쪽이었다(배울 점).
    """
    text = cell.strip()
    if _XLSX_GROUPED.fullmatch(text):
        return int(text.replace(",", ""))
    if _XLSX_PLAIN.fullmatch(text):
        return int(text)
    return cell


def _cell_width(value: Any) -> int:
    text = str(value if value is not None else "")
    # 한글·한자는 영문 두 칸 너비다.
    return sum(2 if ord(char) > 0x2E80 else 1 for char in text)


def _dress_sheet(sheet: Any, page: list[list[str]]) -> None:
    """머리줄 굵게·바탕색 · 머리줄 얼림 · 거르기 · 칸 너비는 내용만큼 · 주소는 하이퍼링크 · 쉼표 숫자는 쉼표 서식."""
    from openpyxl.styles import Font, PatternFill

    # 머리글을 얼려 두면 긴 표를 사람이 실제로 읽을 수 있다.
    sheet.freeze_panes = "A2"
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
    if len(page) > 1 and sheet.max_column:
        sheet.auto_filter.ref = sheet.dimensions
    widths: dict[str, int] = {}
    for index, row in enumerate(sheet.iter_rows()):
        for cell in row:
            widths[cell.column_letter] = max(widths.get(cell.column_letter, 0), _cell_width(cell.value))
            if index == 0:
                continue
            source = page[index][cell.column - 1] if cell.column - 1 < len(page[index]) else ""
            if isinstance(cell.value, int) and _XLSX_GROUPED.fullmatch(str(source).strip()):
                cell.number_format = "#,##0"
            elif isinstance(cell.value, str) and _XLSX_URL.fullmatch(cell.value.strip()):
                cell.hyperlink = cell.value.strip()
                cell.style = "Hyperlink"
    for letter, width in widths.items():
        sheet.column_dimensions[letter].width = min(max(width + 2, 8), 60)


#: 엑셀이 시트 이름에 못 받는 글자.
_SHEET_TITLE_BAD = re.compile(r"[\\/*?:\[\]]")


def _sheet_titles(names: list[str]) -> list[str]:
    """시트 이름을 엑셀이 받는 꼴로 — 못 받는 글자는 빈칸으로, 31자까지, 겹치면 번호를 붙인다.

    ★ 2026-10-04 허깅페이스 판 3ad09518: 시트 이름 「벤치마크/출처」의 `/` 하나로 쓰기가 통째로 튕겼다
      (`Invalid character / found in sheet title`). 모델은 이름을 바꿔 다시 불렀다 — 다섯 줄을 한 번 더 썼다.
      글자 하나 바꾸면 되는 일을 돌려보낼 까닭이 없다(사고 R). 자르다 같은 이름이 되면 뒤 시트가 앞 시트를 덮으므로 번호를 붙인다.
    """
    out: list[str] = []
    for index, name in enumerate(names, start=1):
        title = " ".join(_SHEET_TITLE_BAD.sub(" ", str(name or "")).split()).strip("'")[:31] or f"Sheet{index}"
        base, count = title, 2
        while title.casefold() in {seen.casefold() for seen in out}:
            tail = f" ({count})"
            title = base[: 31 - len(tail)] + tail
            count += 1
        out.append(title)
    return out


def _write_xlsx(target: Path, rows: list[list[str]], sheets: Any) -> dict[str, Any]:
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.active)
    pages: dict[str, list[list[str]]] = {}
    if isinstance(sheets, dict) and sheets:
        pages = {
            title: _sheet_rows(value)
            for title, value in zip(_sheet_titles([str(name) for name in sheets]), sheets.values())
        }
    else:
        pages = {"Sheet1": rows}
    for name, page in pages.items():
        sheet = book.create_sheet(title=name or "Sheet1")
        for index, row in enumerate(page):
            sheet.append(row if index == 0 else [_xlsx_value(cell) for cell in row])
        if page:
            _dress_sheet(sheet, page)
    book.save(target)
    shape: dict[str, Any] = {"sheets": list(pages), "rows": sum(len(p) for p in pages.values())}
    # ★ 머리줄만 쓴 시트는 **말한다**(2026-09-28 T1 O4: 머리줄만 쓰고 값 줄 없이 끝냈는데 답은 「엑셀도 동일하게 생성」). 막지는 않는다 —
    #   칸 고치기로 채우는 판(O2)도 있다. 모델이 이 결과를 보고 값을 채우게 한다.
    # 줄이 **0개**면 머리줄조차 못 읽은 것이다 — 「rows 로 채우세요」는 틀린 안내가 된다(T1 O10: 이미 rows 였다). 받는 모양을 댄다.
    unread = [name for name, page in pages.items() if not page]
    if unread:
        shape["unreadable_sheets"] = (
            f"시트 {', '.join(unread)} 의 표를 알아보지 못해 **빈 시트**가 됐습니다. "
            '이 모양으로 다시 보내세요: {"시트 이름": [["머리1", "머리2"], ["값1", "값2"]]} (첫 줄이 머리줄, 다음 줄부터 값).'
        )
    header_only = [name for name, page in pages.items() if len(page) == 1]
    if header_only:
        shape["header_only_sheets"] = (
            f"시트 {', '.join(header_only)} 에는 머리줄만 있고 값 줄이 0개입니다 — 값 줄을 같은 시트의 rows 로 채우세요."
        )
    return shape


def _wants_footnotes(blocks: Any) -> bool:
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").lower() in {"footnote", "각주"}:
            return True
        if block.get("footnote") or block.get("각주"):
            return True
    return False


#: 문서 기본 서식. **모델에게 부탁하지 않고 코드가 정한다.**
#
# ★ 2026-09-11 실측. 라이브에서 나온 워드 문서를 열어 보니 이랬다:
#
#     [Normal] 여수 지역 회계 채용 공고 조사 결과 (2026-09-10 기준)   ← 제목인데 Normal
#     문서 기본 글꼴: None / None                                     ← 한글 글꼴 미지정
#
#   python-docx 의 기본 서식은 Calibri 11pt 이고 **동아시아 글꼴을 안 정한다.**
#   그러면 여는 PC 마다 굴림·바탕·맑은고딕이 제각각으로 잡힌다. 내용이 맞아도
#   문서로는 못 쓴다.
#
#   이건 모델이 「맑은 고딕으로 해주세요」라고 부탁할 일이 아니다. **결정론으로
#   박을 수 있으면 코드로** 간다 — 이 저장소가 안내문으로 고치려다 세 번 실패한
#   자리와 같은 규율이다(사고 R).
_DOC_FONT_KO = "맑은 고딕"
_DOC_FONT_EN = "Calibri"
_DOC_BODY_PT = 10.5
#: 제목 크기. 1단계부터 3단계까지. 워드 기본은 파란 글씨라 검정에 가깝게 바꾼다.
_DOC_HEADING_PT = {0: 20.0, 1: 15.0, 2: 12.5, 3: 11.0, 4: 10.5}
_DOC_HEADING_RGB = (0x1F, 0x1F, 0x1F)
_DOC_MARGIN_CM = 2.0
_DOC_LINE_SPACING = 1.4


def _set_run_fonts(item: Any) -> None:
    """서양 글꼴과 **동아시아 글꼴을 따로** 박는다.

    python-docx 의 `font.name` 은 `w:ascii` 만 건드린다. 한글은 `w:eastAsia` 를
    보므로 그것만 정하면 한글이 여전히 기본 글꼴로 나온다 — 눈으로는 「글꼴을
    정했는데 왜 안 바뀌지」가 된다. 그래서 XML 을 직접 적는다.
    """
    from docx.oxml.ns import qn

    element = item.element.rPr if hasattr(item, "element") else None
    if element is None:
        return
    fonts = element.rFonts if element.rFonts is not None else element.get_or_add_rFonts()
    fonts.set(qn("w:ascii"), _DOC_FONT_EN)
    fonts.set(qn("w:hAnsi"), _DOC_FONT_EN)
    fonts.set(qn("w:eastAsia"), _DOC_FONT_KO)
    fonts.set(qn("w:cs"), _DOC_FONT_EN)


def _apply_document_theme(document: Any) -> None:
    """새 문서에 **읽을 만한 기본 서식**을 입힌다. 내용과 무관하게 늘 한다."""
    from docx.shared import Cm, Pt, RGBColor

    for section in document.sections:
        section.left_margin = section.right_margin = Cm(_DOC_MARGIN_CM)
        section.top_margin = section.bottom_margin = Cm(_DOC_MARGIN_CM)

    normal = document.styles["Normal"]
    normal.font.name = _DOC_FONT_EN
    normal.font.size = Pt(_DOC_BODY_PT)
    _set_run_fonts(normal)
    paragraph = normal.paragraph_format
    paragraph.line_spacing = _DOC_LINE_SPACING
    paragraph.space_after = Pt(6)

    for level, size in _DOC_HEADING_PT.items():
        name = "Title" if level == 0 else f"Heading {level}"
        try:
            style = document.styles[name]
        except KeyError:
            continue
        style.font.name = _DOC_FONT_EN
        style.font.size = Pt(size)
        style.font.bold = True
        # 워드 기본 제목은 파란 글씨다. 조사 보고서에는 안 어울린다.
        style.font.color.rgb = RGBColor(*_DOC_HEADING_RGB)
        _set_run_fonts(style)
        style.paragraph_format.space_before = Pt(12 if level <= 1 else 10)
        style.paragraph_format.space_after = Pt(4)


def _style_table(table: Any) -> None:
    """표 머리줄을 **굵게 하고 쪽이 넘어가도 따라가게** 한다.

    긴 표는 다음 쪽에서 머리줄이 사라져 어느 칸이 무엇인지 알 수 없게 된다.
    `tblHeader` 는 python-docx 가 안 열어 주므로 XML 로 적는다.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    if not table.rows:
        return
    head = table.rows[0]
    properties = head._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    properties.append(repeat)
    for cell in head.cells:
        for par in cell.paragraphs:
            for run in par.runs:
                run.bold = True
    _fit_table_columns(table)


#: 글자 하나의 어림 폭(인치 · 본문 크기) — 한글 · 한자는 두 칸, 그 밖은 한 칸으로 센다. 칸 안쪽 여백은 따로 더한다.
_INCH_PER_UNIT = 0.085
_CELL_PADDING_INCH = 0.16
_EMU_PER_INCH = 914400


def _display_units(text: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _fit_table_columns(table: Any) -> None:
    """칸 너비를 **내용에 맞춰 나눠 정한다** — 워드의 자동 맞춤에 맡기지 않는다.

    ★ 2026-10-13 촬영 판: 다섯 칸짜리 가격 표에서 끊을 수 없는 주소 한 칸이 폭을 다 가져가, 「상품 이름」은 두세 글자씩,
      「101,890원」은 「101,8 / 90 원」으로 꺾였다. 값은 맞는데 읽을 수 없는 표였다.

    - 칸마다 **가장 긴 낱말**(띄어 쓴 한 덩어리 — 값 하나)이 한 줄에 들어갈 폭은 지킨다. 주소처럼 끊을 수 없는 긴 글은
      낱말로 치지 않는다(정해 준 폭 안에서 워드가 줄을 바꾼다).
    - 남는 폭은 칸의 내용 길이에 비례해 나눈다. 한 칸이 전체의 3분의 1 남짓을 넘지 않는다.
    - 고정 배치(`tblLayout fixed`)로 적는다 — 안 그러면 워드가 다시 제 마음대로 늘린다.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Emu

    try:
        section = table.part.document.sections[0]
        available = int(section.page_width - section.left_margin - section.right_margin)
    except Exception:  # noqa: BLE001 — 쪽 크기를 못 읽으면 흔한 값(6.5인치)으로
        available = int(6.5 * _EMU_PER_INCH)
    columns = len(table.rows[0].cells)
    if columns < 2 or available <= 0:
        return
    longest = [0] * columns
    token = [0] * columns
    for row in table.rows:
        for index, cell in enumerate(row.cells[:columns]):
            text = cell.text or ""
            longest[index] = max(longest[index], *(_display_units(line) for line in text.splitlines() or [""]))
            for word in text.split():
                if len(word) > 24 or "://" in word:
                    continue                      # 끊을 수 없는 긴 글(주소 · 긴 식별자)은 폭 안에서 줄을 바꾸게 둔다
                token[index] = max(token[index], _display_units(word))
    inch = _EMU_PER_INCH
    natural = [min(3.0, units * _INCH_PER_UNIT + _CELL_PADDING_INCH) * inch for units in longest]
    minimum = [max(0.75, min(1.7, units * _INCH_PER_UNIT + _CELL_PADDING_INCH)) * inch for units in token]
    if sum(natural) <= available:
        widths = [max(low, want) for low, want in zip(minimum, natural)]
        if sum(widths) > available:
            widths = [width * available / sum(widths) for width in widths]
    else:
        floor = sum(minimum)
        if floor >= available:
            widths = [low * available / floor for low in minimum]
        else:
            room = [max(0.0, want - low) for low, want in zip(minimum, natural)]
            spare = available - floor
            widths = [low + (spare * more / sum(room) if sum(room) else spare / columns) for low, more in zip(minimum, room)]
            # 한 칸이 너무 넓어지지 않게 — 넘친 만큼은 다른 칸에 고르게 돌려준다.
            ceiling = available * 0.36
            over = sum(max(0.0, width - ceiling) for width in widths)
            if over:
                narrow = [index for index, width in enumerate(widths) if width < ceiling]
                widths = [min(width, ceiling) for width in widths]
                for index in narrow:
                    widths[index] += over / len(narrow)
    properties = table._tbl.tblPr
    for old in properties.findall(qn("w:tblLayout")):
        properties.remove(old)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    properties.append(layout)
    table.autofit = False
    for row in table.rows:
        for index, cell in enumerate(row.cells[:columns]):
            cell.width = Emu(int(widths[index]))


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_BULLET = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$")


def _md_is_rule(line: str) -> bool:
    """구분선인가. 칸마다 대시가 있고 글자·숫자가 없어야 한다."""
    text = line.strip()
    if not text or not set(text) <= set("|:- " + chr(9)):
        return False
    cells = [c.strip() for c in text.strip("|").split("|")]
    return len(cells) >= 2 and all("-" in c for c in cells)


def blocks_from_markdown(text: str) -> list[dict[str, Any]]:
    """모델이 **답에 써 놓은 것**을 문서 블록으로 옮긴다.

    ## 왜 필요한가 (2026-09-11)

    사슬 벤치에서 판이 이렇게 끝났다 — 공고 5곳을 열어 읽고, 답에 표를 완성하고,
    **파일만 안 만들었다.** 계획 층이 「산출물이 없다」고 두 번 되받았는데도 같은
    답을 되풀이했다. 걸음도 시간도 남아 있었다.

    이 저장소가 아는 병이다 — **안내문은 안 먹는다**(사고 R, 준수율 6~12%).
    그때 쓴 답이 결정론으로 박기였고(`_forced_commit_call`), 여기도 같다.

    **지어내기가 아닌 이유:** 내용을 만들지 않는다. 모델이 이미 답에 쓴 글을
    형식만 바꿔 옮긴다. 근거 검사(숫자·이름)는 그 답에 이미 걸려 있다.
    """
    blocks: list[dict[str, Any]] = []
    lines = (text or "").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        # 표: 다음 줄이 구분선이면 이 줄이 머리다.
        if ("|" in stripped and index + 1 < len(lines)
                and _md_is_rule(lines[index + 1])):
            grid: list[list[str]] = []
            for row in lines[index:]:
                if "|" not in row:
                    break
                if _md_is_rule(row):
                    continue
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                if any(cells):
                    grid.append(cells)
            if len(grid) >= 2:
                blocks.append({"type": "table", "rows": grid})
                index += 1
                while index < len(lines) and "|" in lines[index]:
                    index += 1
                continue
        heading = _MD_HEADING.match(stripped)
        if heading:
            blocks.append({"type": "heading",
                           "level": min(len(heading.group(1)), 4),
                           "text": heading.group(2).strip()})
            index += 1
            continue
        bullet = _MD_BULLET.match(stripped)
        if bullet:
            blocks.append({"type": "bullet", "text": bullet.group(1).strip()})
            index += 1
            continue
        blocks.append({"type": "paragraph", "text": stripped})
        index += 1
    return blocks

def _looks_like_markdown(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return any(_MD_HEADING.match(line) or _md_is_rule(line) for line in lines)


def _markdown_to_blocks(blocks: Any, text: str, *, strip_bold: bool = False) -> Any:
    """워드·한글·PPT 로 갈 **마크다운 글**을 진짜 제목·표·목록 블록으로 편다 (2026-09-24 노트북 실측).

    「회의록 양식을 한글(hwpx)로」에 모델이 마크다운을 글로 보냈고, 한글 파일 안에 `# 제목`·`| 항목 | 내용 |`·
    `|------|`·`**날짜**` 가 **글자 그대로** 들어갔다 — 한글로 열면 표가 아니라 기호 줄이다. 모델이 이미 쓴 글의
    **꼴만** 바꾼다(`blocks_from_markdown` 과 같은 이유 — 내용을 짓지 않는다). 문단 블록 하나에 마크다운을 통째로
    넣은 경우도 편다. 한글(hwpx)은 굵은 글씨 서식을 못 입혀서 별표를 지운다 — 워드는 별표를 진짜 굵은 글씨로 바꾸므로 남긴다.
    """
    if not blocks and _looks_like_markdown(text):
        blocks = blocks_from_markdown(text)
    if not isinstance(blocks, list):
        return blocks
    out: list[Any] = []
    for block in blocks:
        body = block if isinstance(block, str) else (block.get("text") if isinstance(block, dict) else None)
        kind = "paragraph" if isinstance(block, str) else str((block or {}).get("type") or "paragraph").lower()
        if kind == "paragraph" and isinstance(body, str) and chr(10) in body and _looks_like_markdown(body):
            out.extend(blocks_from_markdown(body))
            continue
        out.append(block)
    for block in out if strip_bold else []:
        if isinstance(block, dict) and isinstance(block.get("text"), str) and "**" in block["text"]:
            block["text"] = block["text"].replace("**", "")
    return out


def _clean_block_text(body: str) -> str:
    """모델이 보낸 글에서 **우리가 다시 붙일 것**을 벗기고, 글자로 온 줄바꿈을 푼다.

    ★ 2026-09-11 라이브에서 이렇게 나왔다:

        # # YES24 파이썬 도서 조사 결과
        **부족한 정보 및 사유**\\n* **도서 2권 미확보:** …

    앞엣것은 모델이 `#` 를 붙여 보냈는데 우리가 또 붙인 것이고, 뒤엣것은 줄바꿈을
    **글자 두 개**(역슬래시+n)로 보낸 것이다. 둘 다 모델을 탓할 일이 아니라
    **받는 쪽에서 치우면 되는 것**이다 — 그리고 이렇게 코드로 옮긴 규칙만큼
    작은 모델도 같은 결과를 낸다.
    """
    text = str(body or "")
    # 글자로 온 줄바꿈·탭을 진짜로 바꾼다. 진짜 줄바꿈이 이미 있으면 손대지 않는다.
    if chr(10) not in text:
        text = text.replace('\\n', chr(10)).replace('\\t', chr(9))
    return _scrub_model_markup(text).strip()


#: 모델의 **속생각 표시**가 본문으로 새어 나온 조각.
#
# ★ 2026-09-13 양식 검사기가 처음 돌자마자 잡았다. 사람인 문서의 첫 두 줄이:
#
#       <thought
#       >사람인에서 '여수 회계'로 검색된 공고 중 …
#
#   젬마가 생각 구간을 닫는 태그를 반쯤 흘렸고, 우리가 그걸 문단으로 옮겼다.
#   사람이 받는 워드 첫 줄이 「<thought」 였다. 파일이 나왔으니 성공으로 셀 뻔했다.
_MODEL_MARKUP = re.compile(
    r"</?\s*(?:thought|thinking|think|reasoning)\b[^>\n]*>?|^\s*>\s*(?=\S)",
    re.I | re.M,
)


def _scrub_model_markup(text: str) -> str:
    """속생각 태그 조각을 걷는다. 태그가 없으면 글을 **한 글자도** 안 바꾼다."""
    if not re.search(r"</?\s*(?:thought|thinking|think|reasoning)\b", text, re.I):
        return text
    return _MODEL_MARKUP.sub("", text)


#: 워드·한글·PPT 에서는 **기호가 아니라 서식**이어야 하는 것.
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RULE_ONLY = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


#: 블록 글 전체가 **속생각 태그 조각뿐**인가(닫는 꺾쇠가 없어도).
_THOUGHT_ONLY = re.compile(r"\s*</?\s*(?:thought|thinking|think|reasoning)\b[^>\n]*>?\s*", re.I)


def _blocks_from_payload(raw: Any) -> Any:
    """`blocks` 가 **JSON 글자열**로 와도 읽는다 (2026-09-24 노트북 4B).

    작은 모델이 목록 대신 글자열을 보냈고, 그 글자열마저 표 블록의 닫는 `}` 가 빠져 있었다 — 도구는 통째로 건너뛰고
    빈 문서를 만들었다. 통째로 안 읽히면 **객체 하나씩** 건져 낸다(제목·문단은 살고 깨진 표만 빠진다).
    """
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else [parsed]
    except (ValueError, TypeError):
        pass
    rescued: list[Any] = []
    for chunk in _block_chunks(text):
        item = _repaired_piece(chunk) if chunk.endswith("}") else None
        if not isinstance(item, dict):
            item = _table_from_chunk(chunk)
        if isinstance(item, dict):
            rescued.append(item)
        else:
            _LOST_BLOCKS.lost += 1
    return rescued


def _block_chunks(text: str) -> list[str]:
    """깨진 `blocks` 글자열을 **블록 하나씩**으로 자른다. 따옴표 안의 중괄호는 세지 않는다.

    ★ 2026-10-05 9B arXiv 판(d3a87ec6): 표를 닫는 `}` 가 빠진 블록은 예전 방식(`{…}` 한 쌍 찾기)으로는 **조각조차 안 잡혀**
      조용히 사라졌다 — 오류에는 「못 읽은 블록 0개」라고 나갔다. 블록은 `{` 에서 시작해 제 `}` 에서, 그것이 없으면 다음 블록의
      `{` 앞에서 끝난다(블록 안에는 중괄호가 없다 — 표의 줄은 대괄호다).
    """
    opens: list[int] = []
    closes: list[int] = []
    in_string = escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            opens.append(index)
        elif char == "}":
            closes.append(index)
    chunks: list[str] = []
    for number, start in enumerate(opens):
        limit = opens[number + 1] if number + 1 < len(opens) else len(text)
        close = next((at for at in closes if start < at < limit), None)
        chunks.append(text[start: close + 1] if close is not None else text[start:limit])
    return chunks


#: 값만 든 배열 하나(표의 한 줄). 따옴표 안의 대괄호는 줄의 끝이 아니다.
_FLAT_ROW = re.compile(r'\[(?:\s*(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)\s*,?)*\s*\]')


#: 빈 칸이 맨몸으로 온 줄까지 잡는다(`["G마켓", "", , , , "확인 불가"]`). 칸 값의 모양은 `_FLAT_ROW` 와 같다.
_LOOSE_ROW = re.compile(
    r'\[(?:\s*(?:(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)\s*)?,)*'
    r'\s*(?:(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)\s*)?\]'
)
_LOOSE_CELL = re.compile(r'\s*(?:("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)\s*)?([,\]])')


def _loose_row_cells(piece: str) -> list[Any] | None:
    """`[` 로 시작하는 줄 하나를 칸으로 가른다. 맨몸의 빈 칸은 빈 글자열이다. 못 읽으면 `None`."""
    cells: list[Any] = []
    at = 1
    while at < len(piece):
        found = _LOOSE_CELL.match(piece, at)
        if found is None:
            return None
        token, closer = found.group(1), found.group(2)
        if token is not None:
            try:
                cells.append(json.loads(token))
            except (ValueError, TypeError):
                return None
        elif closer == ",":
            cells.append("")
        # 닫는 괄호 바로 앞의 빈 자리는 끝에 붙은 쉼표다 — 칸으로 세지 않는다.
        at = found.end()
        if closer == "]":
            return cells
    return None


def _rows_from_string(text: str) -> list[Any]:
    """목록 대신 **글자열**로 온 표를 읽는다. 못 읽으면 빈 목록 — 그때는 예전처럼 「표가 있어야 합니다」로 돌아간다.

    ★ 2026-10-12 밤 공식 9B · 4B(창 32K) 가격 조사에서 **세 가게를 다 읽고도 파일이 안 나온 판**의 까닭이 이것이었다.
      이틀 동안 문서 쓰기 73번 중 `rows_or_sheets_required` 거절이 18번, 전부 `rows` 가 글자열이었다. 4B 한 판은 같은 표를
      네 번 보내고 네 번 거절당해 걸음을 다 썼다. 모델은 표를 넣었는데 도구는 「표가 있어야 합니다」라고 했다
      (`blocks` 글자열은 09-24 부터 읽는다 — `rows` 는 빠져 있었다. 이 함수의 머리말은 처음부터 「글자열도 받는다」였다).

      글자열이 된 까닭은 끝의 괄호 하나다. 그날 거절된 원문 셋의 끝:
          …"해외직구"]],        (쉼표가 하나 더)
          …"할인가"]}           (대괄호 대신 중괄호)
          …, , , "확인 불가"]]]  (대괄호가 하나 더 · 빈 칸이 맨몸)
      줄(가게 한 줄) 자체는 셋 다 온전했다.

    읽는 법: 통째로 JSON 이면 그대로. 아니면 줄을 **하나씩** 건진다 — `_table_from_chunk` 와 같은 원칙으로, 줄을 전부 건졌을
    때만 복구한다(건진 줄을 걷어내고 남는 것이 괄호 · 쉼표뿐이어야 한다). 줄이 빠진 표를 「성공」으로 내보내는 것은 돌려보내는
    것보다 나쁘다. 칸의 내용은 짐작해 고치지 않는다.
    """
    body = str(text or "").strip()
    if not body:
        return []
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    # ★ 표가 **온전히 닫힌 뒤에** 다른 것이 딸려 왔으면 표까지만 읽는다 (같은 날 밤 4B 판 b937ff5c — 고친 뒤에도 같은 표를
    #   세 번 거절했다). 끝이 `…"최저가"]],\n<open>\nTrue` 였다 — 다음 인자(`open`)의 꼬리표가 이 칸에 섞여 들어온 것이다.
    #   맨 앞에서 시작해 제대로 닫힌 목록이 표의 전부이고, 그 뒤는 표의 내용이 아니다.
    try:
        head, _end = json.JSONDecoder().raw_decode(body)
    except (ValueError, TypeError):
        head = None
    if isinstance(head, list) and head and all(isinstance(row, (list, dict)) for row in head):
        return head
    rows: list[Any] = []
    for found in _LOOSE_ROW.finditer(body):
        cells = _loose_row_cells(found.group(0))
        if cells is None:
            return []
        if cells:
            rows.append(cells)
    if re.sub(r"[\[\]\s,{}]", "", _LOOSE_ROW.sub("", body)):
        return []
    return rows


def _table_from_chunk(chunk: str) -> Any:
    """대괄호 개수가 틀린 표 블록에서 **줄을 하나씩** 건져 표를 다시 세운다. 표가 아니면 `None`.

    같은 판에서 두 가지로 깨졌다: 머리줄 뒤에서 표를 일찍 닫음(`[[머리]], [줄], [줄]]`) · 표를 닫는 `}` 가 빠짐(`[[머리], [줄]], {다음 블록`).
    두 번 다 줄(문자열 배열) 자체는 온전했다 — 틀린 것은 그 줄들을 감싸는 괄호의 개수뿐이다. 내용을 짐작해 고치지 않는다:
    `"rows"` 뒤에 온 줄을 순서대로 그대로 쓴다.
    """
    marker = re.search(r'"rows"\s*:', chunk)
    if marker is None or '"table"' not in chunk[: marker.start()] + chunk[marker.end():]:
        return None
    # ★ 줄을 **전부** 건졌을 때만 복구한다. 줄 안의 따옴표가 깨진 표(`"초보자를 위한 "파이썬" 200제"`)는 그 줄이 안 읽히는데,
    #   읽힌 줄만으로 표를 세우면 머리줄뿐인 엑셀이 「성공」으로 나간다 — 줄이 빠진 파일은 돌려보내는 것보다 나쁘다.
    #   읽힌 줄을 걷어내고 남는 것이 괄호·쉼표뿐이어야 한다.
    if re.sub(r"[\[\]\s,}]", "", _FLAT_ROW.sub("", chunk[marker.end():])):
        return None
    rows: list[list[Any]] = []
    for found in _FLAT_ROW.finditer(chunk, marker.end()):
        try:
            row = json.loads(found.group(0))
        except (ValueError, TypeError):
            continue
        if isinstance(row, list) and row:
            rows.append(row)
    return {"type": "table", "rows": rows} if rows else None


class _LostBlocks:
    """이번 문서 쓰기에서 **못 읽고 버린 블록 수** — 결과에 적어 모델이 다시 보내게 한다(`write_document`)."""

    lost = 0


_LOST_BLOCKS = _LostBlocks()


def _repaired_piece(piece: str) -> Any:
    """깨진 블록 하나를 읽는다. 흔한 실수 하나는 고쳐서 읽는다 (2026-09-28 T2 재측정 B1).

    모델이 표 머리 줄을 일찍 닫았다: `{"rows": [["순서","결정 사항","담당자","기한"]], ["1","","",""], …]}`.
    이 조각을 통째로 버려 「결정 사항 · 담당 · 기한」 제목 아래 **표가 없는** 워드가 나갔다. `]], [` 를 `], [` 로 한 번 고쳐 본다.
    """
    for attempt in (piece, piece.replace("]], [", "], [", 1)):
        try:
            return json.loads(attempt)
        except (ValueError, TypeError):
            continue
    return None


def _sheets_as_blocks(blocks: Any, sheets: Any) -> Any:
    """문서 형식에 온 `sheets`(엑셀용 칸)를 **시트마다 제목 + 표**로 옮긴다 (2026-09-28 대결 T2 O3).

    모델이 워드 회의록에 표 여럿을 넣으려고 `sheets` 를 썼다. 문서 쓰기는 그 칸을 아무 데도 안 썼고, 「내용 없음」 검사는
    `sheets` 가 있다는 이유로 통과시켜 **거의 빈 워드**가 `verified: true` 로 나갔다(모델은 다음 걸음에 다시 썼다).
    """
    if not isinstance(sheets, dict) or not sheets:
        return blocks
    out = list(blocks) if isinstance(blocks, list) else []
    for name, value in sheets.items():
        grid = _as_rows(value)
        if not grid:
            continue
        out.append({"type": "heading", "level": 2, "text": str(name)})
        out.append({"type": "table", "rows": grid})
    return out


def _with_inferred_types(blocks: Any) -> Any:
    """`type` 이 빠진 블록의 종류를 **칸 모양**으로 알아본다 (2026-09-28 헤르메스 대결 T2 온텔릭 판).

    모델이 표 다섯을 `{"rows": [...]}` 로 보냈다(`type` 없음). 블록 종류의 기본값이 문단이라 글 없는 문단 다섯이 됐고,
    **표가 말없이 사라졌다** — 도구는 `verified: true`, 답은 「담당자·기한 표」를 설명했다. 거짓말을 한 것은 모델이 아니라 도구다.
    `rows` 가 있으면 표, `level` 이 있으면 제목이다. 종류를 댄 블록은 건드리지 않는다.
    """
    if not isinstance(blocks, list):
        return blocks
    out: list[Any] = []
    for block in blocks:
        if isinstance(block, dict) and not str(block.get("type") or "").strip():
            if isinstance(block.get("rows"), list):
                block = {**block, "type": "table"}
            elif block.get("level") is not None and str(block.get("text") or "").strip():
                block = {**block, "type": "heading"}
        out.append(block)
    return out


#: 제목을 담는 칸 이름 — 모델이 `{"heading": "…", "paragraphs": […]}` 처럼 묶음으로 보낼 때 쓴다.
_SECTION_HEADING_KEYS = frozenset({"heading", "title", "header", "section", "subtitle", "name", "제목", "소제목", "머리말"})
#: 값이 목록일 때 글머리표로 쓸 칸 이름. 그 밖의 목록은 문단이다.
_SECTION_BULLET_KEYS = frozenset({"bullets", "items", "points", "list", "항목", "목록"})
#: 글(`text`)이 없어도 제 몫을 그리는 블록 종류 — 풀지 않는다.
_KINDS_DRAWN_WITHOUT_TEXT = frozenset({
    "table", "rule", "hr", "divider", "math", "equation", "formula", "footnote", "각주",
    "image", "figure", "picture", "chart", "toc", "spacer", "break", "page_break", "pagebreak",
})
_BLOCK_SETTING_KEYS = frozenset({"type", "level", "style", "language", "align", "text"})
_SECTION_DEPTH_MAX = 4


def _draws_nothing(block: dict[str, Any]) -> bool:
    """문서 쓰기가 이 블록에서 **아무것도 못 그리는가** — 글도 표도 없고, 글 없이 그리는 종류도 아니다."""
    if str(block.get("text") or "").strip() or block.get("rows"):
        return False
    if str(block.get("type") or "").strip().lower() in _KINDS_DRAWN_WITHOUT_TEXT:
        return False
    return not (block.get("math") or block.get("latex") or block.get("footnote") or block.get("각주") or block.get("texts"))


def _value_blocks(value: Any, *, bullet: bool, depth: int) -> list[Any]:
    if isinstance(value, str):
        body = value.strip()
        return [{"type": "bullet" if bullet else "paragraph", "text": body}] if body else []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [{"type": "paragraph", "text": str(value)}]
    if isinstance(value, dict):
        return _unpack_sections([value], depth + 1)
    if isinstance(value, (list, tuple)) and value:
        if all(isinstance(row, (list, tuple)) for row in value):
            return [{"type": "table", "rows": [list(row) for row in value]}]
        out: list[Any] = []
        for item in value:
            out.extend(_value_blocks(item, bullet=bullet, depth=depth))
        return out
    return []


def _unpack_sections(blocks: Any, depth: int = 0) -> Any:
    """문서 쓰기가 **못 그리는 모양의 블록**을 제목 · 문단 · 글머리표 · 표로 풀어 쓴다. 그릴 수 있는 블록은 건드리지 않는다.

    ★ 2026-10-12 밤, 4B(창 32K)에게 조사한 내용을 「한글이나 워드 파일로 전달해 줘」라고 하자 **글자가 0자인 한글 파일**이
      나왔고 도구는 성공이라고 했다(답: 「한글 파일로 정리했습니다」). 작은 카드로 쓰는 사람이 같은 날 겪은 「흰 화면뿐인
      파일」과 같은 모양이다. 모델이 보낸 것:

          [{"heading": "…분석 (2026년 10월)", "paragraphs": ["본 분석은 …", "…"]}, {"heading": "…", "paragraphs": […]}]

      문서 쓰기는 블록에서 `type` · `text` · `rows` 만 읽는다. 이 묶음에는 셋 다 없어서 「글 없는 문단」이 됐고, 내용이
      말없이 사라졌다. 「빈 문서를 성공이라 하지 않는다」 검사(09-24)는 **보낸 것**에 글자가 있는지를 봐서 통과시켰다 —
      쓰는 쪽이 읽는 칸과 검사가 보는 칸이 달랐다(09-28 의 「표가 말없이 사라졌다」와 같은 병, 다른 자리).

      모양을 외우게 하지 않는다. 못 그리는 블록의 칸을 차례로 풀어 쓴다 — 제목 칸은 제목, 글은 문단, 목록은 문단이나
      글머리표, 줄의 목록은 표, 묶음 안의 묶음은 한 단계 아래 제목으로. 내용은 그대로 옮기고 고치지 않는다.
    """
    if not isinstance(blocks, list) or depth > _SECTION_DEPTH_MAX:
        return blocks
    out: list[Any] = []
    for block in blocks:
        if not isinstance(block, dict) or not _draws_nothing(block):
            out.append(block)
            continue
        kind = str(block.get("type") or "").strip().lower()
        try:
            level = int(block.get("level")) if block.get("level") is not None else min(2 + depth, 4)
        except (TypeError, ValueError):
            level = min(2 + depth, 4)
        fields = [(str(key).strip().lower(), value) for key, value in block.items() if str(key).strip().lower() not in _BLOCK_SETTING_KEYS]
        pieces: list[Any] = []
        for name, value in fields:
            if name in _SECTION_HEADING_KEYS and isinstance(value, str) and value.strip():
                pieces.append({"type": "heading", "level": level, "text": value.strip()})
        for name, value in fields:
            if name in _SECTION_HEADING_KEYS and isinstance(value, str):
                continue
            pieces.extend(_value_blocks(
                value, bullet=name in _SECTION_BULLET_KEYS or kind in {"bullet", "list", "list_item"}, depth=depth,
            ))
        out.extend(pieces if pieces else [block])
    return out


def _draws_text(blocks: Any, rows: list[list[str]], text: str) -> bool:
    """문서 쓰기가 **실제로 그릴 글**이 하나라도 있는가 — 쓰는 쪽이 읽는 칸(`text` · 표 · 각주 · 수식)으로만 본다."""
    if any(any(str(cell).strip() for cell in row) for row in rows or []):
        return True
    if str(text or "").strip():
        return True
    for block in blocks if isinstance(blocks, list) else []:
        if isinstance(block, str):
            if block.strip():
                return True
            continue
        if not isinstance(block, dict):
            continue
        if str(block.get("text") or "").strip():
            return True
        if any(any(str(cell).strip() for cell in row) for row in _as_rows(block.get("rows"))):
            return True
        if block.get("math") or block.get("latex") or _footnote_texts(block.get("texts") or block.get("footnote") or block.get("각주")):
            return True
    return False


def _has_content(blocks: Any, rows: list[list[str]], text: str) -> bool:
    if any(any(str(cell).strip() for cell in row) for row in rows or []):
        return True
    if str(text or "").strip():
        return True
    for block in blocks if isinstance(blocks, list) else []:
        if isinstance(block, str) and block.strip():
            return True
        # 형식마다 칸 이름이 다르다(문단 text · 표 rows · PPT title/bullets …) — 글자나 목록이 하나라도 차 있으면 내용이다.
        if isinstance(block, dict) and any(
            (isinstance(value, str) and value.strip()) or (isinstance(value, (list, dict)) and value)
            for key, value in block.items() if key not in {"type", "level", "style"}
        ):
            return True
    return False


def _drop_thought_fragments(blocks: Any) -> Any:
    """속생각 태그가 **블록 두 개에 걸쳐** 쪼개져 온 것을 걷는다.

    실제로 온 모양(2026-09-13):

        {"type": "paragraph", "text": "<thought"}
        {"type": "paragraph", "text": ">사람인에서 '여수 회계'로 검색된 공고 중 …"}

    첫 블록은 태그 조각뿐이라 통째로 버리고, 바로 다음 블록 앞의 `>` 는 그 태그의
    닫는 꺾쇠이므로 벗긴다. 태그가 없으면 목록을 **그대로** 돌려준다.
    """
    if not isinstance(blocks, list):
        return blocks
    out: list[Any] = []
    strip_next = False
    for block in blocks:
        if not isinstance(block, dict):
            out.append(block)
            strip_next = False
            continue
        raw = str(block.get("text") or "")
        if not block.get("rows") and _THOUGHT_ONLY.fullmatch(raw):
            strip_next = not raw.rstrip().endswith(">")
            continue
        if strip_next and raw.lstrip().startswith(">"):
            block = {**block, "text": raw.lstrip()[1:].lstrip()}
        strip_next = False
        out.append(block)
    return out


#: 「값을 못 찾았다」를 값처럼 채운 칸. **「없음」·「-」는 넣지 않는다** — 「경력 무관」·
#   「지원자 없음」처럼 진짜 값일 수 있다. 못 찾았다는 말만 고른다.
_UNVERIFIED_CELL = re.compile(
    r"^\s*[\(\[]?\s*(?:확인\s*불가(?:능)?|확인\s*못\s*함?|확인되지\s*않음|미확인|"
    r"정보\s*없음|정보\s*미제공|알\s*수\s*없음|n\s*/\s*a)\s*[\)\]]?\s*$",
    re.IGNORECASE,
)


def _blank_unverified_cells(grid: list[list[str]]) -> tuple[list[list[str]], int]:
    """표 칸의 「확인 불가」류를 빈칸으로. 머리줄은 건드리지 않는다."""
    if len(grid) < 2:
        return grid, 0
    count = 0
    cleaned = [grid[0]]
    for row in grid[1:]:
        new_row = []
        for cell in row:
            if _UNVERIFIED_CELL.match(str(cell or "")):
                new_row.append("")
                count += 1
            else:
                new_row.append(cell)
        cleaned.append(new_row)
    return cleaned, count


def _blank_unverified_in_blocks(blocks: Any, *, note: bool) -> tuple[Any, int]:
    """★ 「확인 불가」로 채운 칸을 **비우고 끝에 한 번 적는다** (2026-09-14).

    새 과제 검사에서 잡코리아·알라딘 문서에 칸마다 「확인 불가」가 들어 있었다. 문서 스킬이
    금지한 모양이다 — 표가 차 보이는데 실제로는 비어 있다. 스킬 규칙(「못 찾았으면 문서 끝에
    한 번 적는다」)을 코드로 옮긴다. 값을 짓지 않고 **빈칸을 빈칸으로** 보이게 할 뿐이다.
    """
    if not isinstance(blocks, list):
        return blocks, 0
    total = 0
    out: list[Any] = []
    for block in blocks:
        if isinstance(block, dict) and str(block.get("type") or "").lower() == "table":
            grid = _table_grid(block)
            grid, count = _blank_unverified_cells(grid)
            if count:
                block = {**block, "rows": grid, "text": ""}
                total += count
        out.append(block)
    if total and note:
        out.append({
            "type": "paragraph",
            "text": f"빈 칸 {total}개는 페이지에서 값을 확인하지 못해 비워 두었습니다.",
        })
    return out, total


def _plain_inline(text: str) -> str:
    """`**굵게**` 를 벗긴다. 굵게를 못 입히는 자리(표 칸·한글·PPT)용."""
    return _BOLD.sub(r"\1", str(text or ""))


def _add_rich_paragraph(document: Any, body: str, style: str | None = None) -> Any:
    """`**굵게**` 를 **진짜 굵게**로 입혀 문단을 만든다.

    ★ 2026-09-13 양식 검사기가 잡았다 — 경쟁 분석 워드 문서에
    「1. **Python 중심의 에이전트 생태계:**」가 별표째 찍혀 있었다. 마크다운에서는
    굵게인데 워드에서는 글자다. 모델은 마크다운으로 생각하니 그걸 탓할 일이 아니고,
    받는 쪽이 서식으로 바꾸면 된다.
    """
    paragraph = document.add_paragraph(style=style) if style else document.add_paragraph()
    position = 0
    for match in _BOLD.finditer(body):
        if match.start() > position:
            paragraph.add_run(body[position:match.start()])
        run = paragraph.add_run(match.group(1))
        run.bold = True
        position = match.end()
    if position < len(body):
        paragraph.add_run(body[position:])
    return paragraph


def _heading_text(body: str) -> str:
    """제목 글에서 앞머리 `#` 를 벗긴다. 마크다운은 우리가 붙이고, 워드는 스타일로 준다."""
    return _clean_block_text(body).lstrip("#").strip()

def _md_table(grid: list[list[str]]) -> str:
    """파이프 표. **머리줄과 구분선이 있어야 표로 그려진다.**"""
    if not grid:
        return ""
    width = max(len(row) for row in grid)

    def line(cells: list[str]) -> str:
        padded = list(cells) + [""] * (width - len(cells))
        safe = [c.replace("|", '\\|').replace(chr(10), " ") for c in padded]
        return "| " + " | ".join(safe) + " |"

    out = [line(grid[0]), "|" + "|".join([" --- "] * width) + "|"]
    out += [line(row) for row in grid[1:]]
    return chr(10).join(out)


def _write_markdown(target: Path, blocks: Any, rows: list[list[str]], text: str) -> dict[str, Any]:
    """마크다운을 **마크다운으로** 쓴다.

    ## 왜 따로 있어야 하나 (2026-09-11)

    `md` 에 쓰기 함수가 없어서 평문 갈래로 떨어지고 있었다. 그래서 「파이썬 책
    3권을 마크다운 문서로」가 이렇게 나왔다 —

        제목⇥쪽수⇥ISBN⇥상세페이지 URL
        Do it! 점프 투 파이썬⇥432쪽⇥9791163034735⇥https://…

    **탭 구분 텍스트다.** 제목도 없고 표도 아니라 마크다운으로 열면 한 줄로
    뭉개진다. 채점기가 「표 0행」이라 한 것이 맞았고, 모델이 게을러서가 아니라
    **우리가 그렇게 쓰고 있었다.**

    `blocks` 를 주면 제목·문단·목록·표로 그리고, 안 주면 `rows` 를 파이프 표로
    만든다. 둘 다 없을 때만 글을 그대로 쓴다 — 다른 형식과 같은 약속이다.
    """
    parts: list[str] = []
    written = 0
    for block in blocks if isinstance(blocks, list) else []:
        if isinstance(block, str):
            parts.append(block)
            written += 1
            continue
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or "paragraph").lower()
        body = _clean_block_text(block.get("text") or "")
        if kind in {"heading", "h1", "h2", "h3"}:
            level = int(block.get("level") or (1 if kind in {"heading", "h1"} else 2))
            # 모델이 `#` 를 이미 붙여 보낸다. 안 벗기면 `# # 제목` 이 된다.
            parts.append("#" * max(1, min(level, 6)) + " " + _heading_text(body))
        elif kind in {"bullet", "list"}:
            # 모델이 「- 」를 이미 붙여 보낸다. 안 벗기면 `- - 항목` 이 된다
            #  (`# #` 과 같은 병, 2026-09-11 라이브).
            parts.append("- " + re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", body))
        elif kind == "table":
            grid = _table_grid(block)
            if grid:
                parts.append(_md_table(grid))
        elif kind in {"code", "pre"}:
            fence = "```" + str(block.get("language") or "")
            parts.append(fence + chr(10) + body + chr(10) + "```")
        elif kind in {"quote", "blockquote"}:
            parts.append("> " + body)
        elif kind in {"rule", "hr", "divider"}:
            parts.append("---")
        else:
            parts.append(body)
        written += 1
    if not written:
        if rows:
            parts.append(_md_table(rows))
            written = len(rows)
        elif text:
            parts.append(text)
            written = 1
    body = (chr(10) * 2).join(part for part in parts if part).strip() + chr(10)
    target.write_text(body, encoding="utf-8")
    return {"chars": len(body), "blocks": written}


def _wants_math(blocks: Any) -> bool:
    """수식 블록을 달라고 했나. `_wants_footnotes` 와 같은 규율이다."""
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").lower() in {"math", "equation", "formula"}:
            return True
        if block.get("math") or block.get("latex"):
            return True
    return False


def _write_docx(target: Path, blocks: Any, rows: list[list[str]], text: str) -> dict[str, Any]:
    from docx import Document

    # ★ **못 하는 것은 못 한다고 말한다** (2026-09-01).
    #
    #   python-docx 에는 각주 API 가 없다. 그런데 조용히 본문에 끼워 넣으면
    #   「각주 달아줘」가 `[수정 제안: …]` 라는 **본문 글**로 나오고, 사람은
    #   각주인 줄 안다 — 라이브에서 정확히 그랬다. 한글(hwpx)로 가면 진짜
    #   각주가 되므로, 그 길을 알려 주고 여기서 멈춘다.
    # ★ **수식도 못 하는 것은 못 한다고 말한다** (2026-09-11).
    #
    #   python-docx 에 수식(OMML) API 가 없다. 각주와 같은 자리다. 조용히 글로
    #   써 넣으면 `$A = P(1+r/n)^{nt}$` 가 **본문 글자로** 나오고 사람은 수식인 줄 안다.
    #
    #   짓지 않은 이유는 수요를 재 봤기 때문이다 — 라이브 프롬프트 833개에서 수식을
    #   말한 것은 **0건**이었다(10건이 걸렸는데 전부 「**공식** reCAPTCHA」였다).
    #   필요해지면 그때 짓는다. 그전까지는 **마크다운으로 보내라고 알려 준다** —
    #   `$...$` 는 우리 마크다운 쓰기가 손대지 않고 그대로 통과시킨다.
    if _wants_math(blocks):
        raise ValueError(
            "docx_math_unsupported — 워드(docx)에는 수식을 넣을 수 없습니다."
            " 수식이 필요하면 format 을 md 로 주세요($...$ 가 그대로 살아갑니다)."
        )
    if _wants_footnotes(blocks):
        raise ValueError(
            "docx_footnotes_unsupported — 워드(docx)에는 각주를 넣을 수 없습니다."
            " 각주가 필요하면 format 을 hwpx 로 주세요(한글 문서는 진짜 각주가 됩니다)."
        )

    document = Document()
    _apply_document_theme(document)
    written = 0
    for block in blocks if isinstance(blocks, list) else []:
        if isinstance(block, str):
            document.add_paragraph(block)
            written += 1
            continue
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or "paragraph").lower()
        body = _clean_block_text(block.get("text") or "")
        if not body and kind != "table":
            continue
        if kind in {"heading", "h1", "h2", "h3"}:
            level = int(block.get("level") or (1 if kind in {"heading", "h1"} else 2))
            # 워드는 스타일로 제목을 준다 — 글에 `#` 가 남아 있으면 그대로 보인다.
            document.add_heading(_plain_inline(_heading_text(body)), level=max(0, min(level, 4)))
        elif kind in {"bullet", "list"}:
            item = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", body)
            _add_rich_paragraph(document, item, style="List Bullet")
        elif kind == "table":
            grid = _table_grid(block)
            if grid:
                table = document.add_table(rows=1, cols=len(grid[0]))
                table.style = "Light Grid Accent 1"
                for index, cell in enumerate(grid[0]):
                    table.rows[0].cells[index].text = _plain_inline(cell)
                for row in grid[1:]:
                    cells = table.add_row().cells
                    for index, cell in enumerate(row[: len(grid[0])]):
                        cells[index].text = _plain_inline(cell)
                _style_table(table)
        elif _RULE_ONLY.match(body):
            # 마크다운 구분선(`---`)은 워드에서 「---」 글자 한 줄이 된다.
            continue
        else:
            _add_rich_paragraph(document, body)
        written += 1
    if not written:
        # blocks 를 안 줬으면 표나 글로 만든다. 빈 문서를 내놓지 않는다.
        if rows:
            table = document.add_table(rows=1, cols=len(rows[0]))
            table.style = "Light Grid Accent 1"
            for index, cell in enumerate(rows[0]):
                table.rows[0].cells[index].text = cell
            for row in rows[1:]:
                cells = table.add_row().cells
                for index, cell in enumerate(row[: len(rows[0])]):
                    cells[index].text = cell
            _style_table(table)
            written = len(rows)
        else:
            for line in text.splitlines() or [""]:
                document.add_paragraph(line)
                written += 1
    document.save(target)
    return {"blocks": written}


def _write_pptx(target: Path, blocks: Any, text: str) -> dict[str, Any]:
    from pptx import Presentation

    deck = Presentation()
    slides = blocks if isinstance(blocks, list) and blocks else [{"title": text[:80], "bullets": []}]
    for block in slides:
        item = block if isinstance(block, dict) else {"title": str(block), "bullets": []}
        layout = deck.slide_layouts[1]
        slide = deck.slides.add_slide(layout)
        slide.shapes.title.text = str(item.get("title") or "")[:200]
        body = slide.placeholders[1].text_frame
        bullets = item.get("bullets")
        lines = bullets if isinstance(bullets, list) else str(item.get("text") or "").splitlines()
        for index, line in enumerate(lines or [""]):
            paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
            paragraph.text = str(line)[:400]
    deck.save(target)
    return {"slides": len(deck.slides._sldIdLst)}


def _footnote_texts(value: Any) -> list[str]:
    """각주 인자를 **여러 개**로 읽는다.

    ★ 2026-09-02 라이브. 「1순위부터 3순위까지 회사별로 각주 달아줘」에 자비스는
    사고에서 이렇게 계획했다:

        For "42억 원 규모 세부과제별 지출 서류 검토":
          [늘봄마루소프트 제안] … [새솔바이오 제안] … [한빛넥스 제안] …

    한 문단에 각주 셋을 달려던 것이다. 그런데 `footnote` 가 **문자열 하나**만
    받으니 셋을 이어 붙여 하나로 만들었다 — 각주 1개, 요구는 3개, 미달.

    **모델이 게으른 게 아니라 담을 칸이 없었다.** 도구가 없으면 흉내 낸다는,
    이 저장소가 아는 그 병의 또 다른 얼굴이다. 목록도 받는다.
    """
    if isinstance(value, str):
        body = value.strip()
        return [body] if body else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict):
                # {"회사": "늘봄마루소프트", "text": "…"} 꼴도 받는다.
                label = str(item.get("label") or item.get("회사") or item.get("company") or "")
                body = str(item.get("text") or item.get("note") or item.get("각주") or "").strip()
                if body:
                    out.append(f"[{label}] {body}" if label else body)
                continue
            body = str(item or "").strip()
            if body:
                out.append(body)
        return out
    return []


def _add_footnote(document: Any, paragraph: Any, text: str) -> int:
    """진짜 각주를 단다. 단 개수를 돌려준다(못 달면 0).

    ★ 이게 없어서 라이브에서 **각주를 흉내 냈다** (2026-09-01). 자비스는
    「고칠 만한 곳마다 각주로 수정 제안을 달아줘」에 본문 안에
    `[수정 제안: …]` 라고 써 넣었다 — 각주가 아니다. 도구에 각주 블록이 없으니
    그것밖에 할 수 없었다. **도구가 없으면 흉내 낸다**, 이 저장소가 아는 그 병이다.

    `python-hwpx` 는 6.0 에서 `doc.add_footnote` 를 `doc.notes.add_footnote` 로
    옮겼고 7.0 에서 옛 자리를 없앤다. 새 자리를 먼저 쓰고 옛 판으로 떨어진다.
    """
    body = str(text or "").strip()
    if not body:
        return 0
    notes = getattr(document, "notes", None)
    try:
        if notes is not None and hasattr(notes, "add_footnote"):
            notes.add_footnote(body, paragraph=paragraph)
        else:  # pragma: no cover - python-hwpx 6.0 미만
            document.add_footnote(body, paragraph=paragraph)
    except Exception:
        # 각주를 못 달았다고 문서를 통째로 실패시키지 않는다. 대신 **세지도 않는다** —
        # 안 달린 것을 달렸다고 보고하는 것이 더 나쁘다.
        return 0
    return 1


def _write_hwpx(target: Path, blocks: Any, rows: list[list[str]], text: str) -> dict[str, Any]:
    """한글 문서(HWPX)를 **한글 없이** 만든다.

    ★ 왜 이게 국내에서 큰가 (2026-09-01)

    기존 `hwp_*` 도구 넷은 COM(pywin32)이라 **한글이 켜져 있고 그 문서가 열려
    있어야** 동작한다. 새 문서를 만들거나 디스크의 파일을 고칠 수는 없었다.
    그래서 「한글 문서로 정리해 줘」가 통째로 안 됐다 — 국내 학원·공공·기업 문서가
    대부분 한글인데.

    HWPX 는 ZIP+XML(OWPML) 구조라 순수 파이썬으로 만들 수 있다. 한글을 띄우지
    않으므로 **사람이 편집 중인 문서를 건드릴 위험도 없다.**
    """
    from hwpx import HwpxDocument

    document = HwpxDocument.new()
    written = 0
    notes = 0
    last_paragraph = None
    for block in blocks if isinstance(blocks, list) else []:
        if isinstance(block, str):
            last_paragraph = document.add_paragraph(block)
            written += 1
            continue
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or "paragraph").lower()
        body = str(block.get("text") or "")
        if kind in {"heading", "h1", "h2", "h3"}:
            level = int(block.get("level") or (1 if kind in {"heading", "h1"} else 2))
            document.add_heading(body, level=max(1, min(level, 4)))
            last_paragraph = None
        elif kind == "table":
            grid = _table_grid(block)
            if grid:
                table = document.add_table(rows=len(grid), cols=len(grid[0]))
                for r, line in enumerate(grid):
                    for c, cell in enumerate(line[: len(grid[0])]):
                        table.cell(r, c).set_text(cell)
            last_paragraph = None
        elif kind in {"footnote", "각주"}:
            # 앞 문단에 **진짜 각주**를 단다. 문단이 없으면 하나 만들어 거기 단다.
            for one in _footnote_texts(block.get("texts") or block.get("footnote") or body):
                notes += _add_footnote(document, last_paragraph, one)
            written += 1
            continue
        elif kind in {"bullet", "list", "list_item"}:
            # 한글 문단에는 목록 서식이 없다 — 글머리표를 글자로 붙여 목록으로 보이게 한다(2026-09-24).
            last_paragraph = document.add_paragraph("• " + body)
        else:
            last_paragraph = document.add_paragraph(body)
        written += 1
        # 문단에 각주를 같이 준 꼴도 받는다 — 이쪽이 더 자연스럽다.
        #     {"type":"paragraph","text":"본문","footnote":"수정 제안"}
        for rider in _footnote_texts(block.get("footnote") or block.get("각주")):
            notes += _add_footnote(document, last_paragraph, rider)
    if not written:
        if rows:
            table = document.add_table(rows=len(rows), cols=len(rows[0]))
            for r, line in enumerate(rows):
                for c, cell in enumerate(line[: len(rows[0])]):
                    table.cell(r, c).set_text(cell)
            written = len(rows)
        else:
            for line in text.splitlines() or [""]:
                document.add_paragraph(line)
                written += 1
    document.save_to_path(target)
    return {"blocks": written, "footnotes": notes}


#: 문서 꼴을 갖췄나. **과제와 무관하게** 어느 문서에나 적용된다.
#
# ★ 2026-09-11. 서식을 코드가 입히게 했지만(`_apply_document_theme`) **뼈대는
#   모델이 준다.** 라이브에서 큰 제목이 `Normal` 로 나온 것은 모델이 전부
#   `paragraph` 로 보냈기 때문이다.
#
#   그래서 만든 **직후에** 말해 준다. 판이 끝난 뒤 채점하면 이미 늦다 — 이 저장소가
#   배운 것이 「아직 할 수 있을 때 말해 줘야 한다」이다(`remaining_note` 주석).
#
#   막지는 않는다. 제목 없는 문서가 맞는 경우도 있다(한 줄 메모·초안 조각).
#   **알려주고 판단은 부르는 쪽에 맡긴다.**
_SHAPED_FORMATS = frozenset({"docx", "hwpx", "md", "pptx"})


#: 이 줄이 **열 이름이 아니라 값**으로 보이는가.
#
# 머리줄은 짧은 이름이다 — 주소도 긴 숫자도 안 들어간다. 하나라도 있으면 값이다.
# 넉넉히 잡지 않는다: 「2026년 매출」 같은 열 이름이 죽으면 안 되므로 **네 자리를
# 넘는 숫자**와 **주소**만 본다.
_DATA_CELL = re.compile(r"https?://|www\.|[0-9]{5,}")


def _grid_from_text(text: str) -> list[list[str]]:
    """`"[['가','나'],['1','2']]"` 처럼 **격자를 문자열로 담아 온 것**을 되살린다.

    파이썬 리터럴로도 JSON 으로도 올 수 있어 둘 다 받는다. 격자 모양이 아니면
    빈 목록을 돌려준다 — 아무 문자열이나 표로 바꾸지 않는다.
    """
    body = str(text or "").strip()
    if not body.startswith("[") or not body.endswith("]"):
        return []
    for parse in (json.loads, ast.literal_eval):
        try:
            value = parse(body)
        except Exception:  # noqa: BLE001 — 모양이 아니면 조용히 포기한다
            continue
        if (
            isinstance(value, list)
            and value
            and all(isinstance(row, (list, tuple)) for row in value)
        ):
            return [[str(cell) for cell in row] for row in value]
    return []


def _md_header_cells(text: str) -> list[str]:
    """`| 도서명 | 쪽수 |` 같은 **머리줄 한 줄**을 칸으로 쪼갠다. 아니면 빈 목록."""
    line = str(text or "").strip()
    if line.count(chr(10)) or not line.startswith("|"):
        return []
    if set(line.replace("|", "").strip()) <= set("-: "):
        return []
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return cells if len(cells) >= 2 and any(cells) else []


def _table_grid(block: dict[str, Any]) -> list[list[str]]:
    """표 블록의 **행 전부** — `text` 에 온 머리줄까지 되찾아 온다.

    ★ 왜 (2026-09-12 n=3 벤치)

    모델이 표를 이렇게 준다. 틀린 모양이 아니다 — 머리줄을 `text` 에, 값을
    `rows` 에 나눠 담는다:

        {"type": "table",
         "text": "| 도서명 | 쪽수 | ISBN | 상세 페이지 URL |",
         "rows": [["Do it! 점프 투 파이썬", "432쪽", "9791163034735", "https://…"]]}

    그런데 우리는 `rows` 만 읽고 `text` 를 버렸다. 그래서 만들어진 파일이 이랬다:

        | Do it! 점프 투 파이썬 | 432쪽 | 9791163034735 | https://… |
        | --- | --- | --- | --- |

    **열 이름이 사라지고 유일한 값이 머리줄로 먹혔다.** 데이터 0줄짜리 표다.
    채점기는 「열 0/4 · 채움 0%」로 찍었고 그게 정확했다 — yes24 두 판이 이것이다.
    조사는 다 해 놓고 담는 자리에서 잃었다.

    되찾아 오는 조건을 좁게 둔다: `text` 가 파이프 한 줄이고, 이미 있는 첫 줄이
    값으로 보이고, 칸 수가 맞을 때만. 셋 다 아니면 손대지 않는다 —
    **데이터를 망가뜨리느니 그대로 두고 짚어 준다.**
    """
    grid = _as_rows(block.get("rows"))
    # ★ 격자를 통째로 `text` 에 문자열로 담아 보내기도 한다 (2026-09-12 실측).
    #
    #     {"type": "table", "rows": [],
    #      "text": "[['도서명', '쪽수', 'ISBN', 'URL'], ['모두의 파이썬', '200쪽', …]]"}
    #
    #   행이 0개라 우리는 표를 아예 안 썼고, 파일에는 제목과 한 줄 설명만 남았다.
    #   조사한 세 권이 통째로 사라졌다(채움 0%). 모델이 판단을 잘못한 것이 아니라
    #   **담는 그릇을 문자열로 바꿔 보낸 것**이고, 그건 되살릴 수 있다.
    if not grid:
        grid = _as_rows(_grid_from_text(block.get("text") or ""))
        if grid:
            return grid
    head = _md_header_cells(block.get("text") or "")
    if not head:
        return grid
    if not grid:
        return [head]
    if len(head) != len(grid[0]):
        return grid
    if not _looks_like_data_row(grid[0]):
        return grid
    return [head] + grid


def _looks_like_data_row(row: list[str]) -> bool:
    return any(_DATA_CELL.search(str(cell or "")) for cell in row)

def _shape_notes(fmt: str, blocks: Any, rows: list[list[str]], text: str) -> list[str]:
    """문서 꼴에서 빠진 것을 짚는다. 없으면 빈 목록."""
    if fmt not in _SHAPED_FORMATS:
        return []
    kinds = [
        str(b.get("type") or "paragraph").lower()
        for b in (blocks if isinstance(blocks, list) else [])
        if isinstance(b, dict)
    ]
    # ★ **글로 온 마크다운도 읽는다** (2026-09-21 실전).
    #
    #   모델이 `text` 로 마크다운을 통째로 주면 `blocks` 가 비어 있다. 그런데 여기서
    #   `blocks` 만 보고 있었으므로, 첫 줄이 `# 제목` 이어도 언제나 「제목이 없다」가
    #   붙었다. 파일은 제목도 표도 멀쩡했다 — **거짓말은 안내문 쪽이었다.**
    #
    #   실전 손해: 모델이 안내를 믿고 blocks 로 바꿨다가, 표가 안 서 보이니 다시 text 로
    #   돌아오기를 **여섯 번** 반복하고 10분을 태웠다. 쓰레기 산출물 6개가 남았다.
    #
    #   막는 것보다 나쁘다 — 벽이 아닌 곳을 벽이라고 하면 모델은 맞는 답을 버린다.
    if not kinds and text.strip():
        kinds = [
            str(b.get("type") or "paragraph").lower()
            for b in blocks_from_markdown(text)
            if isinstance(b, dict)
        ]
    notes: list[str] = []
    if not any(k in {"heading", "h1", "h2", "h3", "title"} for k in kinds):
        notes.append(
            "제목이 없다 — 첫 블록을 "
            + chr(39) + chr(123) + chr(34) + "type" + chr(34) + ":" + chr(34) + "heading"
            + chr(34) + "," + chr(34) + "level" + chr(34) + ":1," + chr(34) + "text" + chr(34)
            + ":" + chr(34) + "…" + chr(34) + chr(125) + chr(39) + " 로 주면 문서에 제목이 선다"
        )
    if len(rows) >= 2 and not any(k == "table" for k in kinds):
        notes.append("표로 줄 것을 글로 보냈다 — rows 는 table 블록으로 주면 표가 된다")
    # ★ **머리줄만 있는 표는 빈 표다** (2026-09-11).
    #
    #   사슬 벤치에서 yes24 판이 **두 모델·두 라운드 모두** 이렇게 나왔다 — 표 산출물
    #   8개 중 4개다:
    #
    #       | 제목 | 저자 | 쪽수 | ISBN13 | URL |
    #       | --- | --- | --- | --- | --- |        ← 행 0개
    #       ## 1. Do it! 첫 파이썬                   ← 값은 절에 흩어짐
    #       엘리스 코딩 | 이지스퍼블리싱 | 268쪽 | …
    #
    #   내용은 다 조사해 놓고 **담는 그릇만 틀렸다.** 기계가 합쳐 넣을 수도 있지만
    #   열이 한 칸씩 밀려 있어(제목이 절 머리로 빠졌다) 저자 칸에 출판사가 들어간다.
    #   **데이터를 망가뜨리느니 짚어 주고 모델이 고치게 한다.**
    for block in (blocks if isinstance(blocks, list) else []):
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").lower() != "table":
            continue
        grid = _table_grid(block)
        if len(grid) == 1:
            notes.append(
                "표에 머리줄만 있고 값이 한 줄도 없다 — 각 항목을 표의 **행**으로 "
                "넣어라. 절(##)에 풀어 쓰면 표로 안 읽힌다"
            )
            break
        if grid and _looks_like_data_row(grid[0]):
            # ★ 머리줄만 있던 것을 고쳤더니 이번엔 **머리줄이 없다** (2026-09-11).
            #
            #   같은 판이 이렇게 나왔다 — 첫 줄부터 값이다:
            #
            #       | Do it! 점프 투 파이썬 | 432쪽 | 9791163034735 | https://… |
            #       | --- | --- | --- | --- |
            #
            #   표의 첫 줄은 **열 이름**이다. 값이 거기 앉으면 그 항목은 통째로
            #   사라지고(머리줄로 먹힘), 받는 쪽은 어느 칸이 무엇인지 모른다.
            notes.append(
                "표에 머리줄이 없다 — 첫 줄이 값으로 보인다. 열 이름(예: 도서명·쪽수"
                "·ISBN·URL)을 **첫 줄**로 넣고 값은 그 아래부터 넣어라"
            )
            break
    # 「덩어리」는 **꼴이 없을 때**의 말이다. 위에서 글의 마크다운을 이미 읽었으므로,
    # 제목도 표도 목록도 없이 문단만 있을 때에만 남는다 — 그때는 사실이다.
    if not any(k in {"heading", "h1", "h2", "h3", "title", "table", "bullet"} for k in kinds) and text:
        notes.append("글 한 덩어리로 저장했다 — blocks 로 나누면 제목·표가 산다")
    return notes

def rows_from_blocks(blocks: Any) -> list[list[str]]:
    """`blocks` 안의 표를 꺼내 `rows` 로 만든다.

    ## 왜 (2026-09-11)

    스킬에 「제목은 heading, 표는 table 블록으로 줘라」를 넣었더니 모델이 **엑셀에도**
    그렇게 보냈다. 그런데 xlsx·csv 는 `rows`/`sheets` 만 받아서 네 번 연속 거부했다:

        오류: rows_or_sheets_required
        인자: blocks=[heading, paragraph, table…]   ← 내용은 다 있었다

    조사·표 작성을 다 해 놓고 **그릇 이름이 안 맞아서** 파일이 안 나왔다. 사슬 9/10
    에서 7/10 으로, 채움 67% 에서 38% 로 떨어진 원인이 이것이다 — 내가 낸 회귀다.

    안내문을 되돌리는 대신 **받는 쪽을 넓힌다.** 부르는 쪽이 형식마다 다른 모양을
    외워야 하면 그건 언젠가 틀린다. 「블록으로 주면 알아서 한다」가 규칙이어야 한다.
    """
    out: list[list[str]] = []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").lower() != "table":
            continue
        grid = _table_grid(block)
        if not grid:
            continue
        if out and grid[0] == out[0]:
            grid = grid[1:]      # 표가 여럿이고 머리줄이 같으면 한 번만 쓴다
        out.extend(grid)
    return out


def twin_column_notes(rows: list[list[str]]) -> list[str]:
    """표의 **두 칸이 모든 줄에서 같은 값**이면 쓴 직후에 짚어 준다 (2026-10-14).

    어머님 부탁(쿠팡 캣타워)으로 만든 엑셀에서 「평점 수」 칸과 「리뷰 수」 칸에 같은
    숫자가 세 줄 다 들어갔다 — 한 칸에 들어갈 값을 두 칸에 나눠 적은 것이다. 모델의
    판단이 아니라 표의 **모양**이라, 쓰기 직후에 짚을 수 있다.

    지키는 것:
    - 첫 줄은 머리줄, 그 아래 값 줄이 **두 줄 이상**이어야 본다.
    - 서로 다른 두 칸의 값(앞뒤 공백 무시)이 모든 값 줄에서 같고, 두 칸이 **모든 줄에서
      비어 있는 것**은 아니면, 그 두 칸의 머리줄 이름이 든 알림을 하나 만든다.
    - 막지 않는다 — 정말로 같은 값인 표도 있다. 짚어 주고 모델이 다시 보게 한다.
    """
    value_rows = [row for row in rows[1:] if row]
    if len(value_rows) < 2:
        return []
    header = rows[0]
    width = max((len(row) for row in rows), default=0)
    notes: list[str] = []
    for i in range(width):
        for j in range(i + 1, width):
            all_same = True
            all_blank = True
            for row in value_rows:
                vi = str(row[i]).strip() if i < len(row) else ""
                vj = str(row[j]).strip() if j < len(row) else ""
                if vi != vj:
                    all_same = False
                    break
                if vi:
                    all_blank = False
            if all_same and not all_blank:
                name_i = str(header[i]).strip() if i < len(header) else f"{i + 1}번째"
                name_j = str(header[j]).strip() if j < len(header) else f"{j + 1}번째"
                notes.append(
                    f"'{name_i}' 칸과 '{name_j}' 칸의 값이 모든 줄에서 같습니다 — "
                    "한 칸에 들어갈 값을 두 칸에 나눠 적었는지 확인하세요"
                )
    return notes


def _column_shape(header: str) -> str | None:
    """머리줄 이름이 값의 **꼴**을 정하는 칸이면 그 꼴 이름, 아니면 `None`.

    '평점 수'·'리뷰 수' 같은 **개수** 칸은 평점(0~5)이 아니라 **개수**이므로,
    평점 판정에서 '수'·'개수'를 뺀다.
    """
    name = header.strip()
    low = name.lower()
    if ("평점" in name or "별점" in name) and "수" not in name and "개수" not in name:
        return "평점(0~5점)"
    if "가격" in name or "판매가" in name or "금액" in name:
        return "금액"
    # 「주소」만으로는 웹 주소인지 모른다 — 한국어에서는 집 · 매장 주소가 더 흔하다. 웹을 가리키는 말이 붙을 때만 링크로 본다.
    if "링크" in low or "url" in low or any(word in name for word in ("웹 주소", "페이지 주소", "상품 주소", "읽은 주소")):
        return "링크"
    if "리뷰 수" in name or "평점 수" in name or "상품평" in name or "후기 수" in name:
        return "개수"
    return None


def _value_fits_shape(shape: str, value: str) -> bool:
    """`shape` 가 정한 꼴에 `value` 가 맞는가."""
    # ★ 칸의 **첫 값**으로 본다 — 「118,810원 (쿠폰 적용 시)」 · 「4.5 (808개)」처럼 설명이 붙은 값이 흔하다(2026-10-14 · 8GB
    #   노트북 결과에 실제로 있었다). 통째 맞춤으로 보면 멀쩡한 값을 틀렸다고 짚는다 — 짚는 말이 틀리면 모델은 맞는 답을 버린다.
    v = value.strip()
    if shape == "평점(0~5점)":
        if "%" in v.split("(")[0]:
            return False
        m = re.match(r"[\*★☆\s]*(\d+(?:\.\d+)?)", v)
        return bool(m) and 0 <= float(m.group(1)) <= 5
    if shape == "금액":
        return re.match(r"(?:₩|\$|약\s*)?\s*\d[\d,]*(?:\.\d+)?\s*(?:원|만\s*원)?", v) is not None
    if shape == "링크":
        return v.lower().startswith(("http://", "https://"))
    if shape == "개수":
        return "%" not in v and re.match(r"\(?\s*\d[\d,]*(?!\.\d)", v) is not None
    return True


def column_shape_notes(rows: list[list[str]]) -> list[str]:
    """머리줄 이름이 값의 **꼴**을 정하는 칸에서, 값이 그 꼴과 안 맞으면 짚어 준다 (2026-10-14).

    막지 않고 **알린다.** 그 칸의 빈칸 아닌 값이 **두 개 이상**이고 그중 **절반을
    넘게** 그 꼴이 아니면, 칸 이름과 예시 값을 넣은 알림 한 줄을 만든다.

    꼬인 꼴 넷:
    - '평점'·'별점' (그리고 '수'·'개수' 아님) → 0~5점 (4.5 · 4.5점 · ★4.5 · 4.5/5). 89% 같은 퍼센트는 아님.
    - '가격'·'판매가'·'금액' → 금액 (14,150원 · 14150 · ₩14,150).
    - '링크'·'주소'·'URL' (대소문자 무시) → http:// 또는 https:// 로 시작.
    - '리뷰 수'·'평점 수'·'상품평'·'후기 수' → 개수 (784 · 784개 · 1,275개).
    """
    if len(rows) < 2:
        return []
    header = rows[0]
    width = max((len(row) for row in rows), default=0)
    notes: list[str] = []
    for i in range(width):
        if i >= len(header):
            continue
        shape = _column_shape(str(header[i]))
        if shape is None:
            continue
        values: list[str] = []
        for row in rows[1:]:
            v = str(row[i]).strip() if i < len(row) else ""
            if v:
                values.append(v)
        if len(values) < 2:
            continue
        bad = [v for v in values if not _value_fits_shape(shape, v)]
        if len(bad) > len(values) / 2:
            notes.append(
                f"'{str(header[i]).strip()}' 칸에는 {shape} 꼴의 값이 와야 하는데 절반이 넘게 그 꼴이 아닙니다 "
                f"(예: '{bad[0]}') — 다른 값을 이 칸에 넣었는지 확인하세요"
            )
    return notes


def write_document(
    target: Path, format_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """`format_name` 대로 `target` 에 만든다. 만든 것의 **모양**을 돌려준다.

    돌려주는 값이 "몇 줄·몇 장"인 이유는, 만들었다는 주장만으로는 빈 파일과 구별이
    안 되기 때문이다.
    """
    fmt = format_name.lower().lstrip(".")
    if fmt not in WRITABLE:
        # ★ 막기만 하면 모델은 같은 벽에 계속 부딪친다 (2026-09-20 실전: 프론트 과제가
        #   `local_write_file` 에 막히자 여기로 흘러와 `html` 을 요청하고 또 막혔다).
        #   이 도구는 **표·문단으로 문서를 짜는** 자리다. 소스 파일은 글자를 그대로
        #   쓰는 도구의 일이니, 어디로 가야 하는지 같이 말해 준다.
        source_like = {"html", "htm", "js", "jsx", "ts", "tsx", "css", "py", "json", "yml", "yaml", "toml", "xml"}
        door = (
            f" — `{fmt}` 는 소스 파일이라 이 도구의 일이 아니다. `local_write_file` 로 글자를 그대로 써라."
            if fmt in source_like
            else f" — 이 도구가 만들 수 있는 것: {', '.join(WRITABLE)}"
        )
        raise ValueError(f"format_not_writable:{fmt}{door}")
    rows = _as_rows(payload.get("rows"))
    text = _scrub_model_markup(str(payload.get("text") or ""))
    _LOST_BLOCKS.lost = 0
    blocks = _with_inferred_types(_drop_thought_fragments(_blocks_from_payload(payload.get("blocks"))))
    lost_blocks = _LOST_BLOCKS.lost
    if fmt in {"docx", "hwpx", "pptx", "md", "txt"}:
        blocks = _sheets_as_blocks(blocks, payload.get("sheets"))
    # 칸마다 「확인 불가」를 채운 표는 차 보이지만 비어 있다 — 비우고 끝에 한 번 적는다.
    rows, blanked_rows = _blank_unverified_cells(rows)
    blocks, blanked_blocks = _blank_unverified_in_blocks(
        blocks, note=fmt in {"md", "docx", "hwpx", "pptx"}
    )
    blanked = blanked_rows + blanked_blocks
    if fmt in {"docx", "hwpx", "pptx"}:
        blocks = _markdown_to_blocks(blocks, text, strip_bold=fmt == "hwpx")
    # ★ **빈 문서를 성공이라 하지 않는다** (2026-09-24 노트북: 한글 양식이 글자 0개인데 「만들었습니다」).
    #   읽을 수 있는 블록·표·글이 하나도 없으면 여기서 멈춘다 — 모델이 다시 보내게 한다.
    # ★ 못 그리는 모양의 블록은 풀어 쓴다 — 그러고도 **그릴 글이 없으면** 성공이라 하지 않는다 (2026-10-12 밤 · `_unpack_sections`).
    #   PPT 는 제 칸(title · bullets)이 따로 있어 건드리지 않는다.
    if fmt in {"docx", "hwpx", "md", "txt"}:
        blocks = _unpack_sections(blocks)
        if not _draws_text(blocks, rows, text) and not payload.get("sheets"):
            raise ValueError(
                "document_empty — 문서에 쓸 글을 읽지 못했습니다(빈 파일은 만들지 않았습니다). 블록은 이런 꼴로 주세요: "
                "[{\"type\":\"heading\",\"level\":1,\"text\":\"제목\"},{\"type\":\"paragraph\",\"text\":\"본문 한 문단\"},"
                "{\"type\":\"table\",\"rows\":[[\"항목\",\"내용\"],[\"날짜\",\"\"]]}] — 또는 내용 전체를 text 에 마크다운으로 넣으세요."
            )
    if fmt in {"docx", "hwpx", "pptx", "md", "txt"} and not _has_content(blocks, rows, text) and not payload.get("sheets") and not payload.get("slides"):
        raise ValueError(
            "document_empty — 넣을 내용이 없습니다. blocks 는 JSON 문자열이 아니라 **목록**으로 주세요"
            " 예: [{\"type\":\"heading\",\"level\":1,\"text\":\"제목\"},{\"type\":\"table\",\"rows\":[[\"항목\",\"내용\"],[\"날짜\",\"\"]]}]"
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "xlsx":
        # ★ 블록으로 와도 받는다. 형식마다 다른 모양을 외우게 하면 언젠가 틀린다.
        if not rows and not payload.get("sheets"):
            rows = rows_from_blocks(blocks)
        raw_blocks = payload.get("blocks")
        if not rows and not payload.get("sheets") and isinstance(raw_blocks, str) and '"table"' in raw_blocks.replace("'", '"'):
            # ★ 표를 **넣었는데** 「표가 있어야 합니다」라고 하면 모델은 같은 것을 또 보낸다 (2026-10-01 AWS 9B, 5번 연속).
            #   blocks 를 JSON 글자열로 보냈고 그 안의 표 블록만 깨져 못 읽었다 — 무엇이 잘못됐고 어떻게 고치는지를 말한다.
            raise ValueError(
                "blocks_table_unreadable — blocks 를 JSON 글자열로 보냈는데 그 안의 표(table) 블록이 깨져 읽히지 않았습니다"
                f"(못 읽은 블록 {lost_blocks}개 — 따옴표·괄호를 확인하세요). blocks 는 글자열이 아니라 **목록**으로 보내거나, "
                "표는 rows 에 [[\"제목\",\"판매가\"],[\"책1\",\"18,000원\"]] 같은 목록으로 따로 넣으세요."
            )
        if not rows and not payload.get("sheets"):
            raise ValueError(
                "rows_or_sheets_required — 엑셀은 표가 있어야 합니다. rows(리스트의 "
                "리스트)나 table 블록을 주세요."
            )
        shape = _write_xlsx(target, rows, payload.get("sheets"))
    elif fmt == "docx":
        shape = _write_docx(target, blocks, rows, text)
    elif fmt == "pptx":
        shape = _write_pptx(target, blocks, text)
    elif fmt == "hwpx":
        shape = _write_hwpx(target, blocks, rows, text)
    elif fmt == "csv":
        if not rows:
            rows = rows_from_blocks(blocks)
        if not rows:
            raise ValueError(
                "rows_required — csv 는 표가 있어야 합니다. rows 나 table 블록을 주세요."
            )
        # BOM 을 붙인다 — 안 붙이면 엑셀이 한글을 깨서 연다.
        with target.open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerows(rows)
        shape = {"rows": len(rows)}
    elif fmt == "md":
        shape = _write_markdown(target, blocks, rows, text)
    else:
        # 진짜 평문(txt)만 여기로 온다. 마크다운이 아니므로 파이프 표를 쓸 이유가 없다.
        body = text or "\n".join("\t".join(row) for row in rows)
        if not body.strip() and isinstance(blocks, list) and blocks:
            # 블록만 온 평문 — 예전에는 블록을 통째로 버려 빈 파일이 됐다(2026-10-12). 마크다운 쓰기가 그린 글을 그대로 쓴다.
            shape = _write_markdown(target, blocks, rows, text)
        else:
            target.write_text(body, encoding="utf-8")
            shape = {"chars": len(body)}
    # ★ 두 칸이 모든 줄에서 같은 값이면 **짚어 준다** (2026-10-14). 막지 않는다.
    #   payload 의 rows 와, blocks 안의 table 블록(rows_from_blocks) 둘 다를 본다.
    twin_notes: list[str] = []
    shape_notes: list[str] = []
    for candidate in (rows, rows_from_blocks(blocks)):
        if candidate:
            twin_notes.extend(twin_column_notes(candidate))
            shape_notes.extend(column_shape_notes(candidate))
    twin_notes = list(dict.fromkeys(twin_notes))
    shape_notes = list(dict.fromkeys(shape_notes))
    return {
        "format": fmt,
        "bytes": target.stat().st_size,
        # ★ 만든 것을 **바로 보여 준다** (2026-09-01).
        #
        # hwpx·xlsx·docx 는 브라우저에서 못 그린다. 그래서 만든 순간 그 내용을
        # 글로 한 번 요약해 내보낸다 — 사람이 한글을 열지 않고도 "제대로 들어갔나"를
        # 확인할 수 있어야 한다. 파일만 던져 놓고 "만들었습니다"는 주장일 뿐이다.
        "preview": _preview_of(rows, blocks, text),
        # ★ **만든 직후에** 꼴을 짚어 준다. 끝나고 채점하면 이미 늦다.
        #   막지 않는다 — 한 줄 메모처럼 제목이 없어도 되는 문서가 있다.
        **({"shape_notes": notes} if (notes := _shape_notes(fmt, blocks, rows, text)) else {}),
        # 비운 칸이 있으면 **말한다.** 조용히 바꾸지 않는다.
        **({"blanked_unverified_cells": blanked} if blanked else {}),
        # ★ 못 읽고 버린 블록이 있으면 **말한다**(2026-09-28 B1: 표 둘을 말없이 잃었다). 모델이 그 블록을 고쳐 다시 보내게 한다.
        **({"unreadable_blocks": (
            f"블록 {lost_blocks}개를 JSON 으로 못 읽어 문서에 넣지 못했습니다 — 빠진 표·문단을 고쳐서 blocks 를 **목록**으로 다시 보내세요."
        )} if lost_blocks else {}),
        # ★ 두 칸이 모든 줄에서 같은 값이면 **말한다** (2026-10-14). 막지 않는다.
        **({"twin_columns": twin_notes} if twin_notes else {}),
        # ★ 머리줄이 값의 꼴을 정하는 칸에서 값이 그 꼴과 안 맞으면 **알린다** (2026-10-14). 막지 않는다.
        **({"column_shape": shape_notes} if shape_notes else {}),
        **shape,
    }


#: 미리보기에 보여 줄 글자 수. 사람이 「제대로 들어갔나」만 보면 되므로 짧게.
PREVIEW_CHARS = 700


def _preview_of(rows: list[list[str]], blocks: Any, text: str) -> str:
    """무엇을 썼는지 사람 말로. 파일을 안 열고도 확인할 수 있게."""
    lines: list[str] = []
    for block in blocks if isinstance(blocks, list) else []:
        if isinstance(block, str):
            lines.append(block)
        elif isinstance(block, dict):
            kind = str(block.get("type") or "").lower()
            body = str(block.get("text") or block.get("title") or "")
            if kind in {"heading", "h1", "h2", "h3"}:
                lines.append(f"# {body}")
            elif kind == "table":
                grid = _table_grid(block)
                lines += [" | ".join(row) for row in grid[:6]]
            else:
                # ★ 슬라이드는 **제목과 내용을 같이** 보여야 한다 (2026-09-01).
                #
                #   예전엔 `body or bullets` 였다. 제목이 있으면 `body` 가 참이라
                #   `or` 가 영영 안 돌아 **불릿이 통째로 빠졌다** — PPT 미리보기가
                #   제목만 나열하고 끝났다. 미리보기의 존재 이유는 열지 않고
                #   속을 확인하는 것인데, 속이 빠져 있었다.
                bullets = [str(x) for x in (block.get("bullets") or []) if str(x).strip()]
                if body:
                    lines.append(body)
                if bullets:
                    lines += [f"  · {item}" for item in bullets[:6]]
    if not lines:
        # ★ **글로 온 것은 빈 줄째 보여 준다** (2026-09-21 실전).
        #
        #   예전엔 빈 줄을 전부 걷어 냈다. 마크다운에서 표는 **앞에 빈 줄이 있어야**
        #   표로 서기 때문에, 미리보기만 보면 제목·문단·표가 한 덩어리로 뭉쳐 보인다.
        #   모델은 그걸 보고 「표가 안 섰다」고 판단해 같은 문서를 여섯 번 다시 썼다.
        #   파일은 처음부터 멀쩡했다 — 뭉갠 것은 미리보기였다.
        if not rows and text.strip():
            return text[:PREVIEW_CHARS]
        lines = [" | ".join(row) for row in rows[:8]] or text.splitlines()[:12]
    return "\n".join(line for line in lines if line)[:PREVIEW_CHARS]


def edit_spreadsheet(target: Path, edits: Any, sheet_name: str = "") -> dict[str, Any]:
    """기존 엑셀의 **셀만** 고친다. 통째로 다시 쓰지 않는다.

    다시 쓰면 서식·수식·다른 시트가 날아간다. 사람이 쓰던 파일에 자비스가 몇 칸
    채우는 것이 실제 업무의 모양이므로, 남은 것을 건드리지 않는 쪽이 맞다.

    `edits` 는 `[{"cell": "B3", "value": "..."}]` 또는 `{"B3": "..."}` 둘 다 받는다.
    """
    from openpyxl import load_workbook

    if not target.exists():
        raise FileNotFoundError("path_not_found")
    book = load_workbook(target)
    # ★ 시트가 여럿인데 어느 시트인지 안 댔거나 없는 이름을 댔으면 **고치지 않고 묻는다** (2026-10-04 레딧 조사 판 aa741c81).
    #   「글 목록」 시트의 줄을 고치려던 편집이 시트 이름 없이 와서 조용히 첫 시트(「공통점」)에 들어갔다 — 틀린 자리에
    #   조용히 쓰는 것이 거절보다 나쁘다. 시트가 하나면 예전 그대로 그 시트다.
    wanted = str(sheet_name or "").strip()
    if wanted and wanted not in book.sheetnames:
        close = [name for name in book.sheetnames if name.strip().casefold() == wanted.casefold()]
        if len(close) == 1:
            wanted = close[0]
        else:
            raise ValueError(
                f"sheet_not_found — 「{wanted}」 시트가 없다. 있는 시트: " + ", ".join(book.sheetnames)
                + ". `sheet` 에 이 이름 중 하나를 그대로 넣어 다시 불러라."
            )
    if not wanted and len(book.sheetnames) > 1:
        raise ValueError(
            "sheet_required — 이 파일은 시트가 여러 개다: " + ", ".join(book.sheetnames)
            + ". 어느 시트를 고칠지 `sheet` 에 이름을 넣어 다시 불러라(안 넣으면 엉뚱한 시트를 고치게 된다)."
        )
    sheet = book[wanted] if wanted else book.active
    pairs: list[tuple[str, Any]] = []
    if isinstance(edits, dict):
        pairs = [(str(k), v) for k, v in edits.items()]
    elif isinstance(edits, list):
        for item in edits:
            if isinstance(item, dict) and item.get("cell"):
                pairs.append((str(item["cell"]), item.get("value")))
    if not pairs:
        raise ValueError("edits_required")
    changed: list[dict[str, Any]] = []
    for cell, value in pairs:
        reference = cell.strip().upper()
        before = sheet[reference].value
        sheet[reference] = value
        changed.append({"cell": reference, "before": str(before)[:120] if before is not None else None})
    book.save(target)
    return {
        "sheet": sheet.title,
        "changed": len(changed),
        "cells": changed[:40],
        "bytes": target.stat().st_size,
    }


#: 제자리 수정이 되는 형식. 나머지는 통째로 다시 쓰는 수밖에 없다.
EDITABLE = ("docx", "hwpx", "pptx")


def edit_document(target: Path, edits: Any) -> dict[str, Any]:
    """기존 워드·한글 문서를 **제자리에서** 고친다. 통째로 다시 쓰지 않는다.

    ★ 왜 만들었나 (2026-09-01). 엑셀만 셀 단위 수정이 있었고(`edit_spreadsheet`),
    워드·한글은 **새로 만들기밖에** 없었다. 그래서 「받은 파일에서 3번 문단만
    고쳐줘」가 통째로 다시 쓰기가 됐고 — 서식·표·머리말·글꼴이 전부 날아갔다.
    사람이 쓰던 파일에 몇 줄 고치는 것이 실제 사무의 모양이다.

    `edits` 는 목록이고, 항목마다 넷 중 하나다:

        {"find": "지출 서류 검토", "replace": "증빙 적정성 검토"}   글 바꾸기
        {"paragraph": 3, "text": "새 내용"}                       그 문단만 갈아끼움
        {"after": 3, "insert": "새 문단"}                          뒤에 끼워 넣기
        {"delete": 7}                                             그 문단 지우기

    문단 번호는 **0부터** 세고, `local_read_document` 가 보여 준 순서와 같다.

    되돌리기는 호출부(`local_computer._backup`)가 파일째로 잡는다.
    """
    if not target.exists():
        raise FileNotFoundError("path_not_found")
    if not isinstance(edits, list) or not edits:
        raise ValueError("edits_required")
    suffix = target.suffix.lower().lstrip(".")
    if suffix == "docx":
        return _edit_docx(target, edits)
    if suffix == "hwpx":
        return _edit_hwpx(target, edits)
    if suffix == "pptx":
        return _edit_pptx(target, edits)
    raise ValueError(f"unsupported_edit_format:{suffix or '(확장자 없음)'}")


def _set_paragraph_text(paragraph: Any, text: str) -> bool:
    """문단의 **글만** 갈아끼운다. 서식은 첫 run 의 것을 남긴다.

    돌려주는 값은 「문단 안 부분서식이 살았는가」다. 한 문단이 여러 run 으로
    쪼개져 있으면(중간만 굵게 등) 그 구분은 사라진다 — 그 사실을 **말해 준다.**
    잘림이든 서식 손실이든 침묵으로 오면 안 된다.
    """
    runs = list(paragraph.runs)
    if not runs:
        paragraph.text = text
        return True
    runs[0].text = text
    for extra in runs[1:]:
        extra.text = ""
    return len(runs) == 1


def _edit_docx(target: Path, edits: list[Any]) -> dict[str, Any]:
    from docx import Document

    if any(isinstance(e, dict) and (e.get("footnote") or e.get("각주")) for e in edits):
        raise ValueError(
            "docx_footnotes_unsupported — 워드(docx)에는 각주를 넣을 수 없습니다."
            " 한글(hwpx) 문서로 만들면 진짜 각주가 됩니다."
        )

    document = Document(str(target))
    paragraphs = document.paragraphs
    changed: list[dict[str, Any]] = []
    formatting_lost = 0

    for edit in edits:
        if not isinstance(edit, dict):
            continue
        if edit.get("find"):
            find = str(edit["find"])
            replace = str(edit.get("replace") or "")
            hits = 0
            for index, paragraph in enumerate(document.paragraphs):
                if find not in paragraph.text:
                    continue
                # run 하나 안에 다 들어 있으면 그 run 만 고친다 — 부분서식이 산다.
                inside_one_run = False
                for run in paragraph.runs:
                    if find in run.text:
                        run.text = run.text.replace(find, replace)
                        inside_one_run = True
                        break
                if not inside_one_run:
                    if not _set_paragraph_text(paragraph, paragraph.text.replace(find, replace)):
                        formatting_lost += 1
                hits += 1
                changed.append({"paragraph": index, "how": "찾아 바꾸기", "find": find[:60]})
            if hits == 0:
                # 못 찾았는데 성공으로 돌려주면 "고쳤다"가 거짓이 된다.
                changed.append({"how": "찾아 바꾸기", "find": find[:60], "hits": 0, "note": "못 찾음"})
        elif "paragraph" in edit:
            index = int(edit["paragraph"])
            if not 0 <= index < len(paragraphs):
                raise ValueError(f"paragraph_out_of_range:{index}")
            before = paragraphs[index].text
            if not _set_paragraph_text(paragraphs[index], str(edit.get("text") or "")):
                formatting_lost += 1
            changed.append({"paragraph": index, "how": "문단 교체", "before": before[:80]})
        elif "after" in edit:
            index = int(edit["after"])
            if not 0 <= index < len(paragraphs):
                raise ValueError(f"paragraph_out_of_range:{index}")
            anchor = paragraphs[index]
            # 맨 뒤에 만든 다음 제자리로 **옮긴다.** lxml 의 `addnext` 는 복사가
            # 아니라 이동이라, 이 두 줄이면 끝난다.
            new = document.add_paragraph(str(edit.get("insert") or ""))
            anchor._p.addnext(new._p)
            paragraphs = document.paragraphs
            changed.append({"paragraph": index, "how": "뒤에 끼움"})
        elif "delete" in edit:
            index = int(edit["delete"])
            if not 0 <= index < len(paragraphs):
                raise ValueError(f"paragraph_out_of_range:{index}")
            element = paragraphs[index]._p
            before = paragraphs[index].text
            element.getparent().remove(element)
            changed.append({"paragraph": index, "how": "문단 삭제", "before": before[:80]})
            paragraphs = document.paragraphs

    document.save(str(target))
    result: dict[str, Any] = {
        "format": "docx",
        "changed": len([item for item in changed if item.get("hits") != 0]),
        "edits": changed[:40],
        "bytes": target.stat().st_size,
        "preview": preview_of_file(target),
    }
    if formatting_lost:
        # 무엇을 잃었는지 **말한다.** 조용히 잃으면 다음에 열어 보고서야 안다.
        result["formatting_lost_paragraphs"] = formatting_lost
        result["note"] = (
            f"문단 {formatting_lost}개는 안쪽 부분서식(굵게·색 등)이 한 벌로 합쳐졌습니다."
            " 문단 서식·표·머리말은 그대로입니다."
        )
    return result


def _edit_hwpx(target: Path, edits: list[Any]) -> dict[str, Any]:
    """한글도 같은 규칙으로 고친다.

    `python-hwpx` 가 `replace_text_in_runs` 를 이미 갖고 있다 — 한글이 안 깔려
    있어도 된다. HWPX 는 ZIP+XML(OWPML) 이라 파일만 있으면 되는 형식이다.
    """
    from hwpx.document import HwpxDocument

    document = HwpxDocument.open(str(target))
    changed: list[dict[str, Any]] = []
    notes = 0

    for edit in edits:
        if not isinstance(edit, dict):
            continue
        if edit.get("find"):
            find = str(edit["find"])
            replace = str(edit.get("replace") or "")
            # python-hwpx 6.0 에서 `replace_text_in_runs` 가 `doc.text.replace` 로
            # 옮겨 갔고 7.0 에서 사라진다. 새 자리를 먼저 쓰고, 옛 판에서는 옛 자리로
            # 떨어진다 — 라이브러리 판이 갈려도 안 죽는다.
            surface = getattr(document, "text", None)
            if surface is not None and hasattr(surface, "replace"):
                hits = surface.replace(find, replace)
            else:  # pragma: no cover - python-hwpx 6.0 미만
                hits = document.replace_text_in_runs(find, replace)
            changed.append({"how": "찾아 바꾸기", "find": find[:60], "hits": int(hits)})
        elif edit.get("footnote") or edit.get("각주"):
            # 있는 문서에 **진짜 각주**를 단다. 「고칠 만한 곳마다 각주로」가
            # 본문 안 `[수정 제안: …]` 로 나오던 것을 여기서 끝낸다.
            #
            # ⚠ 이 갈래는 `paragraph` 보다 **먼저** 와야 한다.
            #   `{"paragraph":0,"footnote":"…"}` 는 「0번 문단에 각주」이지
            #   「0번 문단을 빈 글로 교체」가 아니다 — 순서를 뒤로 뒀다가 실제로
            #   본문이 지워졌다.
            wanted = _footnote_texts(edit.get("footnote") or edit.get("각주"))
            paragraphs = document.paragraphs
            index = int(edit.get("paragraph", edit.get("at", -1)))
            anchor = paragraphs[index] if 0 <= index < len(paragraphs) else None
            if index >= 0 and anchor is None:
                raise ValueError(f"paragraph_out_of_range:{index}")
            added = sum(_add_footnote(document, anchor, one) for one in wanted)
            notes += added
            changed.append({
                "paragraph": index if anchor is not None else None,
                "how": f"각주 {added}개 달기" if added else "각주 못 담",
                "text": (wanted[0] if wanted else "")[:60],
                **({} if added else {"hits": 0}),
            })
        elif "paragraph" in edit:
            index = int(edit["paragraph"])
            paragraphs = document.paragraphs
            if not 0 <= index < len(paragraphs):
                raise ValueError(f"paragraph_out_of_range:{index}")
            before = str(getattr(paragraphs[index], "text", "") or "")
            paragraphs[index].text = str(edit.get("text") or "")
            changed.append({"paragraph": index, "how": "문단 교체", "before": before[:80]})
        elif "after" in edit:
            # 한글 쪽은 지정 위치 삽입 API 가 없다. **맨 뒤에 붙이고 그렇게 말한다** —
            # 자리를 지어내는 것보다 낫다.
            document.add_paragraph(str(edit.get("insert") or ""))
            changed.append({"how": "문단 추가(맨 뒤)", "note": "한글은 중간 삽입이 안 돼 끝에 붙였습니다"})
        elif "delete" in edit:
            index = int(edit["delete"])
            paragraphs = document.paragraphs
            if not 0 <= index < len(paragraphs):
                raise ValueError(f"paragraph_out_of_range:{index}")
            before = str(getattr(paragraphs[index], "text", "") or "")
            document.remove_paragraph(paragraphs[index])
            changed.append({"paragraph": index, "how": "문단 삭제", "before": before[:80]})

    document.save_to_path(str(target))
    return {
        "format": "hwpx",
        "footnotes": notes,
        "changed": len([item for item in changed if item.get("hits") != 0]),
        "edits": changed[:40],
        "bytes": target.stat().st_size,
        "preview": preview_of_file(target),
    }


def _slide_body(slide: Any) -> Any:
    """그 슬라이드의 **본문 틀**. 없으면 None.

    제목(idx 0)이 아니면서 글을 담을 수 있는 첫 자리를 쓴다. 레이아웃마다
    자리 번호가 달라서 `placeholders[1]` 을 그냥 집으면 어떤 장에서는 터진다.
    """
    for shape in slide.placeholders:
        if shape.placeholder_format.idx != 0 and shape.has_text_frame:
            return shape.text_frame
    for shape in slide.shapes:
        if shape.has_text_frame and shape != slide.shapes.title:
            return shape.text_frame
    return None


def _set_bullets(frame: Any, lines: list[str]) -> None:
    """본문 틀의 줄을 갈아끼운다. 틀 자체(글꼴·자리)는 그대로 둔다."""
    frame.clear()
    for index, line in enumerate(lines or [""]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = str(line)[:400]


def _edit_pptx(target: Path, edits: list[Any]) -> dict[str, Any]:
    """발표자료를 **제자리에서** 고친다.

    ★ 2026-09-01 실측에서 이 칸만 비어 있었다. docx·hwpx 는 제자리 수정이 되는데
    pptx 는 **새로 만드는 수밖에** 없어서, 「이 PPT 3번 슬라이드만 고쳐줘」가
    통째로 다시 쓰기가 됐다 — 디자인·레이아웃·다른 장이 전부 날아간다.

    `edits` 항목은 다섯 중 하나다(슬라이드 번호는 **0부터**):

        {"find": "옛 글", "replace": "새 글"}                모든 장에서 글 바꾸기
        {"slide": 2, "title": "새 제목"}                     그 장 제목만
        {"slide": 2, "bullets": ["가", "나"]}                그 장 본문만
        {"after": 2, "insert": {"title": ..., "bullets": []}}  뒤에 새 장
        {"delete": 3}                                        그 장 지우기

    python-pptx 에는 장을 지우거나 옮기는 공개 API 가 없어 `sldIdLst` 를 직접
    다룬다. 실측으로 확인한 방식이다(삭제·이동 둘 다).
    """
    from pptx import Presentation

    deck = Presentation(str(target))
    changed: list[dict[str, Any]] = []
    formatting_lost = 0

    def slide_at(index: int) -> Any:
        if not 0 <= index < len(deck.slides):
            raise ValueError(f"slide_out_of_range:{index}")
        return deck.slides[index]

    for edit in edits:
        if not isinstance(edit, dict):
            continue
        if edit.get("find"):
            find = str(edit["find"])
            replace = str(edit.get("replace") or "")
            hits = 0
            for index, slide in enumerate(deck.slides):
                for shape in slide.shapes:
                    if not shape.has_text_frame:
                        continue
                    for paragraph in shape.text_frame.paragraphs:
                        if find not in paragraph.text:
                            continue
                        inside_one_run = False
                        for run in paragraph.runs:
                            if find in run.text:
                                run.text = run.text.replace(find, replace)
                                inside_one_run = True
                                break
                        if not inside_one_run:
                            replaced = paragraph.text.replace(find, replace)
                            if not _set_paragraph_text(paragraph, replaced):
                                formatting_lost += 1
                        hits += 1
                        changed.append({"slide": index, "how": "찾아 바꾸기", "find": find[:60]})
            if hits == 0:
                # 못 찾았는데 성공으로 돌려주면 「고쳤다」가 거짓이 된다.
                changed.append({"how": "찾아 바꾸기", "find": find[:60], "hits": 0, "note": "못 찾음"})
        elif "slide" in edit:
            index = int(edit["slide"])
            slide = slide_at(index)
            if edit.get("title") is not None:
                if slide.shapes.title is None:
                    raise ValueError(f"slide_has_no_title:{index}")
                before = slide.shapes.title.text
                first = slide.shapes.title.text_frame.paragraphs[0]
                if not _set_paragraph_text(first, str(edit["title"])):
                    formatting_lost += 1
                changed.append({"slide": index, "how": "제목 교체", "before": before[:60]})
            if edit.get("bullets") is not None:
                frame = _slide_body(slide)
                if frame is None:
                    raise ValueError(f"slide_has_no_body:{index}")
                before = frame.text
                _set_bullets(frame, [str(x) for x in (edit.get("bullets") or [])])
                changed.append({"slide": index, "how": "본문 교체", "before": before[:60]})
        elif "after" in edit:
            index = int(edit["after"])
            slide_at(index)
            item = edit.get("insert")
            item = item if isinstance(item, dict) else {"title": str(item or ""), "bullets": []}
            new = deck.slides.add_slide(deck.slide_layouts[1])
            if new.shapes.title is not None:
                new.shapes.title.text = str(item.get("title") or "")[:200]
            frame = _slide_body(new)
            if frame is not None:
                _set_bullets(frame, [str(x) for x in (item.get("bullets") or [])])
            # 맨 뒤에 생긴 것을 제자리로 **옮긴다.** 공개 API 가 없어 목록을 직접 다룬다.
            order = deck.slides._sldIdLst
            entries = list(order)
            order.remove(entries[-1])
            order.insert(index + 1, entries[-1])
            changed.append({"slide": index, "how": "뒤에 끼움"})
        elif "delete" in edit:
            index = int(edit["delete"])
            slide = slide_at(index)
            before = slide.shapes.title.text if slide.shapes.title is not None else ""
            order = deck.slides._sldIdLst
            order.remove(list(order)[index])
            changed.append({"slide": index, "how": "슬라이드 삭제", "before": before[:60]})

    deck.save(str(target))
    result: dict[str, Any] = {
        "format": "pptx",
        "changed": len([item for item in changed if item.get("hits") != 0]),
        "edits": changed[:40],
        "slides": len(deck.slides),
        "bytes": target.stat().st_size,
        "preview": preview_of_file(target),
    }
    if formatting_lost:
        result["formatting_lost_paragraphs"] = formatting_lost
        result["note"] = (
            f"문단 {formatting_lost}개는 안쪽 부분서식(굵게·색 등)이 한 벌로 합쳐졌습니다."
            " 레이아웃·디자인·다른 장은 그대로입니다."
        )
    return result
