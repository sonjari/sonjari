"""SQLite 스키마에 칸을 더할 때 쓰는 한 줄짜리 문 (2026-10-06).

「칸이 없으면 더한다」를 `PRAGMA table_info` 로 보고 `ALTER TABLE` 하는 두 걸음으로 하면, **같은 DB 를 처음 여는
프로세스가 둘**일 때 둘 다 「없다」를 보고 둘 다 더하려다 한쪽이 `duplicate column name` 으로 죽는다.

우리 PC 에서는 안 보였다 — DB 가 이미 있어서 아무도 칸을 더하지 않는다. 공개 저장소의 자동 시험(깨끗한 기계,
시험 일꾼 여러 개가 동시에 `api` 를 불러옴)이 첫 판에 잡았다: `scheduler._init_schema` 의 `repeat_every`.
같은 꼴이 `jobs.py` 에 셋 더 있어 한 자리로 모은다.
"""
from __future__ import annotations

import sqlite3


def add_column_if_missing(connection: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
    """`table` 에 `column` 이 없으면 더한다. 더했으면 True.

    확인과 추가 사이에 다른 프로세스가 먼저 더했으면 그것이 원하던 상태다 — 죽지 않고 False 를 돌려준다.
    그 밖의 오류(없는 표·잠긴 DB)는 그대로 올린다.
    """
    existing = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    if column in existing:
        return False
    try:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError as error:
        if "duplicate column name" not in str(error).lower():
            raise
        return False
    return True
