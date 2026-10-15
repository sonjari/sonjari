"""사람이 지금 이 PC 를 쓰고 있나 — 온텔릭이 화면을 앞으로 가져와도 되는지 (2026-09-16, 인수인계 H2-A).

## 왜

온텔릭에게 몇 분짜리 일을 시켜 두면 사람은 그동안 다른 것을 한다. 그때 온텔릭 크롬이 앞으로 튀어나오고
치던 글자가 끊기면 「같이 못 쓰는 프로그램」이 된다. Claude 가 일을 맡기는 하위 에이전트로 쓸 때는 더 그렇다 —
사람은 Claude 창에서 계속 대화하는 중이다.

## 규칙

- 최근 `active_sec` 초 안에 키보드·마우스 입력이 있었으면 **사람이 쓰는 중**이다.
- 쓰는 중이면 브라우저 창을 앞으로 가져오거나 최대화하지 않는다(일은 뒤에서 계속한다 — 화면은 작업 화면에 보인다).
- 창에 키를 보내는 조작은 포커스가 꼭 필요하다. 그때는 손이 멈출 때까지 **기다리고**, 끝내 안 멈추면 미룬다 —
  사람이 치는 글자와 섞이면 엉뚱한 창에 입력이 들어간다.

Windows 가 아니면 판단할 수 없으니 「안 쓰는 중」으로 본다(지금까지와 같은 동작).
`JARVIS_ASSUME_USER_ACTIVE=1` 은 실측용 — 늘 쓰는 중인 것처럼 굴어 뒤에서만 일할 때의 성공률을 잰다.
"""

from __future__ import annotations

import ctypes
import sys
import time
from typing import Any, Callable

from .config import setting

__all__ = ["idle_seconds", "UserPresence"]


def idle_seconds() -> float | None:
    """마지막 입력 뒤 지난 초. 잴 수 없으면 None."""
    if sys.platform != "win32":
        return None

    class _LastInput(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = _LastInput()
    info.cbSize = ctypes.sizeof(_LastInput)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    except Exception:  # noqa: BLE001 — 못 재면 판단하지 않는다
        return None
    # GetTickCount 는 49.7 일마다 0 으로 돈다. 차이도 같은 32비트로 계산한다.
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0


class UserPresence:
    def __init__(self, config: Any, *, idle: Callable[[], float | None] = idle_seconds,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self._idle = idle
        self._sleep = sleep
        self._clock = clock

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.config, "yield_to_user_enabled", True))

    def active(self) -> bool:
        """사람이 지금 쓰는 중인가."""
        if not self.enabled:
            return False
        if bool(getattr(self.config, "assume_user_active", False)) or setting("JARVIS_ASSUME_USER_ACTIVE") == "1":
            return True
        seconds = self._idle()
        if seconds is None:
            return False
        return seconds < float(getattr(self.config, "yield_to_user_active_sec", 10.0))

    def wait_until_idle(self, *, quiet_sec: float = 2.0, timeout_sec: float = 45.0) -> bool:
        """손이 `quiet_sec` 초 멈출 때까지 기다린다. 멈췄으면 True, 끝내 안 멈췄으면 False."""
        if not self.enabled:
            return True
        deadline = self._clock() + max(0.0, timeout_sec)
        while True:
            if bool(getattr(self.config, "assume_user_active", False)):
                return False
            seconds = self._idle()
            if seconds is None or seconds >= quiet_sec:
                return True
            if self._clock() >= deadline:
                return False
            self._sleep(min(0.5, max(0.05, quiet_sec - seconds)))
