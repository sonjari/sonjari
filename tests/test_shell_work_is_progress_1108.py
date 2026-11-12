"""이 PC 의 셸 일도 진척이다 (2026-11-08 게임 시험 2-2 · 맥 세 판 연속 step_cap 12)."""
from __future__ import annotations

from alture_jarvis.agent import BrowserAgent


def _shell(cmd: str, ok: bool = True) -> dict:
    return {"tool": "local_run_shell", "ok": ok, "arguments": {"command": cmd}, "evidence": {}}


def test_new_shell_commands_are_progress() -> None:
    steps = [_shell("ls a"), _shell("unity install --help"), _shell("unity install 6000.6.3f1 --dry-run"),
             _shell("unity modules list"), _shell("ls /Applications/Unity"), _shell("unity install 6000.6.3f1 -m x")]
    assert BrowserAgent._is_stuck(steps) is False


def test_repeating_the_same_command_is_stuck() -> None:
    steps = [_shell("ls /Applications/Unity") for _ in range(6)]
    assert BrowserAgent._is_stuck(steps) is True
