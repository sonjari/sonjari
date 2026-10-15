"""폴더 지우기 — 이 판이 만든 폴더와 캐시 폴더만 (2026-10-04 대표 결정).

코드 판의 검토가 `npm install` 을 돌려 `node_modules` 가 생겼는데, 모델에게는 폴더를 치울 손이 없었다.
파일 지우기는 백업을 떠서 되돌릴 수 있지만 폴더는 못 한다 — 그래서 **잃을 것이 없는 것만** 받는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools, _folders_under

JOB = "job-folder-1"


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path]:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / "node_modules" / "left-pad").mkdir(parents=True)  # 전부터 있던 것
    (repo / "node_modules" / "left-pad" / "index.js").write_text("x", encoding="utf-8")
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(tmp_path)))
    tools.authorize_code_workspace(JOB, str(repo))
    return tools, repo


def _delete(tools: LocalComputerTools, path: Path) -> dict[str, Any]:
    return tools.delete_file({"path": str(path), "__job_id": JOB})


def test_a_folder_this_job_made_is_deleted_and_counted(tmp_path: Path) -> None:
    tools, repo = _tools(tmp_path)
    made = repo / "build_out"
    (made / "deep").mkdir(parents=True)
    (made / "deep" / "a.txt").write_text("hello", encoding="utf-8")
    (made / "b.txt").write_text("hi", encoding="utf-8")

    result = _delete(tools, made)

    assert not made.exists()
    assert result["folder"] is True and result["verified"] is True
    assert result["files_removed"] == 2 and result["bytes_removed"] == 7
    assert result["why_allowed"] == "made_by_this_job"
    assert "되돌릴 수 없다" in result["note"]
    assert "undo_handle" not in result  # 되돌리기를 약속하지 않는다


def test_a_new_folder_inside_an_old_folder_is_still_this_jobs(tmp_path: Path) -> None:
    tools, repo = _tools(tmp_path)
    made = repo / "src" / "generated"
    made.mkdir()

    assert _delete(tools, made)["why_allowed"] == "made_by_this_job"


def test_a_folder_that_was_already_there_is_refused(tmp_path: Path) -> None:
    tools, repo = _tools(tmp_path)

    for old in (repo / "src", repo / "node_modules"):
        with pytest.raises(PermissionError, match="folder_existed_before_this_job"):
            _delete(tools, old)
        assert old.exists()
    # 훑지 않은 폴더의 안쪽은 「없던 폴더」라고 할 수 없다.
    with pytest.raises(PermissionError, match="folder_existed_before_this_job"):
        _delete(tools, repo / "node_modules" / "left-pad")


def test_a_cache_folder_goes_even_if_it_was_there(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "pkg" / "__pycache__").mkdir(parents=True)
    (repo / "pkg" / "__pycache__" / "m.pyc").write_bytes(b"\x00\x01")
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(tmp_path)))
    tools.authorize_code_workspace(JOB, str(repo))

    result = _delete(tools, repo / "pkg" / "__pycache__")

    assert result["why_allowed"] == "regenerated_cache" and not (repo / "pkg" / "__pycache__").exists()


def test_git_history_and_the_workspace_itself_are_never_deleted(tmp_path: Path) -> None:
    tools, repo = _tools(tmp_path)
    nested = repo / "vendor_new"
    (nested / ".git").mkdir(parents=True)  # 이 판이 만든 폴더라도 .git 을 품었으면 안 지운다

    with pytest.raises(PermissionError, match="folder_holds_git_history"):
        _delete(tools, repo / ".git")
    with pytest.raises(PermissionError, match="folder_holds_git_history"):
        _delete(tools, nested)
    with pytest.raises(PermissionError, match="folder_delete_outside_workspace"):
        _delete(tools, repo)
    assert (repo / ".git").exists() and nested.exists() and repo.exists()


def test_a_resumed_job_does_not_forget_what_was_there_at_the_start(tmp_path: Path) -> None:
    """멈췄다 다시 도는 판은 작업 폴더를 다시 묶는다 — 그때 다시 적으면 그새 만든 폴더가 「원래 있던 것」이 된다."""
    tools, repo = _tools(tmp_path)
    made = repo / "node_cache_new"
    made.mkdir()

    tools.authorize_code_workspace(JOB, str(repo))  # 재개

    assert _delete(tools, made)["why_allowed"] == "made_by_this_job"


def test_files_are_deleted_the_old_way_with_a_backup(tmp_path: Path) -> None:
    tools, repo = _tools(tmp_path)

    result = _delete(tools, repo / "src" / "app.py")

    assert result.get("folder") is None and result["undo_handle"]["backup_path"]


def test_the_start_snapshot_lists_heavy_folders_without_walking_into_them(tmp_path: Path) -> None:
    _tools_, repo = _tools(tmp_path)

    seen = _folders_under(repo)

    assert seen is not None and {"src", ".git", "node_modules"} <= seen
    assert "node_modules/left-pad" not in seen


def test_a_refused_folder_is_turned_away_before_any_approval_card(tmp_path: Path) -> None:
    """실패가 정해진 일을 사람에게 묻지 않는다 — 승인 전 검사가 같은 잣대로 먼저 거절한다."""
    tools, repo = _tools(tmp_path)

    with pytest.raises(PermissionError, match="folder_existed_before_this_job"):
        tools._delete_pre_check({"path": str(repo / "node_modules"), "__job_id": JOB})
    assert (repo / "node_modules").exists()  # 검사는 아무것도 지우지 않는다

    made = repo / "tmp_out"
    made.mkdir()
    tools._delete_pre_check({"path": str(made), "__job_id": JOB})  # 될 폴더는 그냥 지나간다
    assert made.exists()
    tools._delete_pre_check({"path": str(repo / "src" / "app.py"), "__job_id": JOB})  # 파일은 예전 그대로


def test_folder_deletion_outside_a_code_job_is_refused(tmp_path: Path) -> None:
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(tmp_path)))
    folder = tmp_path / "somewhere"
    folder.mkdir()

    with pytest.raises(PermissionError, match="folder_delete_only_in_code_workspace"):
        tools._folder_deletable(folder, {"path": str(folder), "__job_id": "cowork-job"})
    assert folder.exists()


def test_the_risk_and_proof_paths_accept_a_folder_without_raising(tmp_path: Path) -> None:
    from alture_jarvis.models import RiskLevel

    tools, repo = _tools(tmp_path)
    made = repo / "tmp_out"
    made.mkdir()
    arguments = {"path": str(made), "__job_id": JOB}

    assert tools._delete_risk(arguments) == RiskLevel.L1  # 작업 폴더 안 — 파일 지우기와 같은 등급
    assert tools._capture_file_proof(arguments)["exists"] is False  # 폴더는 파일 증명 대상이 아니다(예외 없이 지나간다)


# --- 치우는 일에는 「먼저 읽어라」가 안 맞는다 (라이브 04ec9c42) ------------------

def test_cleaning_up_does_not_have_to_read_first(tmp_path: Path) -> None:
    """캐시 폴더와 자기가 만든 파일을 지우려는 네 번이 전부 `code_recon_required` 에 막혀, 모델이 셸로 돌아가 지웠다."""
    import inspect

    from alture_jarvis import agent

    repo = tmp_path / "repo"
    (repo / "__pycache__").mkdir(parents=True)
    (repo / "old.py").write_text("x = 1\n", encoding="utf-8")
    wrote = [{"tool": "local_write_file", "ok": True, "arguments": {"path": "probe.py"}, "evidence": {}}]

    # 폴더 — 무엇을 지워도 되는지는 도구가 가른다.
    assert agent._cleans_up("local_delete_file", {"path": str(repo / "__pycache__")}, [], str(repo))
    assert agent._cleans_up("local_delete_file", {"path": "__pycache__"}, [], str(repo))  # 상대 경로
    # 자기가 쓴 파일.
    assert agent._cleans_up("local_delete_file", {"path": "probe.py"}, wrote, str(repo))
    # 원래 있던 **파일**은 그대로 규칙을 탄다. 쓰기·고치기도.
    assert not agent._cleans_up("local_delete_file", {"path": str(repo / "old.py")}, wrote, str(repo))
    assert not agent._cleans_up("local_apply_edit", {"path": "__pycache__"}, [], str(repo))
    assert not agent._cleans_up("local_delete_file", {"path": ""}, [], str(repo))

    source = inspect.getsource(agent.BrowserAgent.run)
    gate = source[source.index("and not code_recon_ready"):source.index('"error": "code_recon_required"')]
    assert "and not _cleans_up(name, arguments, steps, desk_root)" in gate
