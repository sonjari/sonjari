"""가장 새 MSVC C++ 런타임(`msvcp140.dll`)을 **맨 먼저** 올린다 (2026-09-24).

왜 있나: 노트북 포장본에서 음성 버튼을 누르자 백엔드가 `MSVCP140.dll` 안에서 접근 위반(0xc0000005)으로
죽었다. `winrt`(말할 때 음악 멈추기) 휠이 **옛 런타임 14.29** 를 자기 폴더에 싣고 오고, 그게 먼저 올라간 뒤
음성 인식 엔진(ctranslate2, 14.40 이상으로 빌드)이 들어오면서 잠금(std::mutex)에서 죽는다.
윈도우의 한 프로세스에는 같은 이름 DLL 이 사실상 하나만 쓰이므로 **먼저 올라간 것이 이긴다.**

재현(개발 PC, System32 는 14.44 인데도): winrt 먼저 → whisper 올리기 2/2 비정상 종료(139),
14.44 를 먼저 올려 두면 2/2 받아쓰기까지 정상. 개발 PC 에서 안 보였던 건 불러오는 **순서**가 달라서다.

그래서 백엔드가 뜨자마자(패키지 `__init__`) 보이는 후보 중 **가장 새 것**을 먼저 올린다.
포장본은 빌드가 14.40 이상을 파이썬 폴더에 넣어 둔다(`build_app_package.ps1`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_loaded: str = ""


def file_version(path: Path) -> tuple[int, int, int, int]:
    """DLL 의 파일 버전. 못 읽으면 (0,0,0,0)."""
    if sys.platform != "win32":
        return (0, 0, 0, 0)
    import ctypes
    from ctypes import wintypes

    ver = ctypes.WinDLL("version", use_last_error=True)
    size = ver.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return (0, 0, 0, 0)
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
        return (0, 0, 0, 0)
    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)) or not ptr.value:
        return (0, 0, 0, 0)
    # VS_FIXEDFILEINFO: signature, strucVersion, fileVersionMS, fileVersionLS, ...
    fields = ctypes.cast(ptr, ctypes.POINTER(wintypes.DWORD * 4)).contents
    ms, ls = fields[2], fields[3]
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


def candidates() -> list[Path]:
    """파이썬 폴더(포장본은 여기에 새 것을 넣는다) → 파이썬 설치 폴더 → System32."""
    roots = [Path(sys.executable).parent, Path(sys.base_prefix)]
    system_root = os.environ.get("SystemRoot")
    if system_root:
        roots.append(Path(system_root) / "System32")
    seen: set[str] = set()
    found: list[Path] = []
    for root in roots:
        path = root / "msvcp140.dll"
        key = str(path).lower()
        if key not in seen and path.is_file():
            seen.add(key)
            found.append(path)
    return found


def preload_newest_msvcp() -> str:
    """가장 새 `msvcp140.dll` 을 올리고 그 경로를 돌려준다. 윈도우가 아니거나 실패하면 빈 문자열.

    기동을 막지 않는다 — 못 올려도 원래대로 계속 돈다(그 경우 음성 인식이 옛 런타임과 부딪칠 수 있다).
    """
    global _loaded
    if _loaded or sys.platform != "win32":
        return _loaded
    try:
        import ctypes

        found = candidates()
        if not found:
            return ""
        newest = max(found, key=file_version)
        ctypes.WinDLL(str(newest))
        _loaded = str(newest)
    except Exception:  # noqa: BLE001 - 런타임 미리 올리기는 보조 장치다
        return ""
    return _loaded
