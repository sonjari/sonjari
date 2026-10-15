"""실적에는 **어느 코드가 낸 것인지**가 붙어 있어야 한다.

## 왜 (2026-08-13 실측)

`audit_log` 는 `tool`·`ok`·`created_at` 만 남겼다. 그래서 눈금이 이렇게 나왔다:

    L4 위임 (무개입)   89.4%   85건   도달 (기준 70%)

그럴듯한데, 표본 1,688건 중 1,398건(83%)이 범용 브라우저 작업 **이전** 코드였고
지금 코드로 낸 것은 **0건**이었다. 기본값이 `--days 0`(전체)이라 08-04 부터 다 합쳐졌다.

산 증거가 같은 표 안에 있었다. `browser_pick_suggestion 74.6%` 가 "발목을 잡는
쓰기 도구"로 계속 지목됐는데, 그 도구는 이미 전날 고쳐져 24/24 였다.
**표가 없어진 세상을 보고 있었고, 그것을 알아볼 방법이 표에 한 줄도 없었다.**

`MIN_SAMPLE` 은 표본이 **적을 때**를 막는다. 막지 못한 것은 표본이 **낡았을 때**다.

## 무엇을 지키나

1. 판 지문은 **내용**으로 낸다 — 복사만 해도 바뀌면(mtime) 배포마다 표본이 0 이 된다
2. 새 실적에는 판이 붙는다 (도구 한 줄, 잡 한 줄)
3. 칸이 없던 옛 DB 도 열린다 — 재는 자가 옛 DB 앞에서 죽으면 아무도 안 재게 된다
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alture_jarvis.config import JarvisConfig, build_id
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import JobStatus


def _store(tmp_path: Path) -> JobStore:
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out"
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return JobStore(config.database_path)


def test_the_build_id_is_stable_across_copies() -> None:
    """같은 코드는 같은 지문이어야 한다.

    `sync_to_runtime.ps1` 이 C: 로 복사할 때마다 mtime 이 바뀐다. 지문이 거기 딸려
    바뀌면 **배포할 때마다 '지금 판 표본'이 0 이 되어** 눈금이 못 쓰게 된다.
    """
    assert build_id() == build_id()
    assert len(build_id()) == 12


def test_a_tool_result_carries_the_build(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_audit("tool_executed", "job-1", {"tool": "browser_read", "ok": True})

    with sqlite3.connect(store.path if hasattr(store, "path") else tmp_path / "data" / "jarvis.db") as conn:
        rows = list(conn.execute("SELECT build FROM audit_log WHERE event = 'tool_executed'"))

    assert rows and rows[0][0] == build_id(), "도구 실적에 판이 안 붙었다"


def test_a_job_carries_the_build(tmp_path: Path) -> None:
    """위임률(L4)은 잡으로 센다 — 도구에만 판을 붙이면 L4 는 여전히 못 가른다."""
    store = _store(tmp_path)
    job = store.create_job("agent", "제목", {})

    with sqlite3.connect(tmp_path / "data" / "jarvis.db") as conn:
        found = conn.execute("SELECT build FROM jobs WHERE id = ?", (job["id"],)).fetchone()

    assert found and found[0] == build_id(), "잡에 판이 안 붙었다"


def test_an_older_database_still_opens(tmp_path: Path) -> None:
    """칸이 없던 DB 를 열면 **덧붙이고** 연다. 옛 줄은 빈 판으로 남는다 —
    그것이 '판을 모르는 표본'이라는 정직한 표시다."""
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,"
            " subject_id TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO audit_log(event, payload_json, created_at) VALUES ('tool_executed', '{}', 1.0)"
        )

    JobStore(path).add_audit("tool_executed", "", {"tool": "browser_read", "ok": True})

    with sqlite3.connect(path) as conn:
        builds = [row[0] for row in conn.execute("SELECT build FROM audit_log ORDER BY id")]

    assert builds == ["", build_id()], f"옛 줄과 새 줄이 갈리지 않았다: {builds}"
