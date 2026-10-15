"""같은 대화를 다시 고르면 **카드도 새로 만든다** (2026-09-21 실전).

## 무슨 일

이어받기 실전에서 git 조회가 한 번 실패해 카드에 `{"repo": false}` 가 박혔다.
원인(느린 `ls-files`)을 고치고 **다시 골랐더니** 응답에는 `repo: true` 가 왔는데,
`accept` 는 여전히 쪽지 모드였다. 저장소를 열어 보니:

    id 5 | status card_only | 저장된 card.git: {"repo": false, "reason": "git_failed"}

`_record` 의 `ON CONFLICT DO UPDATE` 가 `status`·`chat_session`·`updated_at` 만 고치고
**`card_json` 을 안 고친다.** 그래서 한 번 잘못 찍힌 카드가 영원히 박힌다.

## 왜 나쁜가

카드는 「무엇을 하던 중이었나」다. 그 사이 사람이 커밋을 하고 파일을 고쳐도
이어받기는 **멈춘 순간의 옛 사진**을 들고 일한다. 그리고 이번처럼 한 번 실패하면
고칠 방법이 사람에게 없다 — 다시 눌러도 그대로다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.takeover import TakeoverService


class _Git:
    """처음엔 실패하고, 두 번째부터는 멀쩡한 git."""

    def __init__(self) -> None:
        self.healthy = False

    def __call__(self, args: list[str], **_kw: Any) -> subprocess.CompletedProcess:
        if not self.healthy:
            raise subprocess.TimeoutExpired(args, 20)
        tail = args[3:]
        if tail == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(args, 0, b"E:/repo\n", b"")
        if tail == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, b"main\n", b"")
        if tail == ["rev-parse", "--short", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, b"abc1234\n", b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    git = _Git()
    made = TakeoverService(config, run=git)
    session = tmp_path / "chat.jsonl"
    session.write_text("{}\n", encoding="utf-8")

    from alture_jarvis import takeover as module

    state = module.SessionState(
        tool="claude_code", path=str(session), cwd=str(tmp_path), session_id="s1",
        title="시험", first_request="처음", last_request="마지막", last_reply="답",
        request_count=3,
    )
    monkeypatch.setattr(made, "sessions", lambda **_kw: [state])
    made.git = git  # type: ignore[attr-defined]
    return made


def test_a_second_pick_replaces_a_broken_card(service: TakeoverService) -> None:
    """★ 실전에서 막힌 자리 — 한 번 실패한 카드가 다시 골라도 그대로였다."""
    first = service.record_card(str(Path(service.config.runtime_root) / "chat.jsonl"))
    assert first["ok"] and first["card"]["git"]["repo"] is False

    service.git.healthy = True  # type: ignore[attr-defined]
    second = service.record_card(str(Path(service.config.runtime_root) / "chat.jsonl"))
    assert second["takeover_id"] == first["takeover_id"], "같은 대화면 같은 기록이어야 한다"

    stored = service.get(second["takeover_id"])
    assert stored is not None
    assert stored["card"]["git"]["repo"] is True, "응답만 새것이고 저장된 카드는 옛것이다"


def test_the_fresh_card_carries_the_new_facts(service: TakeoverService) -> None:
    service.record_card(str(Path(service.config.runtime_root) / "chat.jsonl"))
    service.git.healthy = True  # type: ignore[attr-defined]
    out = service.record_card(str(Path(service.config.runtime_root) / "chat.jsonl"))
    stored = service.get(out["takeover_id"])
    assert stored["card"]["git"].get("branch") == "main"
