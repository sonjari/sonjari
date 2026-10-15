"""파일을 쓴 **뒤에** 새로 읽은 페이지가 있으면 골라낸다 (2026-10-14).

어머님 부탁(쿠팡 캣타워 · 부산 노트북 4B)에서 8번째 걸음에 엑셀을 쓰고, 9 · 10번째 걸음에 셋째 상품을 열어
본문을 읽은 뒤 **다시 쓰지 않고** 끝났다. 셋째 줄은 목록에서 본 값으로 남았다. 끝내기 전에 「쓴 뒤에 새로 읽은 것」을
알면 한 번 더 쓰게 돌려보낼 수 있다. 이 시험은 그 「골라내기」만 정한다(돌려보내기는 따로 붙인다).

지키는 약속 — `alture_jarvis.write_order.reads_after_last_write(steps)`:
- `steps` 는 걸음 기록 목록. 걸음 하나는 dict: `tool`(이름) · `ok`(성공 여부) · `arguments`(dict) · `evidence`(dict).
- 성공한(`ok` 가 참) 걸음만 센다.
- 쓰기 도구: `local_write_document` · `local_write_file` · `local_edit_document` · `local_edit_spreadsheet`.
  읽기 도구: `browser_extract` · `browser_read`. 읽은 주소는 `evidence["url"]`.
- 성공한 쓰기가 없으면 `None`. 마지막 성공한 쓰기 뒤에 「새로 읽은 주소」가 없으면 `None`.
- 「새로 읽은 주소」 = 마지막 쓰기 **뒤**에 성공한 읽기의 주소 가운데, 그 쓰기 **앞**에 성공한 읽기로 이미 읽은 적이 없는 것.
  주소는 `#` 뒤를 떼고 견준다. 빈 주소 · `about:blank` · `file:` 로 시작하는 주소는 세지 않는다.
- 있으면 `{"path": 쓴 파일, "write_index": 그 쓰기 걸음의 목록 위치(0부터), "new_reads": [주소, ...]}` 를 돌려준다.
  `path` 는 `evidence["output_path"]` 가 있으면 그것, 없으면 `arguments["path"]`. `new_reads` 는 처음 읽은 순서 · 겹침 없음.
"""

from __future__ import annotations

from alture_jarvis.write_order import reads_after_last_write


def _read(url: str, ok: bool = True, tool: str = "browser_extract") -> dict:
    return {"tool": tool, "ok": ok, "arguments": {}, "evidence": {"url": url}}


def _write(path: str, ok: bool = True, output_path: str = "", tool: str = "local_write_document") -> dict:
    evidence = {"output_path": output_path} if output_path else {}
    return {"tool": tool, "ok": ok, "arguments": {"path": path, "format": "xlsx"}, "evidence": evidence}


def _open(url: str) -> dict:
    return {"tool": "browser_open_result", "ok": True, "arguments": {"rank": 1}, "evidence": {"url": url}}


A, B, C = "https://shop.example.test/p/1", "https://shop.example.test/p/2", "https://shop.example.test/p/3"


def test_the_cat_tower_run_is_caught() -> None:
    steps = [_open(A), _read(A), _open(B), _read(B), _write("캣타워.xlsx", output_path=r"C:\out\캣타워.xlsx"), _open(C), _read(C)]
    got = reads_after_last_write(steps)
    assert got == {"path": r"C:\out\캣타워.xlsx", "write_index": 4, "new_reads": [C]}


def test_writing_again_after_reading_clears_it() -> None:
    steps = [_read(A), _write("a.xlsx"), _read(C), _write("a.xlsx")]
    assert reads_after_last_write(steps) is None


def test_no_write_or_no_read_after_is_nothing() -> None:
    assert reads_after_last_write([]) is None
    assert reads_after_last_write([_read(A), _read(B)]) is None
    assert reads_after_last_write([_read(A), _write("a.xlsx")]) is None


def test_rereading_a_page_already_in_the_file_is_not_new() -> None:
    steps = [_read(A), _read(B), _write("a.xlsx"), _read(A + "#reviews"), _read(B, tool="browser_read")]
    assert reads_after_last_write(steps) is None


def test_failed_steps_do_not_count() -> None:
    assert reads_after_last_write([_read(A), _write("a.xlsx"), _read(C, ok=False)]) is None
    # 실패한 쓰기는 쓰기가 아니다 — 그 앞의 성공한 쓰기가 기준이다.
    steps = [_read(A), _write("first.xlsx"), _read(C), _write("second.xlsx", ok=False)]
    assert reads_after_last_write(steps) == {"path": "first.xlsx", "write_index": 1, "new_reads": [C]}


def test_blank_and_local_addresses_are_ignored() -> None:
    steps = [_read(A), _write("a.xlsx"), _read(""), _read("about:blank"), _read("file:///C:/out/a.xlsx")]
    assert reads_after_last_write(steps) is None


def test_new_reads_keep_first_order_without_repeats() -> None:
    steps = [_write("a.docx", tool="local_edit_document"), _read(C), _read(B), _read(C + "#top"), _read(B)]
    assert reads_after_last_write(steps) == {"path": "a.docx", "write_index": 0, "new_reads": [C, B]}


def test_other_write_tools_count_too() -> None:
    for tool in ("local_write_file", "local_edit_spreadsheet"):
        got = reads_after_last_write([_read(A), _write("x", tool=tool), _read(C)])
        assert got is not None and got["new_reads"] == [C]
