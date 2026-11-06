# -*- coding: utf-8 -*-
"""윈도우 API 크기 정의는 winapi.py 한 곳에서만 (2026-11-03 백엔드 0xc0000005 사고).

막는 것(양방향):
- 하면 안 됨: winapi.py 밖에서 공용 `ctypes.windll.<dll>` 을 부르기 · 함수의 `.restype` / `.argtypes` 를 실행 중에 바꾸기
- 해야 함: 우리 코드가 winapi 로 부르는 함수는 모두 SIGNATURES 에 있다(크기 안 정한 호출 0)
- 실제 윈도우에서 불러 본다: 64비트 핸들 · byref · 버퍼 · 구조체 값 넘기기가 그대로 된다
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"
# 자기만의 WinDLL 을 그 자리에서 열어 쓰는 파일(공용 객체를 안 건드림) · 동적 이름(msix)
LOCAL_DLL_OK = {"winapi.py", "process_census.py", "store_owner.py", "voice.py", "msvc_runtime.py", "msix.py"}


def _py_files():
    return [p for p in SRC.rglob("*.py") if "gemma_bundle" not in p.parts]


def test_no_shared_windll_outside_winapi():
    bad = []
    for p in _py_files():
        if p.name in LOCAL_DLL_OK:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"ctypes\.windll\.", line) and not line.lstrip().startswith("#"):
                bad.append(f"{p.name}:{i}")
    assert not bad, f"공용 ctypes.windll 을 직접 부름 — winapi 를 쓰세요: {bad}"


def test_no_runtime_signature_changes_outside_winapi():
    bad = []
    for p in _py_files():
        if p.name in LOCAL_DLL_OK:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"\.(argtypes|restype)\s*=", line) and not line.lstrip().startswith("#"):
                bad.append(f"{p.name}:{i}")
    assert not bad, f"실행 중에 restype/argtypes 를 바꿈(스레드끼리 다투다 죽는다): {bad}"


def test_every_called_function_is_declared():
    from alture_jarvis.winapi import SIGNATURES

    declared = {fn for (_dll, fn) in SIGNATURES}
    alias = re.compile(r"\b(?:winapi\.(?:user32|kernel32|gdi32|advapi32|ntdll|shlwapi|crypt32)"
                       r"|user32|kernel32|gdi32|advapi32|crypt32|self\._user32)\.([A-Z]\w+)\s*\(")
    missing = set()
    for p in _py_files():
        if p.name in LOCAL_DLL_OK:
            continue
        missing |= {m.group(1) for m in alias.finditer(p.read_text(encoding="utf-8", errors="ignore"))} - declared
    assert not missing, f"winapi.SIGNATURES 에 없는 함수를 부름: {sorted(missing)}"


@pytest.mark.skipif(sys.platform != "win32", reason="윈도우 전용")
def test_real_calls_on_windows():
    import ctypes
    from ctypes import wintypes as wt

    from alture_jarvis import winapi

    k, u = winapi.kernel32, winapi.user32
    # 자기 프로세스 이름 읽기 — 크롬 감시가 0.02초마다 하는 그 길(_process_name)
    handle = k.OpenProcess(0x1000, False, os.getpid())
    assert handle and isinstance(handle, int)
    size = wt.DWORD(260)
    buf = ctypes.create_unicode_buffer(260)
    assert k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
    assert buf.value.lower().endswith(".exe")
    assert k.CloseHandle(handle)
    # 창 핸들 · 구조체 byref · 구조체 값 넘기기 · NULL 은 None
    fg = u.GetForegroundWindow()
    assert fg is None or isinstance(fg, int)
    rect = wt.RECT()
    if fg:
        assert u.GetWindowRect(fg, ctypes.byref(rect)) in (0, 1)
    pt = wt.POINT(1, 1)
    hwnd = u.WindowFromPoint(pt)
    assert hwnd is None or isinstance(hwnd, int)
    assert u.MonitorFromWindow(None, 0) is None          # MONITOR_DEFAULTTONULL · 창 없음
    assert isinstance(k.GetTickCount(), int) and k.GetTickCount() >= 0
    # 같은 객체가 돌아온다(한 번만 열고 크기를 정한다)
    assert winapi.user32 is u
    # 공용 windll 과 섞이지 않는다
    assert u is not ctypes.windll.user32


@pytest.mark.skipif(sys.platform != "win32", reason="윈도우 전용")
def test_many_threads_calling_at_once_do_not_crash():
    """11-03 사고의 모양: 여러 스레드가 같은 함수를 동시에 부른다(이제는 아무도 크기를 바꾸지 않는다)."""
    import threading

    from alture_jarvis import winapi

    errors: list[str] = []

    def hammer() -> None:
        try:
            for _ in range(2000):
                h = winapi.kernel32.OpenProcess(0x1000, False, os.getpid())
                if h:
                    winapi.kernel32.CloseHandle(h)
                winapi.user32.GetForegroundWindow()
        except Exception as error:  # noqa: BLE001
            errors.append(repr(error))

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
