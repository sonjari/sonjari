"""MSIX(스토어 패키지) 안에서 돌 때 달라지는 것 (W1, 2026-09-15).

## 실측이 정한 것 (`packaging/msix_probe`, 인수인계서 1.1)

제한 기능 없는 기본 매니페스트에서:

- AppData 에 **새로 만든** 파일은 앱 전용 칸(`%LOCALAPPDATA%\\Packages\\<PFN>\\LocalCache`)으로 간다.
  다른 앱에는 안 보이고, **앱을 지우면 같이 지워진다.**
- AppData 에 **이미 있던** 파일을 고치면 실제 파일이 바뀐다.
- 다른 패키지 폴더·사용자 폴더(홈) 아래는 가상화되지 않는다.
- 패키지 **안** 실행 파일의 자식(동봉 파이썬 백엔드)은 부모와 같은 보기, 패키지 **밖** 실행 파일
  (Claude·Cursor·Codex 가 띄우는 명령)은 실제 보기.

그래서 우리 프로세스가 보는 `%LOCALAPPDATA%\\AltureJarvis\\data\\control.token` 과 밖의 앱이 여는
같은 문자열 경로가 **다른 파일**일 수 있다. 밖에 알려 줄 경로는 여기서 실제 디스크 경로로 푼다.

가상화 끄기(`unvirtualizedResources`)는 스토어에서 「제출마다 승인·특정 게임용」이라 쓰지 않는다.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

# GetCurrentPackageFullName 이 패키지 밖에서 돌려주는 값.
APPMODEL_ERROR_NO_PACKAGE = 15700
ERROR_INSUFFICIENT_BUFFER = 122

_cache: dict[str, str] = {}


def _package_string(function_name: str) -> str:
    """`GetCurrentPackageFullName`·`GetCurrentPackageFamilyName` 공통. 패키지 밖이면 빈 문자열."""
    if os.name != "nt":
        return ""
    if function_name in _cache:
        return _cache[function_name]
    value = ""
    try:
        function = getattr(ctypes.windll.kernel32, function_name)
        length = ctypes.c_uint32(0)
        code = function(ctypes.byref(length), None)
        if code == ERROR_INSUFFICIENT_BUFFER and length.value:
            buffer = ctypes.create_unicode_buffer(length.value)
            if function(ctypes.byref(length), buffer) == 0:
                value = buffer.value
    except (AttributeError, OSError):
        # Windows 8 이전에는 함수가 없다. 그런 PC 에서 MSIX 로 돌 수도 없다.
        value = ""
    _cache[function_name] = value
    return value


def package_version() -> str:
    """패키지 판 번호(`0.4.2.0`). 패키지 밖이면 빈 문자열.

    전체 이름은 `이름_판번호_구조_자원_게시자` 다 — 둘째 칸이 스토어·채널에 올린 그 번호다.
    """
    parts = package_full_name().split("_")
    return parts[1] if len(parts) >= 2 else ""


def package_full_name() -> str:
    """패키지 안이면 전체 이름(`RoboMetaFit.Jarvis_1.0.0.0_x64__abc`), 밖이면 빈 문자열."""
    from .config import setting
    forced = setting("JARVIS_FAKE_PACKAGE_FULL_NAME")
    return forced or _package_string("GetCurrentPackageFullName")


def package_family_name() -> str:
    from .config import setting
    forced = setting("JARVIS_FAKE_PACKAGE_FAMILY_NAME")
    return forced or _package_string("GetCurrentPackageFamilyName")


def is_packaged() -> bool:
    return bool(package_full_name())


def _env_path(name: str, fallback: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw) if raw else fallback


def external_path(
    path: Path | str,
    *,
    family_name: str | None = None,
    localappdata: Path | None = None,
    appdata: Path | None = None,
) -> Path:
    """**밖의 앱**이 열어야 하는 실제 디스크 경로.

    패키지 밖이거나, AppData 아래가 아니거나, 이미 다른 패키지 폴더 안이면 그대로 돌려준다.
    패키지 안에서 AppData 아래라면:

    - 전용 칸에 사본이 있으면 그것이 우리가 쓴 파일이다 → 전용 칸 경로
    - 전용 칸에 없고 실제 자리에 있으면(설치 전부터 있던 파일) → 실제 경로
    - 둘 다 없으면 앞으로 만들 파일이다 → 새 파일은 전용 칸으로 가므로 전용 칸 경로
    """
    target = Path(path)
    family = package_family_name() if family_name is None else family_name
    if not family:
        return target
    home = Path.home()
    local = localappdata or _env_path("LOCALAPPDATA", home / "AppData" / "Local")
    roaming = appdata or _env_path("APPDATA", home / "AppData" / "Roaming")
    packages = local / "Packages"
    if _is_under(target, packages):
        return target
    for base, kind in ((local, "Local"), (roaming, "Roaming")):
        if not _is_under(target, base):
            continue
        private = packages / family / "LocalCache" / kind / _relative(target, base)
        if private.exists():
            return private
        if target.exists():
            return target
        return private
    return target


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path))).rstrip("\\/")


def _is_under(path: Path, base: Path) -> bool:
    child, parent = _normalized(path), _normalized(base)
    return child == parent or child.startswith(parent + os.sep)


def _relative(path: Path, base: Path) -> Path:
    return Path(os.path.relpath(os.path.abspath(str(path)), os.path.abspath(str(base))))


def hidden_from_other_apps(
    path: Path | str,
    *,
    family_name: str | None = None,
    localappdata: Path | None = None,
    appdata: Path | None = None,
) -> bool:
    """이 경로에 **새 파일을 만들면** 밖의 앱이 못 보는가.

    Claude Desktop 설치형인데 설정 파일이 아직 없는 PC 가 이 경우다 — 만들어 봐야 우리 전용 칸에만
    생긴다. 그때는 쓰지 말고 붙여넣기 안내로 간다(W1-5).
    """
    target = Path(path)
    family = package_family_name() if family_name is None else family_name
    if not family:
        return False
    # `exists()` 로 거르지 않는다 — 패키지 안에서는 전용 칸 사본도 「있다」로 보인다.
    return external_path(target, family_name=family, localappdata=localappdata, appdata=appdata) != target


def runtime_summary() -> dict[str, object]:
    """진단·화면용. 경로에 사용자 이름이 들어가므로 밖으로 보내는 통계에는 쓰지 않는다."""
    return {
        "packaged": is_packaged(),
        "package_full_name": package_full_name(),
        "package_family_name": package_family_name(),
        "executable": sys.executable,
    }


__all__ = [
    "external_path",
    "hidden_from_other_apps",
    "is_packaged",
    "package_family_name",
    "package_full_name",
    "runtime_summary",
]
