# -*- coding: utf-8 -*-
"""윈도우 API 를 부를 때 쓰는 **우리만의** DLL 묶음 — 함수마다 값의 크기를 한 번만 정해 둔다 (2026-11-03).

왜 따로 두나(사고 기록 · 11-01 · 11-02 · 11-03 백엔드가 `python311.dll` 0xc0000005 로 통째로 죽음):
1. **함수 안에서 실행 중에 크기를 바꿨다.** `browser.py` 가 공용 `ctypes.windll.user32` 의 `restype` · `argtypes` 를
   크롬 감시 스레드 시작 때와 창 자리를 잡을 때마다 다시 넣었다. 다른 스레드가 같은 함수를 부르는 도중에 바꿔 끼우면
   파이썬 안쪽이 이미 놓은 값을 읽는다 → 이벤트 기록의 「python311.dll · 0xc0000005」. 11-01 과 11-03 은 같은 오프셋
   (0x1aaaeb)이었고 11-01 판은 `_process_name`(0.02초마다 도는 크롬 감시) 안에서 죽었다.
2. **크기를 안 정한 호출이 100개 가까이** 있었다 — 기본은 32비트 int 라 64비트 핸들 · 포인터 반환값이 잘린다.
3. 공용 `ctypes.windll` 은 pywinauto · comtypes 같은 남의 라이브러리도 같이 쓰고 그들도 크기를 바꾼다 — 섞이지 않게
   우리 것은 `ctypes.WinDLL(...)` 로 따로 연다.

쓰는 법: `from .winapi import user32` 또는 `from . import winapi; winapi.user32.IsWindow(h)`.
처음 꺼낼 때 한 번(잠금 안에서) 열고 크기를 다 정한다. 이 밖에서 `.restype` · `.argtypes` 를 넣지 않는다
(`tests/test_winapi_1103.py` 가 막는다). 새 함수를 부르려면 아래 표에 한 줄 더한다.

콜백을 받는 함수(EnumWindows · EnumDisplayMonitors · SetWinEventHook)는 파일마다 콜백 모양이 달라 **반환 크기만** 정한다.
"""
from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes as wt
from typing import Any

_V = ctypes.c_void_p        # 핸들 · 포인터 · byref · 버퍼 — None · int · byref · 배열을 다 받는다
_LRESULT = ctypes.c_ssize_t
_KEEP = object()            # argtypes 를 정하지 않음(콜백 · 문자열을 받는 함수)

