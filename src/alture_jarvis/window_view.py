"""창이 **어느 모니터 위에 있는가** — 화면 밖 창을 주 모니터로 데려오고, 못 할 때는 까닭을 정확히 말한다.

★ 2026-10-19 판 ae395490(디스코드로 「클로드 앱의 원격 제어를 켜 줘」). 손자리가 Claude 앱 창을 앞으로 가져오지 못했고
  (`window_focus_failed`), 비전 좌표도 두 번 범위 밖이었다(`visual_coordinate_out_of_bounds`). 모델은 창 좌표 -1928 을 보고
  「창이 화면 왼쪽 밖에 있다」고 **스스로 결론**을 내고 Alt+Space → 이동 · 최대화를 헤매다 사람에게 넘겼다.
  기록을 다시 보니 그 창은 화면 밖이 아니었다 — 이 PC 의 **왼쪽 보조 모니터**(-1920~0)에 최대화돼 있었고(-1928,-8 은 최대화 창의
  여백 8px), 같은 판의 캡처에는 앱 화면이 그대로 찍혀 있다. 도구가 「창은 어느 모니터 안에 있다 / 밖에 있다」를 말해 주지
  않으니 모델이 좌표 하나로 짐작했다.

  그래서 여기서 둘을 한다.
  1. **정말 화면 밖이면 옮긴다** — 꺼지거나 뽑힌 모니터 자리에 남은 창(일렉트론 앱은 마지막 자리를 기억해 거기에 다시 뜬다).
     보이는 넓이가 절반 미만이면 주 모니터 작업 영역(작업 표시줄 뺀 자리)으로 옮긴다. 크기가 맞으면 그대로, 크면 작업 영역에 맞춘다.
     **다른 모니터에 제대로 떠 있는 창은 건드리지 않는다** — 사람이 일부러 둔 자리다.
  2. **어디 있는지 말한다** — 앞으로 가져오기가 실패하면 「창은 보조 모니터 안에 있다, 위치 문제가 아니다」를 같이 돌려준다.

  창을 옮기는 것은 눈에 보이는 변화다. 그래서 **읽기(L0) 도구에서는 하지 않고**, 이미 창을 바꾸는 L1 걸음(창 앞으로 가져오기 ·
  UIA/비전 미리보기)에서만 한다 — 최소화된 창을 펼치는 것(`windows_focus_window` 가 원래 하던 일)과 같은 등급이다. 옮겼으면
  증거에 「어디서 → 어디로」를 남긴다(되돌릴 자리도 그것이다).

좌표 계산은 순수 함수(`plan_into_view` 등)로 두고, 실제 Win32 호출은 `Desktop` 하나로 모았다 — 시험은 가짜 모니터 · 창으로 돈다.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

#: 보이는 넓이가 이 비율 **미만**일 때만 옮긴다. 반쯤 걸친 창은 사람이 그렇게 둔 것일 수 있다.
MIN_VISIBLE = 0.5
#: 최소화된 창의 윈도우 좌표(-32000). 화면 밖으로 세지 않고 「펼치기」로 다룬다.
_MINIMIZED_COORD = -32000


@dataclass(frozen=True, slots=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def area(self) -> int:
        return self.width * self.height

    def overlap(self, other: "Rect") -> int:
        width = min(self.right, other.right) - max(self.left, other.left)
        height = min(self.bottom, other.bottom) - max(self.top, other.top)
        return width * height if width > 0 and height > 0 else 0

    def as_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "right": self.right, "bottom": self.bottom}

    def corner(self) -> str:
        return f"{self.left},{self.top}"


@dataclass(frozen=True, slots=True)
class Monitor:
    rect: Rect
    work: Rect
    primary: bool


def visible_fraction(rect: Rect, monitors: list[Monitor]) -> float:
    """창 넓이 중 어느 모니터든 위에 있는 몫(0~1). 모니터끼리는 겹치지 않는다(윈도우 가상 화면)."""
    if rect.area <= 0:
        return 0.0
    covered = sum(rect.overlap(monitor.rect) for monitor in monitors)
    return min(1.0, covered / rect.area)


def home_monitor(rect: Rect, monitors: list[Monitor]) -> tuple[int, Monitor] | None:
    """가장 많이 겹치는 모니터(번호는 1부터). 어느 모니터와도 안 겹치면 None."""
    best: tuple[int, Monitor] | None = None
    best_overlap = 0
    for index, monitor in enumerate(monitors, start=1):
        shared = rect.overlap(monitor.rect)
        if shared > best_overlap:
            best, best_overlap = (index, monitor), shared
    return best


def primary_monitor(monitors: list[Monitor]) -> Monitor | None:
    for monitor in monitors:
        if monitor.primary:
            return monitor
    return monitors[0] if monitors else None


def plan_into_view(rect: Rect, monitors: list[Monitor], *, min_visible: float = MIN_VISIBLE) -> Rect | None:
    """옮길 자리. 이미 충분히 보이면(또는 모니터를 모르면) None — 옮기지 않는다.

    크기가 주 모니터 작업 영역에 들어가면 그 크기 그대로 가운데에, 크면 작업 영역 크기로 줄여 둔다.
    """
    primary = primary_monitor(monitors)
    if primary is None or rect.area <= 0:
        return None
    if visible_fraction(rect, monitors) >= min_visible:
        return None
    work = primary.work if primary.work.area > 0 else primary.rect
    width = min(rect.width, work.width)
    height = min(rect.height, work.height)
    left = work.left + (work.width - width) // 2
    top = work.top + (work.height - height) // 2
    return Rect(left, top, left + width, top + height)


def where(rect: Rect, monitors: list[Monitor]) -> str:
    """모델에게 줄 한 마디 — 「주 모니터 안」 · 「보조 모니터 2(-1920,0~0,1080) 안」 · 「화면 밖(-1928,-8)」."""
    if rect.left <= _MINIMIZED_COORD + 1000 and rect.top <= _MINIMIZED_COORD + 1000:
        return "최소화된 상태"
    found = home_monitor(rect, monitors)
    if found is None or visible_fraction(rect, monitors) < MIN_VISIBLE:
        return f"화면 밖({rect.corner()})"
    index, monitor = found
    if monitor.primary:
        return "주 모니터 안"
    box = monitor.rect
    return f"보조 모니터 {index}({box.left},{box.top}~{box.right},{box.bottom}) 안"


class Desktop(Protocol):
    """창 · 모니터를 읽고 바꾸는 최소한의 손잡이. 실제는 `Win32Desktop`, 시험은 가짜."""

    def monitors(self) -> list[Monitor]: ...
    def rect(self, hwnd: int) -> Rect: ...
    def is_minimized(self, hwnd: int) -> bool: ...
    def is_maximized(self, hwnd: int) -> bool: ...
    def restore(self, hwnd: int) -> None: ...
    def move(self, hwnd: int, rect: Rect) -> bool: ...


class Win32Desktop:
    """user32 를 ctypes 로 부른다. 같은 프로세스 안에서 창 좌표와 모니터 좌표는 같은 DPI 기준으로 온다."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user32 = ctypes.windll.user32

    def monitors(self) -> list[Monitor]:
        ctypes, wintypes = self._ctypes, self._wintypes

        class _MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        found: list[Monitor] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                                           ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        def collect(handle: Any, _dc: Any, _rect: Any, _data: Any) -> int:
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            if self._user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                box, work = info.rcMonitor, info.rcWork
                found.append(Monitor(Rect(box.left, box.top, box.right, box.bottom),
                                     Rect(work.left, work.top, work.right, work.bottom),
                                     bool(info.dwFlags & 1)))  # MONITORINFOF_PRIMARY
            return 1

        self._user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
        return found

    def rect(self, hwnd: int) -> Rect:
        box = self._wintypes.RECT()
        if not self._user32.GetWindowRect(self._wintypes.HWND(hwnd), self._ctypes.byref(box)):
            return Rect(0, 0, 0, 0)
        return Rect(box.left, box.top, box.right, box.bottom)

    def is_minimized(self, hwnd: int) -> bool:
        return bool(self._user32.IsIconic(self._wintypes.HWND(hwnd)))

    def is_maximized(self, hwnd: int) -> bool:
        return bool(self._user32.IsZoomed(self._wintypes.HWND(hwnd)))

    def restore(self, hwnd: int) -> None:
        self._user32.ShowWindow(self._wintypes.HWND(hwnd), 9)  # SW_RESTORE — `focus_window` 가 원래 쓰던 것과 같다

    def move(self, hwnd: int, rect: Rect) -> bool:
        # SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER — 자리 · 크기만 바꾼다. 앞으로 가져오기는 부른 쪽이 따로 한다.
        flags = 0x0004 | 0x0010 | 0x0200
        return bool(self._user32.SetWindowPos(self._wintypes.HWND(hwnd), None, rect.left, rect.top,
                                              rect.width, rect.height, flags))


