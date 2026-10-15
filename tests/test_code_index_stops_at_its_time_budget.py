"""코드 색인 따라잡기는 시간 상한에서 **거기까지 저장하고** 멈춘다 — 다음 요청이 잇는다 (2026-10-06).

대표 실사용: 「색인이 너무 느린데 이걸 방어하는 로직을 넣어 놓지 않았나」. 09-28 에 넣은 것은 진행 표시뿐이었다.
첫 걸음 전에 동기로 도는 일이라 오래 걸리면 판 전체가 그만큼 서 있는다.

같이 지키는 것: 끝까지 못 훑은 따라잡기는 「없어진 파일」을 지우지 않는다 — 아직 못 본 파일이 색인에서 빠지면 안 된다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import alture_jarvis.code_index as code_index_module
from alture_jarvis.code_index import CodeIndex


def _repo(tmp_path: Path, count: int) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for number in range(count):
        (repo / f"m{number:02d}.py").write_text(f"def f{number}():\n    return {number}\n", encoding="utf-8")
    return repo


def _indexed_paths(index: CodeIndex, repo: Path) -> set[str]:
    with sqlite3.connect(index._database_path(repo.resolve())) as db:
        return {row[0] for row in db.execute("SELECT path FROM files")}


def _tick(monkeypatch, step: float = 1.0) -> None:
    """시계가 부를 때마다 `step` 초씩 간다 — 파일 하나를 볼 때마다 시간이 흐른다."""
    now = {"t": 0.0}

    def monotonic() -> float:
        now["t"] += step
        return now["t"]

    monkeypatch.setattr(code_index_module.time, "monotonic", monotonic)


def test_without_a_budget_everything_is_read_as_before(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, 12)
    _tick(monkeypatch)
    index = CodeIndex(tmp_path / "index")

    stats = index.refresh(repo)

    assert stats["updated_files"] == 12 and stats["truncated"] is False and stats["stopped"] == ""
    assert len(_indexed_paths(index, repo)) == 12


def test_a_catch_up_stops_at_the_budget_and_keeps_what_it_read(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, 12)
    _tick(monkeypatch)
    index = CodeIndex(tmp_path / "index")

    first = index.refresh(repo, budget_sec=6.0)

    assert first["stopped"] == "time" and first["truncated"] is True
    assert 0 < first["updated_files"] < 12
    assert len(_indexed_paths(index, repo)) == first["updated_files"], "멈추기 전에 읽은 것은 저장돼 있어야 한다"
    assert index.last_refresh["stopped"] == "time"


def test_the_next_requests_pick_up_where_it_stopped(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, 12)
    _tick(monkeypatch)
    index = CodeIndex(tmp_path / "index")

    rounds = 0
    while True:
        rounds += 1
        stats = index.refresh(repo, budget_sec=6.0)
        if stats["stopped"] != "time":
            break
        assert stats["updated_files"] >= 1, "한 번에 하나도 못 읽으면 영영 못 끝난다"
        assert rounds < 30

    assert rounds > 1, "상한이 실제로 걸린 뒤에 이어서 끝났다"
    assert len(_indexed_paths(index, repo)) == 12
    assert index.last_refresh["stopped"] == ""


def test_stopping_early_does_not_drop_files_it_has_not_reached_yet(tmp_path: Path, monkeypatch) -> None:
    """먼저 다 읽어 둔 저장소에서 파일 몇 개가 바뀌었다 — 상한에 걸려 멈춰도, 아직 못 본 파일은 색인에 남는다."""
    repo = _repo(tmp_path, 12)
    index = CodeIndex(tmp_path / "index")
    index.refresh(repo)
    assert len(_indexed_paths(index, repo)) == 12
    for number in range(12):
        (repo / f"m{number:02d}.py").write_text(f"def g{number}():\n    return {number} + 1\n", encoding="utf-8")
    _tick(monkeypatch)

    stats = index.refresh(repo, budget_sec=6.0)

    assert stats["stopped"] == "time" and stats["removed_files"] == 0
    assert len(_indexed_paths(index, repo)) == 12, "아직 못 훑은 파일을 「사라진 파일」로 지우면 안 된다"


def test_a_file_that_really_went_away_is_still_removed_when_the_scan_finishes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 4)
    index = CodeIndex(tmp_path / "index")
    index.refresh(repo)
    (repo / "m03.py").unlink()

    stats = index.refresh(repo, budget_sec=CodeIndex.REFRESH_BUDGET_SEC)

    assert stats["removed_files"] == 1 and stats["stopped"] == ""
    assert _indexed_paths(index, repo) == {"m00.py", "m01.py", "m02.py"}
