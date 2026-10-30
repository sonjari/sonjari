"""사람이 부른 손자리 크롬은 **정말** 앞으로 온다 (2026-10-30 · 대표 10-29 00:46 `/레시피` 에서 안 떴다).

윈도우는 뒤쪽 프로세스(예약 작업이 띄운 백엔드)의 `SetForegroundWindow` 를 막는다. 지금 앞창의 입력 스레드에 잠깐 이어야
허락된다 — 가짜 user32 로 그 규칙을 흉내 내 「이은 뒤에 올리고, 다 쓰면 끊는다」를 본다.
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="윈도우 창 관리")


class _User32:
    """윈도우의 앞창 잠금 흉내 — 앞창 스레드에 입력이 이어져 있을 때만 `SetForegroundWindow` 가 먹는다."""

    def __init__(self, front: int, chrome: int) -> None:
        self.front, self.chrome = front, chrome
        self.attached_to: set[int] = set()
        self.calls: list[tuple] = []

    def PeekMessageW(self, *args) -> int:  # noqa: N802
        return 0

    def GetForegroundWindow(self) -> int:  # noqa: N802
        return self.front

    def GetWindowThreadProcessId(self, hwnd: int, _pid) -> int:  # noqa: N802
        return 7000 + hwnd

    def AttachThreadInput(self, me: int, other: int, on: bool) -> int:  # noqa: N802
        self.calls.append(("attach", other, on))
        (self.attached_to.add if on else self.attached_to.discard)(other)
        return 1

    def BringWindowToTop(self, hwnd: int) -> int:  # noqa: N802
        return 1

    def SetForegroundWindow(self, hwnd: int) -> int:  # noqa: N802
        self.calls.append(("set", hwnd, bool(self.attached_to)))
        if self.attached_to:
            self.front = hwnd
            return 1
        return 0   # 막힘 — 작업 표시줄만 깜빡인다


def test_a_background_process_raises_chrome_by_joining_the_front_input() -> None:
    from alture_jarvis.browser import _raise_for_human

    user32 = _User32(front=11, chrome=22)
    raised, attached = _raise_for_human(user32, 22)

    assert raised and attached and user32.front == 22
    assert user32.calls == [("attach", 7011, True), ("set", 22, True), ("attach", 7011, False)], "올린 뒤에는 입력 잇기를 끊는다"


def test_already_in_front_touches_nothing() -> None:
    from alture_jarvis.browser import _raise_for_human

    user32 = _User32(front=22, chrome=22)
    assert _raise_for_human(user32, 22) == (True, False)
    assert user32.calls == []


def test_the_learning_stage_uses_this_path() -> None:
    """배우기 무대 · 「크롬 창 보기」가 같은 길(`_present_for_human(activate=True)`)을 쓰고, 그 길이 이 함수로 올린다."""
    import inspect

    from alture_jarvis import browser

    source = inspect.getsource(browser.BrowserWorker._present_for_human)
    assert "_raise_for_human(user32, hwnd)" in source
    assert "user32.SetForegroundWindow(hwnd)" not in source
