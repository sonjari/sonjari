"""유니티 무대 — 사람이 쓰는 유니티 에디터 창을 온텔릭 창 **안에** 비춘다 (2026-09-27 · 게임 팩 2단계).

## 왜 이렇게

브라우저 무대(`live_view.py`)는 크롬을 화면 밖에 두고 그 그림을 받았다. 유니티는 사람이 **실제로 쓰는** 창이라
밖으로 치울 수 없다. 그래서 창은 그대로 두고, 창이 그린 것만 복사해 온다:

- `PrintWindow(hwnd, PW_RENDERFULLCONTENT)` — 창이 **다른 창에 가려져 있어도** DWM 이 가진 그림을 받는다.
  창을 앞으로 끌어오지 않고, 포커스를 건드리지 않는다(API 가 그런 일을 안 한다 — 그래도 잰다: `measure_focus`).
- 최소화된 창은 그림이 없다. 그때는 「최소화돼 있다」고 말한다(검은 그림을 보여 주지 않는다).
- 보는 사람이 있을 때만 찍는다(6초 동안 아무도 안 당기면 멈춘다). 한 장 찍는 데 드는 것은 수~수십 ms.

## 직접 하기

사람이 「직접 하기」를 누르면 유니티 창을 **앞으로** 가져온다. 이것이 유일하게 창을 움직이는 길이고, 사람이 누른 것만.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import os
import threading
import time
from typing import Any, Callable

WATCH_IDLE_SEC = 6.0
MIN_INTERVAL_SEC = 0.2
PW_RENDERFULLCONTENT = 0x00000002
_DPI_PER_MONITOR_V2 = ctypes.c_void_p(-4)


def _user32() -> Any:
    return ctypes.windll.user32  # type: ignore[attr-defined]


def _process_name(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = ctypes.c_uint32(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


class _DpiAware:
    """이 스레드만 모니터별 DPI 로 — 백엔드 전체의 DPI 설정은 건드리지 않는다(브라우저 좌표 등이 바뀐다)."""

    def __enter__(self) -> "_DpiAware":
        try:
            self._old = _user32().SetThreadDpiAwarenessContext(_DPI_PER_MONITOR_V2)
        except (AttributeError, OSError):
            self._old = None
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._old:
            try:
                _user32().SetThreadDpiAwarenessContext(ctypes.c_void_p(self._old))
            except (AttributeError, OSError):
                pass


def unity_windows() -> list[dict[str, Any]]:
    """떠 있는 유니티 에디터 창(프로세스 `Unity.exe` 의 보이는 최상위 창). 큰 것부터."""
    if os.name != "nt":
        return []
    user32 = _user32()
    rows: list[dict[str, Any]] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    def visit(hwnd: int, _param: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER — 딸린 창(대화 상자)은 뺀다
            return True
        pid = ctypes.c_uint32()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if _process_name(pid.value).lower() != "unity.exe":
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        rows.append({
            "hwnd": int(hwnd), "pid": int(pid.value), "title": title.value,
            "width": rect.right - rect.left, "height": rect.bottom - rect.top,
            "minimized": bool(user32.IsIconic(hwnd)),
        })
        return True

    with _DpiAware():
        user32.EnumWindows(proto(visit), 0)
    # 최소화된 창은 크기가 작게(좌표 -32000) 잡힌다 — 크기로 거르지 않고 그대로 둔다.
    rows = [row for row in rows if row["title"] and (row["minimized"] or (row["width"] > 200 and row["height"] > 150))]
    rows.sort(key=lambda row: row["width"] * row["height"], reverse=True)
    return rows


def capture(hwnd: int, max_width: int = 1600, quality: int = 72) -> tuple[bytes, int, int]:
    """창 하나를 JPEG 로. 창을 움직이지 않는다."""
    from PIL import Image

    user32 = _user32()
    gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                    ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
                    ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]

    with _DpiAware():
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            raise RuntimeError("unity_window_empty")
        window_dc = user32.GetWindowDC(hwnd)
        memory_dc = gdi32.CreateCompatibleDC(window_dc)
        bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        old = gdi32.SelectObject(memory_dc, bitmap)
        try:
            if not user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT):
                raise RuntimeError("unity_print_window_failed")
            header = BITMAPINFOHEADER()
            header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            header.biWidth, header.biHeight = width, -height  # 위에서 아래로
            header.biPlanes, header.biBitCount, header.biCompression = 1, 32, 0
            buffer = ctypes.create_string_buffer(width * height * 4)
            gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        finally:
            gdi32.SelectObject(memory_dc, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(hwnd, window_dc)
    image = Image.frombuffer("RGB", (width, height), buffer.raw, "raw", "BGRX", 0, 1)
    if width > max_width:
        image = image.resize((max_width, round(height * max_width / width)), Image.BILINEAR)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality)
    return out.getvalue(), image.width, image.height


def bring_to_front(hwnd: int) -> bool:
    """사람이 「직접 하기」를 눌렀을 때만. 최소화돼 있으면 되살리고 앞으로."""
    user32 = _user32()
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    foreground = user32.GetForegroundWindow()
    current = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached = bool(other and other != current and user32.AttachThreadInput(current, other, True))
    try:
        user32.BringWindowToTop(hwnd)
        return bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(current, other, False)


class UnityStage:
    """유니티 창 한 장씩. 브라우저 무대와 같은 모양(`frame(after, wait)`)이라 화면 쪽이 같은 틀을 쓴다."""

    def __init__(
        self,
        *,
        find: Callable[[], list[dict[str, Any]]] = unity_windows,
        grab: Callable[[int], tuple[bytes, int, int]] = capture,
        front: Callable[[int], bool] = bring_to_front,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._find, self._grab, self._front, self.clock = find, grab, front, clock
        self._lock = threading.Lock()
        self._frame: dict[str, Any] | None = None
        self._digest = ""
        self._seq = 0
        self._last_at = float("-inf")  # 첫 장은 기다리지 않는다
        self._watch_until = 0.0
        self._problem = ""

    def _window(self, project_hint: str = "") -> dict[str, Any] | None:
        rows = self._find()
        if project_hint:
            hint = project_hint.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
            named = [row for row in rows if hint and hint in row["title"].lower()]
            if named:
                return named[0]
        return rows[0] if rows else None

    def status(self, project_hint: str = "") -> dict[str, Any]:
        window = self._window(project_hint)
        if window is None:
            return {"status": "no_editor", "text": "떠 있는 유니티 에디터 창이 없습니다."}
        if window["minimized"]:
            return {"status": "minimized", "title": window["title"], "text": "유니티 창이 최소화돼 있어 비출 수 없습니다."}
        return {"status": "ready", "title": window["title"], "width": window["width"], "height": window["height"],
                "watching": self.clock() < self._watch_until}

    def frame(self, after: int = 0, wait: float = 1.0, project_hint: str = "") -> dict[str, Any] | None:
        """새 장이 있으면 준다. `after` 보다 새 것이 없으면 잠깐 기다렸다가 None."""
        self._watch_until = self.clock() + WATCH_IDLE_SEC
        deadline = self.clock() + max(0.0, min(float(wait), 5.0))
        while True:
            with self._lock:
                if self.clock() - self._last_at >= MIN_INTERVAL_SEC:
                    self._shoot(project_hint)
                if self._frame is not None and self._frame["seq"] > after:
                    return self._frame
            if self.clock() >= deadline:
                return None
            time.sleep(MIN_INTERVAL_SEC)

    def _shoot(self, project_hint: str) -> None:
        self._last_at = self.clock()
        window = self._window(project_hint)
        if window is None or window["minimized"]:
            self._problem = "no_editor" if window is None else "minimized"
            return
        try:
            jpeg, width, height = self._grab(window["hwnd"])
        except Exception as exc:  # noqa: BLE001 — 한 장 실패로 무대가 죽으면 안 된다
            self._problem = f"capture_failed: {type(exc).__name__}"
            return
        self._problem = ""
        digest = hashlib.sha1(jpeg).hexdigest()
        if digest == self._digest:
            return  # 그대로면 새 장을 만들지 않는다 — 받는 쪽이 같은 그림을 또 그리지 않게
        self._digest = digest
        self._seq += 1
        self._frame = {"seq": self._seq, "jpeg": jpeg, "width": width, "height": height, "title": window["title"]}

    @property
    def problem(self) -> str:
        return self._problem

    def take_over(self, project_hint: str = "") -> dict[str, Any]:
        window = self._window(project_hint)
        if window is None:
            return {"ok": False, "error": "no_editor"}
        return {"ok": self._front(window["hwnd"]), "title": window["title"]}


def measure_focus(stage: UnityStage, seconds: float = 20.0, *, sample_sec: float = 0.1) -> dict[str, Any]:
    """무대를 돌리는 동안 **앞창이 바뀐 횟수**와, 그중 유니티가 앞으로 나온 횟수를 센다.

    사람이 PC 를 쓰는 중이면 앞창은 사람 때문에도 바뀐다 — 그래서 바뀐 순간 직전의 마지막 입력 시각을 같이 적는다
    (09-24 교훈: 가만히 둔 판만 재면 0초가 나오고, 사람이 쓰면 다른 숫자가 나온다).
    """
    user32 = _user32()

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint32)]

    def idle_ms() -> int:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        user32.GetLastInputInfo(ctypes.byref(info))
        return int(ctypes.windll.kernel32.GetTickCount() - info.dwTime)  # type: ignore[attr-defined]

    unity = {row["hwnd"] for row in unity_windows()}
    changes: list[dict[str, Any]] = []
    frames = 0
    seq = 0
    last = user32.GetForegroundWindow()
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        got = stage.frame(after=seq, wait=0)
        if got is not None:
            seq = got["seq"]
            frames += 1
        now = user32.GetForegroundWindow()
        if now != last:
            changes.append({"at": round(time.monotonic() - started, 2), "to_unity": now in unity, "input_idle_ms": idle_ms()})
            last = now
        time.sleep(sample_sec)
    by_us = [row for row in changes if row["to_unity"] and row["input_idle_ms"] > 1500]
    return {"seconds": seconds, "frames": frames, "foreground_changes": len(changes),
            "unity_came_forward_without_input": len(by_us), "changes": changes[:40]}


__all__ = ["UnityStage", "bring_to_front", "capture", "measure_focus", "unity_windows"]
