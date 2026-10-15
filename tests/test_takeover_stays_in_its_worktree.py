"""이어받기는 **가지에서만** 일한다 (2026-09-23 실측).

이어받기 실험(클로드 코드+로컬 대 온텔릭) B2·B3 에서 온텔릭이 인계문의 **원래 폴더 경로**를 그대로
따라가, 막히자 폴더 권한을 받아 원래 폴더를 고쳤다. 가지 쪽 「온텔릭 이어 작업」 커밋은 비어 있었다.
원인 둘:

  ① 인계문이 원래 경로를 준다(작업 폴더 줄·파일 목록·클로드의 마지막 답)
  ② 규칙 1번이 「git diff 로 읽어라」인데 가지에서는 멈춘 순간의 변경이 **이미 커밋**돼 diff 가 비어 보인다

고침도 둘 — 안내문(①②)과 **도구가 바꿔 끼우기**(가지 안의 `.git` 파일이 원래 뿌리를 알려 준다).
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from alture_jarvis import takeover
from alture_jarvis.agent import BrowserAgent as JarvisAgent
from alture_jarvis.takeover import card_for_worktree, resume_prompt


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo_and_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "db.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "seed")
    worktree = tmp_path / "wt" / "8-1"
    _git(repo, "worktree", "add", "-q", "-b", "jarvis/takeover-8", str(worktree), "HEAD")
    return repo, worktree


def test_a_worktree_knows_its_origin(repo_and_worktree) -> None:
    repo, worktree = repo_and_worktree
    assert Path(JarvisAgent._worktree_origin(str(worktree))).resolve() == repo.resolve()


def test_an_ordinary_repo_has_no_origin(repo_and_worktree) -> None:
    repo, _ = repo_and_worktree
    assert JarvisAgent._worktree_origin(str(repo)) == ""


def test_original_paths_are_moved_into_the_worktree(repo_and_worktree) -> None:
    repo, worktree = repo_and_worktree
    origin = JarvisAgent._worktree_origin(str(worktree))
    agent = object.__new__(JarvisAgent)
    args = {"path": str(Path(origin) / "db.py"), "old": "x = 1", "new": "x = 2"}
    moved, note = agent._remap_into_worktree(args, str(worktree))
    assert Path(moved["path"]) == worktree / "db.py"
    assert moved["old"] == "x = 1" and moved["new"] == "x = 2", "경로가 아닌 인자는 그대로"
    assert "작업 가지" in note

    slashed = {"path": str(Path(origin) / "db.py").replace("\\", "/")}
    assert Path(agent._remap_into_worktree(slashed, str(worktree))[0]["path"]) == worktree / "db.py"
    assert Path(agent._remap_into_worktree({"path": origin}, str(worktree))[0]["path"]) == worktree


def test_paths_elsewhere_are_left_alone(repo_and_worktree, tmp_path: Path) -> None:
    _, worktree = repo_and_worktree
    agent = object.__new__(JarvisAgent)
    assert agent._remap_into_worktree({"path": str(worktree / "db.py")}, str(worktree)) is None
    assert agent._remap_into_worktree({"path": str(tmp_path / "other" / "db.py")}, str(worktree)) is None
    # 이름만 비슷한 옆 폴더(repo2)는 원래 저장소가 아니다
    assert agent._remap_into_worktree({"path": str(tmp_path / "repo2" / "db.py")}, str(worktree)) is None


def _card(root: str) -> dict:
    return {
        "tool_name": "Claude Code", "cwd": root, "first_request": "세 가지 해줘",
        "last_request": "세 가지 해줘", "last_reply": str(Path(root) / "pager.py") + " 를 고쳤습니다",
        "files": ["pager.py"], "open_tasks": [], "recent_commands": [f"cd {root} && pytest"],
        "git": {"root": root, "repo": True},
    }


def test_the_handoff_points_at_the_worktree_not_the_original(tmp_path: Path) -> None:
    root = str(tmp_path / "repo")
    worktree = str(tmp_path / "wt" / "8-1")
    text = resume_prompt(card_for_worktree(_card(root), worktree))
    assert f"작업 폴더: {worktree}" in text
    assert str(Path(worktree) / "pager.py") + " 를 고쳤습니다" in text
    assert "고치지 않는다" in text and root in text, "원래 폴더는 금지로만 한 번 나온다"
    assert text.count(root) == 1
    assert "git show --stat HEAD" in text, "가지에서는 git diff 가 비어 보인다"


def test_without_a_worktree_the_old_rules_stay() -> None:
    text = resume_prompt(_card("C:/repo"))
    assert "git diff" in text and "git show" not in text


def test_the_branch_job_uses_the_moved_card() -> None:
    assert "resume_prompt(card_for_worktree(card, worktree))" in inspect.getsource(takeover.TakeoverService.continue_on_branch)


# ── 요청이 잘리면 이어 할 모델은 요구를 못 본다 (2026-09-23 실측) ─────────────
def _long_request() -> str:
    head = "세 가지를 해줘. " + "앞부분 설명 " * 60
    return head + "마지막으로 test_textutil.py 에 word_count 테스트를 2개 이상 추가해."


def test_a_long_request_reaches_the_next_model_whole() -> None:
    """★ 400 자에서 잘려 「테스트를 2개 이상 추가해」가 통째로 빠졌다 — B1·B3 가 그 테스트를 빠뜨렸다."""
    from alture_jarvis.takeover import REQUEST_LIMIT, SessionState, build_card

    request = _long_request()
    assert 400 < len(request) < REQUEST_LIMIT
    state = SessionState(tool="claude_code", path="x.jsonl", cwd="C:/repo")
    state.first_request = state.last_request = request
    card = build_card(state, {"root": "", "repo": False}, now=0.0)
    text = resume_prompt(card)
    assert "테스트를 2개 이상 추가해" in text
    assert text.count("테스트를 2개 이상 추가해") == 1, "처음=마지막이면 한 번만 싣는다"


def test_the_chat_offer_stays_short() -> None:
    from alture_jarvis.takeover import _clean

    assert len(_clean(_long_request(), 200)) <= 200


def test_a_request_too_long_even_now_says_so() -> None:
    card = _card("C:/repo")
    card["first_request"] = card["last_request"] = "아주 긴 요청…"
    card["session_path"] = "C:/s/a.jsonl"
    text = resume_prompt(card)
    assert "잘렸다" in text and "C:/s/a.jsonl" in text