def desktop() -> Desktop | None:
    """이 PC 의 데스크톱. 윈도우가 아니면 None — 옮길 것도 말할 것도 없다. 시험은 이 함수를 갈아 끼운다."""
    if os.name != "nt":
        return None
    try:
        return Win32Desktop()
    except Exception:
        return None


def describe(hwnd: int, desk: Desktop | None = None) -> dict[str, Any]:
    """창이 어디 있는지만 읽는다(바꾸지 않는다). 실패 문장에 붙일 재료."""
    desk = desk if desk is not None else desktop()
    if desk is None:
        return {}
    try:
        rect, monitors = desk.rect(hwnd), desk.monitors()
    except Exception:
        return {}
    return {
        "rect": rect.as_dict(),
        "where": where(rect, monitors),
        "visible_fraction": round(visible_fraction(rect, monitors), 3),
        "off_screen": rect.area > 0 and not desk.is_minimized(hwnd) and visible_fraction(rect, monitors) < MIN_VISIBLE,
    }


def needs_bringing(hwnd: int, desk: Desktop | None = None) -> bool:
    """최소화됐거나 화면 밖인가 — 손을 대기 전에 싸게 묻는다(사람 손 기다리기는 이게 참일 때만)."""
    desk = desk if desk is not None else desktop()
    if desk is None:
        return False
    try:
        if desk.is_minimized(hwnd):
            return True
        return plan_into_view(desk.rect(hwnd), desk.monitors()) is not None
    except Exception:
        return False


