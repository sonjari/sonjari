"""한 판에서 밀린 색인 따라잡기를 두 번 하지 않는다 (2026-10-22 대표 실사용 · 판 84e3771a).

모노레포에서 첫 걸음 전 지도(`repo_card` → `refresh`)가 시간 상한(45초)까지 따라잡고 멈춘 직후, 첫 걸음의 색인 도구
(`query` → `refresh`)가 또 48초를 따라잡았다. 첫 모델 부르기까지 2분 31초. 이제 방금(`BACKLOG_REUSE_SEC` 안) 같은
저장소를 시간 상한까지 따라잡고 멈췄으면 질의는 다시 따라잡지 않는다. 밀린 것 없이 끝난 갱신은 1초 안팎이라 그대로 다시 한다.
"""

from __future__ import annotations

from pathlib import Path

import alture_jarvis.code_index as code_index_module
from alture_jarvis.agent import AgentToolCatalog
from alture_jarvis.code_index import CodeIndex


def _repo(tmp_path: Path, name: str = "repo", count: int = 4) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    for number in range(count):
        (repo / f"m{number}.py").write_text(f"def f{number}():\n    return {number}\n", encoding="utf-8")
    return repo


def _counting(index: CodeIndex) -> list[Path]:
    calls: list[Path] = []
    original = index.refresh

    def refresh(root, **kwargs):  # noqa: ANN001, ANN003
        calls.append(root)
        return original(root, **kwargs)

    index.refresh = refresh  # type: ignore[method-assign]
    return calls


def test_query_right_after_a_timed_out_catch_up_does_not_catch_up_again(tmp_path: Path) -> None:
    repo = _repo(tmp_path).resolve()
    index = CodeIndex(tmp_path / "index")
    index.refresh(repo)
    index.last_refresh = {**index.last_refresh, "stopped": "time"}  # 방금 시간 상한까지 따라잡고 멈춘 것처럼
    calls = _counting(index)

    result = index.query(repo, "f1")

    assert calls == [], "방금 45초를 쓴 따라잡기를 같은 판에서 또 하면 안 된다"
    assert result["index"]["reused_backlog"] is True
    assert index.last_refresh["stopped"] == "time", "「다 못 따라잡았다」는 사실은 그대로 남아 도구 결과가 말할 수 있어야 한다"


def test_finished_refresh_is_redone_so_fresh_edits_show_up(tmp_path: Path, monkeypatch) -> None:
    """★ 2026-10-23 바뀜: 끝까지 따라잡은 직후의 질의는 **손자리가 그사이 무언가 바꿨을 때만** 다시 훑는다(`FRESH_REUSE_SEC`).
    예전엔 매번 다시 훑었다 — 한 질문 안에서 지도 · 첫 색인 도구가 같은 1만 2천 파일을 두 번 훑었다(대표 판 10.1초 + 6.8초)."""
    repo = _repo(tmp_path).resolve()
    index = CodeIndex(tmp_path / "index")
    index.refresh(repo)  # 밀린 것 없이 끝남
    calls = _counting(index)

    index.query(repo, "f1")
    assert calls == [], "방금 끝까지 훑었고 아무것도 안 바꿨다 — 다시 훑지 않는다"

    CodeIndex.note_write()  # 손자리가 파일을 썼다
    index.query(repo, "f1")
    assert calls == [repo], "손자리가 바꿨으면 다시 훑는다 — 방금 고친 파일이 들어오게"

    ended = index.last_refresh["ended"]
    monkeypatch.setattr(code_index_module.time, "monotonic", lambda: ended + index.FRESH_REUSE_SEC + 1.0)
    index.query(repo, "f1")
    assert calls == [repo, repo], "1분이 지났으면 다시 훑는다 — 사람이 편집기로 고친 것도 들어오게"


def test_old_or_other_repo_timeouts_do_not_block_a_refresh(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path).resolve()
    other = _repo(tmp_path, "other").resolve()
    index = CodeIndex(tmp_path / "index")
    index.refresh(repo)
    index.last_refresh = {**index.last_refresh, "stopped": "time", "root": str(other)}
    calls = _counting(index)
    index.query(repo, "f1")
    assert calls == [repo], "다른 저장소가 멈춘 것은 이 저장소와 상관없다"

    index.last_refresh = {**index.last_refresh, "stopped": "time", "root": str(repo), "ended": 0.0}
    now = index.BACKLOG_REUSE_SEC + 1.0
    monkeypatch.setattr(code_index_module.time, "monotonic", lambda: now)
    index.query(repo, "f1")
    assert calls == [repo, repo], "오래전에 멈춘 것은 이어서 따라잡는다"


def test_catalog_reports_the_last_refresh_for_the_job_record() -> None:
    class _Index:
        last_refresh = {"updated_files": 267, "scanned": 1760, "stopped": "time"}

    class _Local:
        code_index = _Index()

    assert AgentToolCatalog(object(), _Local()).last_index_refresh()["updated_files"] == 267
    assert AgentToolCatalog(object()).last_index_refresh() == {}
