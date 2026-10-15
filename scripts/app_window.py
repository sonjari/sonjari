"""시험이 앱 창 크기를 정할 때 쓰는 문 — **창 자체**를 움직인다 (2026-09-16 밤).

전에는 CDP 로 WebView 의 뷰포트를 `set_viewport_size(1440, 900)` 으로 강제했다. 그러면 창을
최대화해도 안쪽 그림이 1440×900 에 묶여 오른쪽·아래가 **검게** 남는다. 시험 도중 사람이 그 창을
보고 「전체화면에서 레이아웃이 깨진다」고 짚었다 — 제품 고장이 아니라 시험이 창을 망가뜨린 것이었다.

그래서 뷰포트를 속이지 않고 **윈도우 창 크기**를 바꾼다. 사람이 최대화하면 앱이 정상으로 다시 그린다.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from pathlib import Path


def _exe_of(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def size_app_window(app_dir: Path, width: int, height: int, *, x: int = 40, y: int = 40) -> int:
    """`app_dir` 안의 exe 가 띄운 **보이는** 창들을 그 크기로 둔다. 움직인 창 수를 돌려준다."""
    user32 = ctypes.windll.user32
    root = str(app_dir).lower()
    moved = 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def visit(hwnd, _param):  # type: ignore[no-untyped-def]
        nonlocal moved
        if not user32.IsWindowVisible(hwnd) or not user32.GetWindowTextLengthW(hwnd):
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not _exe_of(int(pid.value)).lower().startswith(root):
            return True
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        # 트레이·보조 창은 건너뛴다. 단 **최소화된 창**은 크기가 160×28 로 읽히니 그걸로 거르면 안 된다.
        if not user32.IsIconic(hwnd) and rect.right - rect.left < 200:
            return True
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE — 최대화 상태면 크기가 안 먹는다
        user32.SetWindowPos(hwnd, 0, x, y, width, height, 0x0004)  # SWP_NOZORDER
        moved += 1
        return True

    user32.EnumWindows(visit, 0)
    return moved
