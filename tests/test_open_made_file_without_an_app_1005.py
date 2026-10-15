"""만든 파일을 띄울 때 — 여는 프로그램이 없는 PC 에서 오류 창이 뜨지 않는다 (2026-10-05 AWS 영어 윈도우 새 PC).

과제(arXiv 비교표)가 2/2 로 끝나며 `comparison_table_arxiv_cscl_papers.md` 를 열자 윈도우가
「Windows can't open this type of file (.md)」 창을 띄웠다. 새 윈도우에는 `.md` 를 여는 프로그램이 없다.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from alture_jarvis import file_open


def _open(path: Path, app: str) -> tuple[str, list[str], list[list[str]]]:
    started: list[str] = []
    spawned: list[list[str]] = []
    how = file_open.open_file(path, associated=lambda suffix: app, startfile=started.append,
                              popen=lambda args, **kwargs: spawned.append(list(args)))
    return how, started, spawned


def test_a_file_with_an_app_opens_in_that_app(tmp_path: Path) -> None:
    made = tmp_path / "report.docx"
    made.write_bytes(b"PK")

    assert _open(made, r"C:\Program Files\Word\WINWORD.EXE") == ("app", [str(made)], [])


def test_a_markdown_file_without_an_app_opens_in_notepad(tmp_path: Path) -> None:
    made = tmp_path / "comparison_table_arxiv_cscl_papers.md"
    made.write_text("# table", encoding="utf-8")

    how, started, spawned = _open(made, "")

    assert how == "notepad" and started == [], "연결이 없는데 그대로 열면 윈도우가 오류 창을 띄운다"
    assert spawned == [["notepad.exe", str(made)]]


def test_a_file_nothing_can_read_is_pointed_at_in_explorer(tmp_path: Path) -> None:
    made = tmp_path / "plan.hwpx"
    made.write_bytes(b"PK")

    how, started, spawned = _open(made, "")

    assert how == "revealed" and started == []
    assert spawned == [["explorer.exe", f"/select,{made}"]]


def test_a_folder_is_opened_as_before(tmp_path: Path) -> None:
    assert _open(tmp_path, "") == ("app", [str(tmp_path)], [])


@pytest.mark.skipif(os.name != "nt", reason="윈도우의 연결 프로그램을 묻는다")
def test_windows_knows_no_app_for_a_made_up_extension() -> None:
    assert file_open.associated_app(".sonjari-nothing-opens-this") == ""
    assert file_open.associated_app(".txt"), "메모장은 모든 윈도우에 있다"


def test_the_three_places_that_open_a_file_use_the_one_helper() -> None:
    import inspect

    from alture_jarvis import local_computer, runtime

    for module in (local_computer, runtime):
        source = inspect.getsource(module)
        assert "open_file(" in source
        assert "os.startfile(str(external_path(path)))" not in source
