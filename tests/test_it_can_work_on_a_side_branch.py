"""이어받기는 **남의 작업 위에서 일하지 않는다** — git worktree (2026-09-21).

## 왜

클로드가 한도에 걸려 멈추면 온텔릭이 이어받는다. 그때 온텔릭이 `main` 의 작업 폴더를
그대로 고치면:

  * 사람이 보던 파일이 발밑에서 바뀐다
  * 클로드가 돌아왔을 때 누가 뭘 고쳤는지 안 갈린다
  * 실패한 판을 통째로 버릴 방법이 없다

`git worktree add ../옆자리 -b 가지이름` 하나면 **같은 저장소의 다른 폴더**에서
딴 가지로 일할 수 있다. 컨테이너 없이 되는 격리다 — 이 PC 에 도커도 없다.

## 열되, 되돌리기를 어렵게 만드는 것은 막는다

기존 git 관문의 규칙 그대로다: **되돌리기가 브랜치 삭제보다 어려워지는 것은 안 연다.**

  * `worktree add`      ✅ 새 자리를 만든다 — 아무것도 안 지운다
  * `worktree list`     ✅ 읽기
  * `worktree remove`   ❌ 일한 것을 통째로 버린다. 사람이 판단할 일이다
  * `worktree prune`    ❌ 같은 이유
  * `--force` 붙은 것   ❌ 어디에 붙든
"""

from __future__ import annotations

import pytest

from alture_jarvis.local_computer import (
    _GIT_COMMANDS,
    _GIT_WRITE_COMMANDS,
    _check_git_write_args,
)


# ── 만드는 것은 연다 ────────────────────────────────────────────────────────
def test_worktree_is_a_git_command_we_know() -> None:
    assert "worktree" in _GIT_WRITE_COMMANDS or "worktree" in _GIT_COMMANDS


def test_making_a_side_worktree_on_a_new_branch_is_allowed() -> None:
    _check_git_write_args(["worktree", "add", "../ontelic-takeover", "-b", "takeover/2026-09-21"])


def test_listing_worktrees_is_allowed() -> None:
    _check_git_write_args(["worktree", "list"])


# ── 버리는 것은 사람이 한다 ─────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    ["worktree", "remove", "../ontelic-takeover"],
    ["worktree", "prune"],
])
def test_throwing_work_away_is_refused(bad: list[str]) -> None:
    with pytest.raises(PermissionError) as caught:
        _check_git_write_args(bad)
    assert "worktree" in str(caught.value)


def test_force_is_refused_here_too() -> None:
    with pytest.raises(PermissionError) as caught:
        _check_git_write_args(["worktree", "add", "--force", "../x", "-b", "y"])
    assert "force" in str(caught.value)


def test_adding_onto_an_existing_branch_is_refused() -> None:
    """★ 기존 가지에 붙이면 그 가지에서 남이 일하고 있을 수 있다.
    `switch` 를 「새 가지만」으로 막아 둔 것과 같은 이유다."""
    with pytest.raises(PermissionError) as caught:
        _check_git_write_args(["worktree", "add", "../x", "main"])
    assert "branch" in str(caught.value)


# ── 이미 있던 규칙을 안 깨뜨렸나 ────────────────────────────────────────────
def test_the_old_git_rules_still_hold() -> None:
    with pytest.raises(PermissionError):
        _check_git_write_args(["commit", "--amend", "-m", "x"])
    with pytest.raises(PermissionError):
        _check_git_write_args(["checkout", "."])
    with pytest.raises(PermissionError):
        _check_git_write_args(["branch", "-D", "main"])
    # 되는 것은 그대로 된다
    _check_git_write_args(["commit", "-m", "메시지"])
    _check_git_write_args(["switch", "-c", "새-가지"])