# (dll, 함수) → (restype, argtypes)
SIGNATURES: dict[tuple[str, str], tuple[Any, Any]] = {
    # ── user32 ──
    ("user32", "AttachThreadInput"): (wt.BOOL, (wt.DWORD, wt.DWORD, wt.BOOL)),
    ("user32", "BringWindowToTop"): (wt.BOOL, (_V,)),
    ("user32", "DispatchMessageW"): (_LRESULT, (_V,)),
    ("user32", "EnumDisplayMonitors"): (wt.BOOL, _KEEP),
    ("user32", "EnumWindows"): (wt.BOOL, _KEEP),
    ("user32", "FlashWindowEx"): (wt.BOOL, (_V,)),
    ("user32", "GetAncestor"): (_V, (_V, wt.UINT)),
    ("user32", "GetAsyncKeyState"): (ctypes.c_short, (ctypes.c_int,)),
    ("user32", "GetClassNameW"): (ctypes.c_int, (_V, _V, ctypes.c_int)),
    ("user32", "GetCursorPos"): (wt.BOOL, (_V,)),
    ("user32", "GetForegroundWindow"): (_V, ()),
    ("user32", "GetLastInputInfo"): (wt.BOOL, (_V,)),
    ("user32", "GetLayeredWindowAttributes"): (wt.BOOL, (_V, _V, _V, _V)),
    ("user32", "GetMonitorInfoW"): (wt.BOOL, (_V, _V)),
    ("user32", "GetSystemMetrics"): (ctypes.c_int, (ctypes.c_int,)),
    ("user32", "GetTopWindow"): (_V, (_V,)),
    ("user32", "GetWindow"): (_V, (_V, wt.UINT)),
    ("user32", "GetWindowDC"): (_V, (_V,)),
    ("user32", "GetWindowLongW"): (ctypes.c_long, (_V, ctypes.c_int)),
    ("user32", "GetWindowRect"): (wt.BOOL, (_V, _V)),
    ("user32", "GetWindowTextLengthW"): (ctypes.c_int, (_V,)),
    ("user32", "GetWindowTextW"): (ctypes.c_int, (_V, _V, ctypes.c_int)),
    ("user32", "GetWindowThreadProcessId"): (wt.DWORD, (_V, _V)),
    ("user32", "IsIconic"): (wt.BOOL, (_V,)),
    ("user32", "IsWindow"): (wt.BOOL, (_V,)),
    ("user32", "IsWindowVisible"): (wt.BOOL, (_V,)),
    ("user32", "IsZoomed"): (wt.BOOL, (_V,)),
    ("user32", "MonitorFromRect"): (_V, (_V, wt.DWORD)),
    ("user32", "MonitorFromWindow"): (_V, (_V, wt.DWORD)),
    ("user32", "PeekMessageW"): (wt.BOOL, (_V, _V, wt.UINT, wt.UINT, wt.UINT)),
    ("user32", "PrintWindow"): (wt.BOOL, (_V, _V, wt.UINT)),
    ("user32", "ReleaseDC"): (ctypes.c_int, (_V, _V)),
    ("user32", "SendMessageTimeoutW"): (_LRESULT, _KEEP),
    ("user32", "SetForegroundWindow"): (wt.BOOL, (_V,)),
    ("user32", "SetLayeredWindowAttributes"): (wt.BOOL, (_V, wt.DWORD, wt.BYTE, wt.DWORD)),
    ("user32", "SetWinEventHook"): (_V, _KEEP),
    ("user32", "SetWindowLongW"): (ctypes.c_long, (_V, ctypes.c_int, ctypes.c_long)),
    ("user32", "SetWindowPos"): (wt.BOOL, (_V, _V, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT)),
    ("user32", "ShowWindow"): (wt.BOOL, (_V, ctypes.c_int)),
    ("user32", "TranslateMessage"): (wt.BOOL, (_V,)),
    ("user32", "UnhookWinEvent"): (wt.BOOL, (_V,)),
    ("user32", "WindowFromPoint"): (_V, (wt.POINT,)),
    # ── kernel32 ──
    ("kernel32", "CloseHandle"): (wt.BOOL, (_V,)),
    ("kernel32", "GetCurrentThreadId"): (wt.DWORD, ()),
    ("kernel32", "GetTickCount"): (wt.DWORD, ()),
    ("kernel32", "GetUserDefaultUILanguage"): (wt.WORD, ()),
    ("kernel32", "GlobalMemoryStatusEx"): (wt.BOOL, (_V,)),
    ("kernel32", "LocalFree"): (_V, (_V,)),
    ("kernel32", "OpenProcess"): (_V, (wt.DWORD, wt.BOOL, wt.DWORD)),
    ("kernel32", "QueryFullProcessImageNameW"): (wt.BOOL, (_V, wt.DWORD, _V, _V)),
    # ── gdi32 ──
    ("gdi32", "CreateCompatibleBitmap"): (_V, (_V, ctypes.c_int, ctypes.c_int)),
    ("gdi32", "CreateCompatibleDC"): (_V, (_V,)),
    ("gdi32", "DeleteDC"): (wt.BOOL, (_V,)),
    ("gdi32", "DeleteObject"): (wt.BOOL, (_V,)),
    ("gdi32", "GetDIBits"): (ctypes.c_int, (_V, _V, wt.UINT, wt.UINT, _V, _V, wt.UINT)),
    ("gdi32", "SelectObject"): (_V, (_V, _V)),
    # ── 그 밖 ──
    ("advapi32", "GetTokenInformation"): (wt.BOOL, (_V, ctypes.c_int, _V, wt.DWORD, _V)),
    ("advapi32", "OpenProcessToken"): (wt.BOOL, (_V, wt.DWORD, _V)),
    ("ntdll", "NtQuerySystemInformation"): (ctypes.c_long, (wt.ULONG, _V, wt.ULONG, _V)),
    ("shlwapi", "AssocQueryStringW"): (ctypes.c_long, _KEEP),
    ("crypt32", "CryptProtectData"): (wt.BOOL, _KEEP),
    ("crypt32", "CryptUnprotectData"): (wt.BOOL, _KEEP),
}

_DLLS = ("user32", "kernel32", "gdi32", "advapi32", "ntdll", "shlwapi", "crypt32")
_lock = threading.Lock()
_opened: dict[str, Any] = {}


def _open(name: str) -> Any:
    with _lock:
        lib = _opened.get(name)
        if lib is not None:
            return lib
        if sys.platform != "win32":
            raise AttributeError(f"winapi.{name}: 윈도우에서만 씁니다")
        lib = ctypes.WinDLL(name, use_last_error=True)
        for (dll, fn), (restype, argtypes) in SIGNATURES.items():
            if dll != name:
                continue
            func = getattr(lib, fn)
            func.restype = restype
            if argtypes is not _KEEP:
                func.argtypes = list(argtypes)
        _opened[name] = lib
        return lib


def __getattr__(name: str) -> Any:   # PEP 562 — `winapi.user32` 를 처음 꺼낼 때 연다
    if name in _DLLS:
        return _open(name)
    raise AttributeError(name)
