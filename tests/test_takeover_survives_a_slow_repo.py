"""이어받기가 **느린 저장소 하나 때문에 무너지면 안 된다** (2026-09-21 실전).

## 무슨 일

간판 기능을 처음으로 실전에서 굴렸다. 결과:

    accept → {"kind": "card"}
    "이어서 할 일을 정리했습니다. 이 지시문을 한도가 풀린 도구에 붙여 넣으면 됩니다."

**일을 받은 게 아니라 붙여넣을 쪽지를 써 준 것이다.** 사장님이 그 세션에서 하신 말과
정면으로 부딪친다 — 「사용자 입장에서 사용량 제한이 걸렸는데 또 돈을 내야 된다,
이게 큰 UX 망침」.

## 왜

    card.git = {"repo": false, "reason": "git_failed"}

`git_state` 가 던지는 `git_failed` 하나로 `accept` 가 「가지를 못 판다」고 보고
쪽지 모드로 내려앉는다. 그런데 이 저장소는 멀쩡한 git 저장소다.

진짜 원인은 **개수 하나를 세려고 1.18MB 를 훑는 것**이었다:

    git ls-files --others --exclude-standard -z     9.7초 · 1,180,368바이트 · 11,880개
    git ls-files --others --exclude-standard --directory -z   0.8초 · 1,568바이트 · 32개

평소엔 12초 안에 들어와 20초 제한을 통과하지만, GPU·디스크가 바쁘면 넘긴다.
그리고 넘기는 순간 **간판 기능이 조용히 쪽지가 된다.**

## 규칙

1. 추적 안 한 파일 **개수**는 덤이다. 그것 때문에 **저장소 사실 전체를 버리지 않는다.**
2. 덤을 못 셌으면 `None` 으로 두고 **말한다** — 0 으로 적으면 「없다」가 된다.
3. 못 이어받을 땐 **왜인지** 말한다. 쪽지만 주고 조용히 넘어가지 않는다.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from alture_jarvis.takeover import git_state


class _FakeGit:
    """`ls-files` 만 느린 저장소. 나머지는 정상."""

    def __init__(self, *, slow_untracked: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.slow_untracked = slow_untracked

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        tail = args[3:]
        if tail[:1] == ["ls-files"]:
            if self.slow_untracked:
                raise subprocess.TimeoutExpired(args, 20)
            return subprocess.CompletedProcess(args, 0, b"a\0b\0", b"")
        if tail == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(args, 0, b"E:/repo\n", b"")
        if tail == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, b"main\n", b"")
        if tail == ["rev-parse", "--short", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, b"abc1234\n", b"")
        if tail[:1] == ["status"]:
            return subprocess.CompletedProcess(args, 0, b" M one.py\n", b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")


def test_a_slow_untracked_scan_does_not_hide_the_repo(tmp_path) -> None:
    """★ 실전에서 무너진 자리 — 덤 하나가 저장소 사실 전체를 버렸다."""
    state = git_state(str(tmp_path), run=_FakeGit())
    assert state["repo"] is True, state
    assert state["branch"] == "main"
    assert state["changed_count"] == 1


def test_an_uncounted_extra_is_none_not_zero(tmp_path) -> None:
    """0 으로 적으면 「추적 안 한 파일이 없다」가 된다 — 모르는 것과 없는 것은 다르다."""
    state = git_state(str(tmp_path), run=_FakeGit())
    assert state["untracked_count"] is None
    assert state.get("untracked_note")


def test_a_healthy_repo_still_counts(tmp_path) -> None:
    state = git_state(str(tmp_path), run=_FakeGit(slow_untracked=False))
    assert state["repo"] is True and state["untracked_count"] == 2
    assert not state.get("untracked_note")


def test_the_cheap_scan_is_what_we_ask_for(tmp_path) -> None:
    """실측: `--directory` 가 9.7초·1.18MB → 0.8초·1.5KB (12배). 폴더는 한 줄로 접는다."""
    fake = _FakeGit(slow_untracked=False)
    git_state(str(tmp_path), run=fake)
    ls = [c for c in fake.calls if c[3:4] == ["ls-files"]]
    assert ls, "추적 안 한 파일을 아예 안 봤다"
    assert "--directory" in ls[0], ls[0]


def test_a_real_failure_is_still_a_failure(tmp_path) -> None:
    """저장소 자체를 못 읽으면 그건 진짜 실패다 — 이 고침이 그걸 가리면 안 된다."""
    def broken(args: list[str], **_kw: Any) -> subprocess.CompletedProcess:
        raise OSError("git 없음")

    assert git_state(str(tmp_path), run=broken)["repo"] is False


def test_not_a_repo_is_reported_plainly(tmp_path) -> None:
    def outside(args: list[str], **_kw: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, 128, b"", b"not a git repository")

    state = git_state(str(tmp_path), run=outside)
    assert state["repo"] is False and state["reason"] == "not_a_git_repo"
