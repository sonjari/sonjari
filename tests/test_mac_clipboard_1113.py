"""맥 클립보드 — `pbcopy` / `pbpaste` (2026-11-13).

launchd 아래 백엔드는 `LANG` 이 비어 C 로캘이 되고, 그러면 pbcopy · pbpaste 가 한글을 `?` 로 깬다.
그래서 늘 UTF-8 로캘을 넘기고 바이트로 주고받는다. 진짜 클립보드는 건드리지 않는다 — `subprocess.run` 을 가짜로 바꾼다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import macos
from alture_jarvis.config import JarvisConfig
from alture_jarvis.messaging.service import SystemClipboard
from alture_jarvis.tool_gateway import tool_runs_here
from alture_jarvis.windows_automation import WindowsAutomationTools

_KOREAN = "손자리 클립보드 — 한글 그대로 ✓"


class _FakePasteboard:
    """pbcopy 는 받은 바이트를 담고, pbpaste 는 담긴 바이트를 돌려준다. 로캘이 UTF-8 이 아니면 진짜처럼 깬다."""

    def __init__(self) -> None:
        self.data = b""
        self.calls: list[dict[str, Any]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append({"cmd": cmd, **kwargs})
        env = kwargs.get("env") or {}
        utf8 = "UTF-8" in str(env.get("LC_CTYPE") or env.get("LC_ALL") or env.get("LANG") or "")
        if cmd == ["pbcopy"]:
            raw = kwargs.get("input") or b""
            assert isinstance(raw, bytes), "pbcopy 에는 바이트를 넘긴다"
            self.data = raw if utf8 else raw.decode("utf-8").encode("ascii", errors="replace")
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        if cmd == ["pbpaste"]:
            return subprocess.CompletedProcess(cmd, 0, self.data, b"")
        raise AssertionError(cmd)


def test_mac_clipboard_round_trips_korean_with_a_utf8_locale() -> None:
    board = _FakePasteboard()
    assert macos.clipboard_write(_KOREAN, run=board) is True
    assert macos.clipboard_read(run=board) == _KOREAN
    for call in board.calls:
        assert "UTF-8" in call["env"]["LANG"] and "UTF-8" in call["env"]["LC_CTYPE"]


def test_mac_clipboard_failure_is_none_not_an_empty_string() -> None:
    def broken(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(cmd, 1, b"", b"no pasteboard")

    assert macos.clipboard_read(run=broken) is None
    assert macos.clipboard_write("x", run=broken) is False


def test_clipboard_tools_run_on_mac_but_windows_hands_do_not() -> None:
    assert tool_runs_here("clipboard_read", "darwin") and tool_runs_here("clipboard_write", "darwin")
    assert not tool_runs_here("windows_copy_from_window", "darwin")
    assert not tool_runs_here("clipboard_read", "linux")


def test_clipboard_tools_work_on_mac(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    board = _FakePasteboard()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(macos.subprocess, "run", board)
    # 윈도우에서 돌 때 맥 갈래를 안 타면 진짜 클립보드로 새지 않게 막는다(고침 빼기 시험 때 실제로 샜다).
    monkeypatch.setitem(sys.modules, "win32clipboard", None)
    tools = WindowsAutomationTools(
        JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")
    )
    written = tools.clipboard_write({"text": _KOREAN})
    assert written["verified"] is True
    read = tools.clipboard_read({})
    assert read["text"] == _KOREAN and read["empty"] is False
    assert [call["cmd"] for call in board.calls] == [["pbcopy"], ["pbpaste"], ["pbpaste"]]


def test_messaging_clipboard_reads_and_clears_on_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    board = _FakePasteboard()
    board.data = _KOREAN.encode("utf-8")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(macos.subprocess, "run", board)
    monkeypatch.setitem(sys.modules, "win32clipboard", None)
    clip = SystemClipboard()
    assert clip.read() == _KOREAN
    clip.clear()
    assert board.data == b""
