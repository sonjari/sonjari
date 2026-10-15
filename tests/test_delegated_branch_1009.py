"""바깥 AI 가 맡긴 코드 일은 그 저장소의 **새 가지**에서 한다 (2026-10-09).

진짜 git 으로 돈다 — 가지를 따고, 맡긴 폴더만 꺼내고, 커밋 안 된 변경을 가져오고, 끝에 커밋해 바뀐 것을 요약하는 것까지.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from alture_jarvis import delegated_branch as branch_module
from alture_jarvis.delegated_branch import BRANCH_PREFIX, finish, prepare, take_home

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git 이 없는 환경")


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t.example", *args], capture_output=True, check=True)
    return done.stdout.decode("utf-8", "replace").strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "app" / "pkg").mkdir(parents=True)
    (root / "other").mkdir()
    (root / "app" / "pkg" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "other" / "big.txt").write_text("not ours\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    return root


def test_a_new_branch_is_cut_and_the_original_folder_is_left_alone(repo: Path, tmp_path: Path) -> None:
    made = prepare(str(repo), home=tmp_path / "home", clock=lambda: 1_000)

    assert made["ok"] is True, made
    assert made["branch"] == f"{BRANCH_PREFIX}1000"
    assert Path(made["workspace"]) == Path(made["worktree"])
    assert (Path(made["workspace"]) / "app" / "pkg" / "mod.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"      # 원래 폴더는 제 가지 그대로
    assert _git(repo, "status", "--porcelain") == ""
    assert made["base"] == _git(repo, "rev-parse", "HEAD") and made["carried"] is False


def test_only_the_folder_that_was_handed_over_is_checked_out(repo: Path, tmp_path: Path) -> None:
    made = prepare(str(repo / "app"), home=tmp_path / "home", clock=lambda: 2_000)

    assert made["ok"] is True, made
    workspace = Path(made["workspace"])
    assert workspace == Path(made["worktree"]) / "app"
    assert (workspace / "pkg" / "mod.py").is_file()
    assert not (Path(made["worktree"]) / "other").exists(), "맡기지 않은 폴더까지 꺼냈다"
    assert Path(made["repo"]).resolve() == repo.resolve()


def test_uncommitted_edits_come_along_as_the_starting_point(repo: Path, tmp_path: Path) -> None:
    (repo / "app" / "pkg" / "mod.py").write_text("VALUE = 2  # 맡긴 쪽이 아직 커밋 안 한 것\n", encoding="utf-8")
    (repo / "app" / "scratch.log").write_text("추적 안 한 파일\n", encoding="utf-8")

    made = prepare(str(repo), home=tmp_path / "home", clock=lambda: 3_000)

    assert made["carried"] is True
    workspace = Path(made["workspace"])
    assert "VALUE = 2" in (workspace / "app" / "pkg" / "mod.py").read_text(encoding="utf-8")
    assert not (workspace / "app" / "scratch.log").exists(), "추적 안 한 파일은 가져오지 않는다"
    assert made["base"] != _git(repo, "rev-parse", "HEAD"), "가져온 변경은 시작점 커밋으로 박힌다"
    # 원래 폴더의 변경은 그대로 남아 있다.
    assert "VALUE = 2" in (repo / "app" / "pkg" / "mod.py").read_text(encoding="utf-8")


def test_finish_commits_on_the_branch_and_says_what_changed_since_the_start(repo: Path, tmp_path: Path) -> None:
    (repo / "app" / "pkg" / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")     # 맡긴 쪽의 미커밋 변경
    made = prepare(str(repo / "app"), home=tmp_path / "home", clock=lambda: 4_000)
    workspace = Path(made["workspace"])
    (workspace / "pkg" / "mod.py").write_text("VALUE = 3\n", encoding="utf-8")        # 손자리가 한 것
    (workspace / "pkg" / "new_test.py").write_text("def test_it():\n    assert True\n", encoding="utf-8")

    done = finish(made["worktree"], made["base"], message="손자리 작업: 값 고치기")

    assert done["ok"] is True
    assert {(item["status"], item["path"]) for item in done["changed"]} == {("M", "app/pkg/mod.py"), ("A", "app/pkg/new_test.py")}
    assert done["changed_count"] == 2 and "2 files changed" in done["stat"]
    # 가지에는 손자리의 것만 시작점 위에 얹혀 있다 — 맡긴 쪽의 미커밋 변경(VALUE = 2)은 시작점 쪽이다.
    assert _git(repo, "log", "--format=%s", f"{made['base']}..{made['branch']}") == "손자리 작업: 값 고치기"
    assert _git(repo, "log", "-1", "--format=%an", made["branch"]) == "Sonjari"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_finishing_with_nothing_changed_reports_nothing(repo: Path, tmp_path: Path) -> None:
    made = prepare(str(repo), home=tmp_path / "home", clock=lambda: 5_000)
    done = finish(made["worktree"], made["base"], message="아무것도 안 함")
    assert done["ok"] is True and done["changed"] == [] and done["head"] == made["base"]


def test_a_folder_that_is_not_a_repository_is_refused_with_the_reason(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert prepare(str(plain), home=tmp_path / "home")["error"] == "not_a_git_repo"
    assert prepare(str(tmp_path / "nowhere"), home=tmp_path / "home")["error"] == "folder_missing"


def test_the_take_home_commands_name_the_branch_and_never_merge_for_the_caller() -> None:
    notes = take_home("C:/work/repo", f"{BRANCH_PREFIX}1", "abcdef1234567890", "C:/out/repo-1")
    assert notes["review"] == 'git -C "C:/work/repo" diff abcdef123456..sonjari/task-1'
    assert "cherry-pick -n" in notes["take"], "가져오되 커밋은 가져가는 쪽이 정한다"
    assert "worktree remove" in notes["discard"] and "branch -D sonjari/task-1" in notes["discard"]
    # 손자리가 원래 폴더에 합치는 길은 이 모듈에 없다.
    source = Path(branch_module.__file__).read_text(encoding="utf-8")
    assert '"merge"' not in source and '"push"' not in source