def bring_into_view(hwnd: int, desk: Desktop | None = None, *, settle_sec: float = 0.15) -> dict[str, Any]:
    """최소화면 펼치고, 화면 밖이면 주 모니터로 옮긴다. 이미 잘 보이는 창은 **손대지 않는다**.

    돌려주는 것(증거에 그대로 싣는다):
      - `restored` — 최소화를 풀었다
      - `moved_into_view` — {"from", "to", "monitor"} 옮긴 자리. 사람이 되돌릴 때 쓸 원래 자리도 여기 있다
      - `still_off_screen` — 옮기려 했는데 여전히 밖이다(부른 쪽이 그 사실을 실패 문장으로 말한다)
      - `note` — 한국어 한 줄(「창이 화면 밖(-1928,-8)에 있어 주 모니터로 옮겼습니다」)
    """
    desk = desk if desk is not None else desktop()
    if desk is None:
        return {}
    out: dict[str, Any] = {}
    notes: list[str] = []
    if desk.is_minimized(hwnd):
        desk.restore(hwnd)
        if settle_sec:
            time.sleep(settle_sec)
        if desk.is_minimized(hwnd):
            # 펼쳐지지 않았다 — 최소화 좌표(-32000)를 「화면 밖」으로 착각해 옮기지 않는다.
            return {"restored": False, "still_minimized": True,
                    "note": "창이 최소화돼 있는데 펼치지 못했습니다."}
        out["restored"] = True
        notes.append("창이 최소화돼 있어 펼쳤습니다.")
    monitors = desk.monitors()
    before = desk.rect(hwnd)
    target = plan_into_view(before, monitors)
    if target is None:
        if notes:
            out["note"] = " ".join(notes)
        return out
    if desk.is_maximized(hwnd):
        # 최대화된 채로는 자리를 못 옮긴다(윈도우가 최대화 자리로 되돌린다). 먼저 풀고, 풀린 크기로 다시 잰다.
        desk.restore(hwnd)
        if settle_sec:
            time.sleep(settle_sec)
        restored_rect = desk.rect(hwnd)
        target = plan_into_view(restored_rect, monitors)
        if target is None:
            out["moved_into_view"] = {"from": before.as_dict(), "to": restored_rect.as_dict(), "monitor": "주 모니터",
                                      "unmaximized": True}
            notes.append(f"창이 화면 밖({before.corner()})에 최대화돼 있어 최대화를 풀었습니다.")
            out["note"] = " ".join(notes)
            return out
    desk.move(hwnd, target)
    if settle_sec:
        time.sleep(settle_sec)
    after = desk.rect(hwnd)
    if visible_fraction(after, monitors) < MIN_VISIBLE:
        out["still_off_screen"] = True
        out["rect"] = after.as_dict()
        notes.append(f"창이 화면 밖({before.corner()})에 있어 주 모니터로 옮기려 했지만 옮겨지지 않았습니다.")
        out["note"] = " ".join(notes)
        return out
    fitted = after.width < before.width or after.height < before.height
    out["moved_into_view"] = {"from": before.as_dict(), "to": after.as_dict(), "monitor": "주 모니터",
                              **({"resized_to_fit": True} if fitted else {})}
    notes.append(f"창이 화면 밖({before.corner()})에 있어 주 모니터로 옮겼습니다"
                 + ("(화면보다 커서 크기를 맞췄습니다)." if fitted else "."))
    out["note"] = " ".join(notes)
    return out
