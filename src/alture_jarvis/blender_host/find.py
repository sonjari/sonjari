"""블렌더 찾기 — 하나로 (2026-11-18 · 설계 §13-1).

예전엔 두 벌이었다: 3D(`gen3d/blender.py`)와 애니메이터(`animator/blender_bridge.py`). 서로 달라서
- 3D 는 맥에서 `Blender 4.5.app` 처럼 판이 붙은 이름을 못 찾았고(애니 쪽은 11-13 에 고침),
- 3D 는 경로 **아무 데나** 있는 `blender-9.9` 를 판으로 읽어 앞쪽 임시 폴더 숫자를 판으로 오독할 수 있었고,
- 3D 는 처음 찾은 것, 애니는 가장 새 판을 골랐다.
여기 하나로 모은다. 판은 **블렌더 폴더 이름**(맥은 .app 폴더) → 없으면 맥 Info.plist 에서만 읽는다.
낮은 판을 거를지는 부르는 쪽이 정한다(3D 4.5 이상 · 애니는 이번엔 그대로 — 동작을 바꾸지 않는다).
"""
from __future__ import annotations

import glob
import os
import re
import sys
from pathlib import Path
from typing import Any

Version = tuple[int, ...]


def _setting(name: str) -> str:
    try:
        from ..config import setting

        return str(setting(name, "") or "")
    except Exception:  # noqa: BLE001 — 설정을 못 읽으면 환경 변수만
        return os.environ.get(name, "")


def patterns(platform: str | None = None, home: Path | None = None) -> list[str]:
    """흔한 설치 자리(glob). 손자리가 받아 둔 자리 · 사람이 깐 자리를 둘 다 본다."""
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "darwin":
        return ["/Applications/Blender*.app/Contents/MacOS/Blender",
                str(home / "Applications" / "Blender*.app" / "Contents" / "MacOS" / "Blender")]
    if platform != "win32":
        return ["/usr/bin/blender", "/snap/bin/blender", str(home / "blender*" / "blender")]
    local = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    out = []
    for base in (os.path.join(local, "Sonjari", "blender"),):  # 손자리가 받아 푼 자리(설계 §5-1 install)
        out += [os.path.join(base, "blender.exe"), os.path.join(base, "*", "blender.exe")]
    for base in (os.path.join(program_files, "Blender Foundation"), os.path.join(local, "Programs", "Blender Foundation")):
        out.append(os.path.join(base, "Blender*", "blender.exe"))
    out.append(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe")
    for base in (r"D:\tools", r"C:\tools"):
        out += [os.path.join(base, "blender*", "blender.exe"), os.path.join(base, "blender*", "*", "blender.exe")]
    return out


def version_of(path: str | Path) -> Version:
    """판 번호 — 윈도우는 블렌더 폴더 이름(`Blender 4.2` · `blender-5.2.3-windows-x64`), 맥은 `.app` 이름 → Info.plist.

    경로 앞쪽(임시 폴더 등)의 숫자는 판으로 읽지 않는다. 모르면 (0,).
    """
    exe = Path(path)
    on_mac = exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents"
    folder = exe.parents[2].name if on_mac and len(exe.parents) > 2 else exe.parent.name
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", folder)
    if m:
        return tuple(int(x or 0) for x in m.groups())
    plist = exe.parent.parent / "Info.plist"
    try:
        import plistlib

        with plist.open("rb") as fh:
            short = str(plistlib.load(fh).get("CFBundleShortVersionString") or "")
        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", short)
        if m:
            return tuple(int(x or 0) for x in m.groups())
    except Exception:  # noqa: BLE001 — 판을 모르면 맨 뒤로
        pass
    return (0,)


def _text(ver: Version) -> str | None:
    return ".".join(str(x) for x in ver[:2]) if ver and ver != (0,) else None


def find(min_version: Version | None = None, *, platform: str | None = None, home: Path | None = None) -> dict[str, Any]:
    """`{found, exe, version, version_full, why, too_old}`.

    - 설정 `JARVIS_BLENDER` 가 있고 파일이면 그것(사람이 고른 것) — 단 `min_version` 보다 낮은 판으로 **읽히면** 건너뛴다.
    - 아니면 흔한 자리에서 `min_version` 이상 가운데 **가장 새 판**. 판을 못 읽은 것은 거르지 않되 맨 뒤.
    """
    too_old: list[str] = []

    def ok(exe: str) -> bool:
        ver = version_of(exe)
        if min_version and ver != (0,) and ver < tuple(min_version):
            too_old.append(f"{exe} ({_text(ver)})")
            return False
        return True

    def hit(exe: str) -> dict[str, Any]:
        ver = version_of(exe)
        return {"found": True, "exe": exe, "version": _text(ver), "version_full": ver, "why": "", "too_old": too_old}

    given = _setting("JARVIS_BLENDER").strip().strip('"')
    if given and Path(given).is_file() and ok(given):
        return hit(given)
    found = sorted({p for pat in patterns(platform, home) for p in glob.glob(pat) if Path(p).is_file()}, key=version_of)
    usable = [p for p in found if ok(p)]
    if usable:
        return hit(usable[-1])
    floor = f" — {'.'.join(map(str, min_version))} 미만이라 뺀 것: {', '.join(too_old)}" if too_old and min_version else ""
    return {"found": False, "exe": None, "version": None, "version_full": None, "why": "블렌더를 못 찾았다" + floor,
            "too_old": too_old}
