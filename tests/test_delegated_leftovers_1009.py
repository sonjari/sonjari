"""`prepare` 가 만든 작업 자리는 일이 끝나도 남는다 — 오래된 것만 **목록으로** 보여 준다 (2026-10-09).

지우지 않는다(치우는 것은 사람이 한다). `tmp_path` 에 폴더를 만들고 `os.utime` 으로 시각을 옮겨 돈다.
"""
from __future__ import annotations

import os
from pathlib import Path

from alture_jarvis.delegated_branch import leftovers

DAY = 86_400.0
NOW = 1_000.0


def _age_at(folder: Path, days: float) -> None:
    """`folder` 의 mtime 을 `NOW` 보다 `days` 일 전으로 옮긴다."""
    at = NOW - days * DAY
    os.utime(folder, (at, at))


def test_only_the_folders_older_than_the_limit_are_listed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    fresh = home / "fresh"
    old = home / "old"
    fresh.mkdir()
    old.mkdir()
    _age_at(fresh, 1.0)    # 1일 — 제한(7일)보다 새 것
    _age_at(old, 10.0)     # 10일 — 제한보다 오래된 것

    found = leftovers(home, clock=lambda: NOW)

    assert [item["path"] for item in found] == [str(old)], "오래된 것만 남겨야 한다"


def test_each_item_names_the_folder_and_its_age_in_days(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    old = home / "old"
    old.mkdir()
    _age_at(old, 10.5)

    found = leftovers(home, clock=lambda: NOW)

    assert found == [{"path": str(old), "age_days": 10.5}]
    assert isinstance(found[0]["path"], str)
    assert isinstance(found[0]["age_days"], float)


def test_the_oldest_folder_comes_first(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    recent = home / "recent"
    mid = home / "mid"
    oldest = home / "oldest"
    for folder in (recent, mid, oldest):
        folder.mkdir()
    _age_at(recent, 8.0)
    _age_at(mid, 20.0)
    _age_at(oldest, 30.0)

    found = leftovers(home, clock=lambda: NOW)

    assert [item["path"] for item in found] == [str(oldest), str(mid), str(recent)]
    assert [item["age_days"] for item in found] == [30.0, 20.0, 8.0]


def test_a_missing_home_or_a_file_home_gives_no_list_and_no_error(tmp_path: Path) -> None:
    assert leftovers(tmp_path / "nowhere", clock=lambda: NOW) == []
    a_file = tmp_path / "a-file"
    a_file.write_text("x", encoding="utf-8")
    assert leftovers(a_file, clock=lambda: NOW) == []


def test_files_under_the_home_are_not_counted(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    stale = home / "stale.log"
    stale.write_text("x", encoding="utf-8")
    os.utime(stale, (NOW - 30 * DAY, NOW - 30 * DAY))

    found = leftovers(home, clock=lambda: NOW)

    assert found == [], "home 아래 파일은 세지 않는다"


def test_it_only_lists_and_never_removes_anything(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    old = home / "old"
    old.mkdir()
    (old / "work.py").write_text("VALUE = 1\n", encoding="utf-8")
    _age_at(old, 10.0)   # 파일을 넣으면 폴더 mtime 이 갱신되므로, 마지막에 옮긴다

    found = leftovers(home, clock=lambda: NOW)

    assert [item["path"] for item in found] == [str(old)]
    assert old.is_dir(), "목록만 보고 지우지 않는다"
    assert (old / "work.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert [p.name for p in home.iterdir()] == ["old"]
