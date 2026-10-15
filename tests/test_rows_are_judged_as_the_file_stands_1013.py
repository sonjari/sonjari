"""줄은 **파일이 지금 서 있는 대로** 본다 — 쓴 뒤에 고친 칸은 고친 값으로 (2026-10-13 영상 촬영 판).

    14  local_write_document     가격 칸 「139,700원 (최대할인가 138,310원)」          ← 처음 쓴 값
    15  local_edit_spreadsheet   D3 → 「139,700원」                                     ← 모델이 바로 고침
        (끝) 답 · 최종 엑셀 모두 「139,700원」

표는 세 줄 다 맞았는데 답 끝에 「줄의 값이 그 페이지와 다릅니다: 「11번가」 138,310원」이 붙었다. 검사가 줄을 모을 때 쓰기 걸음의
인자만 보고, 그 뒤에 그 파일의 칸을 고친 걸음은 보지 않았다 — **이미 없는 줄**을 판정한 것이다.

같은 자리에 09-28 의 규칙이 있다: 「같은 파일을 여러 번 쓰면 마지막 쓰기만 본다」. 그 규칙의 나머지 반쪽이다 — 다시 쓰는 대신
칸만 고쳐도 파일은 바뀐다.

표본의 가게 · 값 · 주소는 지어낸 것이다.
"""
from __future__ import annotations

import copy

from alture_jarvis.agent import BrowserAgent

HEAD = ["가게", "상품 이름", "판매 가격", "배송비", "읽은 페이지 주소"]
PAGE_A = "https://shop-a.example/products/1001"
PAGE_B = "https://shop-b.example/products/2002"
FILE = r"C:\Users\someone\Documents\Sonjari\가상_마우스_가격.xlsx"


def _write(rows: list[list[str]], *, path: str = "가상_마우스_가격.xlsx", made: str = FILE, **shape: object) -> dict[str, object]:
    arguments: dict[str, object] = {"format": "xlsx", "path": path, **(shape or {"rows": rows})}
    return {"tool": "local_write_document", "ok": True, "arguments": arguments,
            "evidence": {"action": "local_write_document", "output_path": made, "sheets": ["Sheet1"]}}


def _edit(cell: str, value: str, *, path: str = FILE, ok: bool = True, sheet: str = "") -> dict[str, object]:
    return {"tool": "local_edit_spreadsheet", "ok": ok,
            "arguments": {"path": path, "edits": [{"cell": cell, "value": value}], **({"sheet": sheet} if sheet else {})},
            "evidence": {"action": "local_edit_spreadsheet", "output_path": path, "sheet": sheet or "Sheet1", "changed": 1}}


ROWS = [HEAD,
        ["가게 A", "가상 마우스 X1", "129,000원", "무료", PAGE_A],
        ["가게 B", "가상 마우스 X1", "139,700원 (최대할인가 138,310원)", "무료", PAGE_B]]


def _price_of(rows: list[list[str]], shop: str) -> list[str]:
    return [cells[2] for cells in rows if cells and cells[0] == shop]


def test_a_cell_fixed_after_the_write_is_judged_as_fixed() -> None:
    steps = [_write(copy.deepcopy(ROWS)), _edit("C3", "139,700원")]

    rows = BrowserAgent._rows_with_urls("", steps)

    assert _price_of(rows, "가게 B") == ["139,700원"], "이미 고친 칸의 옛 값을 판정하면 맞는 표에 경고가 붙는다"
    assert _price_of(rows, "가게 A") == ["129,000원"]


def test_the_steps_themselves_are_left_as_they_were() -> None:
    """걸음 기록은 일어난 일의 기록이다 — 검사가 고쳐 쓰지 않는다."""
    steps = [_write(copy.deepcopy(ROWS)), _edit("C3", "139,700원")]

    BrowserAgent._rows_with_urls("", steps)

    assert steps[0]["arguments"]["rows"][2][2] == "139,700원 (최대할인가 138,310원)"  # type: ignore[index]


def test_a_fix_that_made_it_wrong_is_what_gets_judged() -> None:
    """양방향 — 고쳐서 틀려진 값도 고친 값으로 본다."""
    steps = [_write(copy.deepcopy(ROWS)), _edit("C2", "99,000원")]

    assert _price_of(BrowserAgent._rows_with_urls("", steps), "가게 A") == ["99,000원"]


def test_an_edit_that_failed_or_touched_another_file_changes_nothing() -> None:
    for step in (_edit("C3", "139,700원", ok=False), _edit("C3", "139,700원", path=r"C:\Users\someone\Documents\Sonjari\다른_파일.xlsx")):
        rows = BrowserAgent._rows_with_urls("", [_write(copy.deepcopy(ROWS)), step])
        assert _price_of(rows, "가게 B") == ["139,700원 (최대할인가 138,310원)"]


def test_an_edit_made_before_the_file_was_written_again_does_not_reach_the_new_write() -> None:
    again = copy.deepcopy(ROWS)
    again[2][2] = "141,000원"
    steps = [_write(copy.deepcopy(ROWS)), _edit("C3", "139,700원"), _write(again)]

    assert _price_of(BrowserAgent._rows_with_urls("", steps), "가게 B") == ["141,000원"], "마지막 쓰기가 그 파일이다"


def test_a_sheet_keyed_write_is_fixed_on_the_named_sheet() -> None:
    steps = [_write([], sheets={"가격": copy.deepcopy(ROWS), "메모": [["비고"], ["가상 메모 https://shop-a.example/notes/1"]]}),
             _edit("C3", "139,700원", sheet="가격")]

    assert _price_of(BrowserAgent._rows_with_urls("", steps), "가게 B") == ["139,700원"]


def test_an_edit_the_checker_cannot_place_leaves_the_write_alone() -> None:
    """모르면 안 고친다 — 칸 이름이 이상하거나 표 밖이면 쓴 그대로 본다(죽지 않는다)."""
    for cell in ("Z99", "가3", "", "C0"):
        rows = BrowserAgent._rows_with_urls("", [_write(copy.deepcopy(ROWS)), _edit(cell, "139,700원")])
        assert _price_of(rows, "가게 B") == ["139,700원 (최대할인가 138,310원)"], cell
