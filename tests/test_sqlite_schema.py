"""칸 더하기가 겹쳐도 죽지 않는다 (2026-10-06).

공개 저장소의 자동 시험이 깨끗한 기계에서 첫 판에 잡은 것: 시험 일꾼 둘이 같은 일정 DB 를 동시에 처음 열어
둘 다 「repeat_every 가 없다」를 보고 둘 다 더하려다 한쪽이 `duplicate column name` 으로 죽었다.
"""
from __future__ import annotations

import sqlite3

import pytest

from alture_jarvis.scheduler import TaskScheduler
from alture_jarvis.sqlite_schema import add_column_if_missing


class _StaleLook:
    """확인할 때는 「없다」고 보이는데 그 사이 남이 이미 더해 둔 DB."""

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, sql: str, *args):
        if sql.startswith("PRAGMA table_info"):
            return iter(())
        return self._real.execute(sql, *args)


def test_a_new_column_is_added_once() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (id TEXT)")

    assert add_column_if_missing(connection, "t", "note", "TEXT NOT NULL DEFAULT ''") is True
    assert add_column_if_missing(connection, "t", "note", "TEXT NOT NULL DEFAULT ''") is False
    assert [row[1] for row in connection.execute("PRAGMA table_info(t)")] == ["id", "note"]


def test_losing_the_race_to_another_process_is_not_an_error() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (id TEXT, note TEXT)")

    assert add_column_if_missing(_StaleLook(connection), "t", "note", "TEXT") is False


def test_other_failures_still_surface() -> None:
    connection = sqlite3.connect(":memory:")

    with pytest.raises(sqlite3.OperationalError):
        add_column_if_missing(connection, "no_such_table", "note", "TEXT")


def test_two_schedulers_can_open_the_same_new_database(tmp_path) -> None:
    """같은 새 DB 를 둘이 열어도 둘 다 뜬다 — 두 번째는 칸이 이미 있는 DB 를 본다."""
    path = tmp_path / "schedules.sqlite3"
    first = TaskScheduler.__new__(TaskScheduler)
    second = TaskScheduler.__new__(TaskScheduler)
    for scheduler in (first, second):
        scheduler.database_path = path
        scheduler._init_schema()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(schedules)")}
    assert {"repeat_every", "deliver_to"} <= columns
