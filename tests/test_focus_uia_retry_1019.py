"""SetForegroundWindow 가 0 을 주면 UIA 로 한 번만 더 시도한다 (2026-10-19).

`local_computer.py` 의 `focus_window` 가 `user32.SetForegroundWindow` 만을 믿다가 0 을 받으면
바로 `window_focus_failed` 를 냈다. 미리보기 → 실행 단계는 UIA 의
`Desktop(backend="uia").window(handle=…).set_focus()` 로 포커스를 맞추는 데, 그 길로 한 번만
더 시도해서 통하면 성공(`"focused_by": "uia"`)으로 보고, pywinauto 로 못 가거나(불러오기 실패 ·
예외) 그 뒤에도 앞이 아니면 **기존 window_focus_failed 문장 그대로** 낸다. 바로 성공한 경우는
그전과 똑같다. 시험은 실제 창을 건드리지 않는다 — user32 · window_view · UserPresence ·
pywinauto 를 가짜로 바꾼다(`tests/test_window_into_view_1019.py` 의 가짜를 참고).
"""

from __future__ import annotations

import ctypes as real_ctypes
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import window_view
from alture_jarvis.config import JarvisConfig
from alture_jarvis.user_presence import UserPresence
from alture_jarvis.window_view import Monitor, Rect

PRIMARY = Monitor(Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1032), True)
#: 주 모니터 안에 잘 보이는 창 — 옮길 일도, 최소화도 없다.
RECT = Rect(100, 100, 900, 700)
WINDOW_ID = 48959036


class FakeDesk:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def monitors(self) -> list[Monitor]:
        return [PRIMARY]

    def rect(self, hwnd: int) -> Rect:
        return RECT

    def is_minimized(self, hwnd: int) -> bool:
        return False

    def is_maximized(self, hwnd: int) -> bool:
        return False

    def restore(self, hwnd: int) -> None:
        self.calls.append("restore")

    def move(self, hwnd: int, rect: Rect) -> bool:
        self.calls.append(("move", rect))
        return True


class _FakeUser32:
    def __init__(self, *, foreground_ok: bool) -> None:
        self.foreground_ok = foreground_ok
        self.front: int = 0

    def IsWindow(self, hwnd: int) -> int:  # noqa: N802 — user32 이름 그대로
        return 1

    def GetWindowTextLengthW(self, hwnd: int) -> int:  # noqa: N802
        return 6

    def GetWindowTextW(self, hwnd: int, buffer: Any, size: int) -> int:  # noqa: N802
        buffer.value = "Claude"
        return 6

    def IsIconic(self, hwnd: int) -> int:  # noqa: N802
        return 0

    def ShowWindow(self, hwnd: int, command: int) -> int:  # noqa: N802
        return 1

    def SetForegroundWindow(self, hwnd: int) -> int:  # noqa: N802
        self.front = hwnd if self.foreground_ok else 0
        return self.front

    def GetForegroundWindow(self) -> int:  # noqa: N802
        return self.front


def _local_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, foreground_ok: bool) -> _FakeUser32:
    if os.name != "nt":
        pytest.skip("윈도우 전용 손")
    from alture_jarvis import local_computer

    user32 = _FakeUser32(foreground_ok=foreground_ok)
    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(user32=user32),
                                  create_unicode_buffer=real_ctypes.create_unicode_buffer)
    monkeypatch.setattr(local_computer, "ctypes", fake_ctypes)
    monkeypatch.setattr(window_view, "desktop", lambda: FakeDesk())
    monkeypatch.setattr(UserPresence, "wait_until_idle", lambda self, **kw: True)
    monkeypatch.setattr(window_view.time, "sleep", lambda _s: None)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")
    tools = local_computer.LocalComputerTools(config)
    global _TOOLS
    _TOOLS = tools
    return user32


_TOOLS: Any = None


def _focus() -> Any:
    return _TOOLS.focus_window({"window_id": WINDOW_ID})


def _fake_pywinauto(monkeypatch: pytest.MonkeyPatch, user32: _FakeUser32, *, focus_ok: bool,
                    raises: Exception | None = None) -> None:
    """`from pywinauto import Desktop` 을 가짜 모듈로 받아서 실제 창을 건드리지 않는다."""

    class _Window:
        def set_focus(self) -> None:
            if raises is not None:
                raise raises
            if focus_ok:
                user32.front = WINDOW_ID

    class _Desktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def window(self, handle: int) -> _Window:
            assert handle == WINDOW_ID
            return _Window()

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=_Desktop))


def test_immediate_success_needs_no_uia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _local_tools(tmp_path, monkeypatch, foreground_ok=True)
    result = _focus()
    assert result["action"] == "windows_focus_window"
    assert result["title"] == "Claude"
    assert "focused_by" not in result


def test_uia_retry_focuses_the_window_and_says_uia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user32 = _local_tools(tmp_path, monkeypatch, foreground_ok=False)
    _fake_pywinauto(monkeypatch, user32, focus_ok=True)
    result = _focus()
    assert result["action"] == "windows_focus_window"
    assert result["focused_by"] == "uia"
    assert result["window_id"] == WINDOW_ID


def test_uia_exception_keeps_the_same_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user32 = _local_tools(tmp_path, monkeypatch, foreground_ok=False)
    _fake_pywinauto(monkeypatch, user32, focus_ok=True, raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError) as caught:
        _focus()
    message = str(caught.value)
    assert message.startswith("window_focus_failed: 창은")
    assert "위치 문제가 아니라" in message and "windows_execute_preview" in message


def test_still_not_foreground_after_uia_keeps_the_same_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user32 = _local_tools(tmp_path, monkeypatch, foreground_ok=False)
    _fake_pywinauto(monkeypatch, user32, focus_ok=False)
    with pytest.raises(RuntimeError) as caught:
        _focus()
    message = str(caught.value)
    assert message.startswith("window_focus_failed: 창은")
    assert "위치 문제가 아니라" in message and "windows_execute_preview" in message
