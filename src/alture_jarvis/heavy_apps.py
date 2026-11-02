"""그래픽카드를 같이 쓰는 무거운 작업 프로그램을 알아본다 (2026-10-30 대표).

16GB 흉내 시험에서 Swift 27B 가 카드 밖으로 넘쳐 초당 6토큰 · 코드 0/3 이었다. 그런데 윈도우는 다른 프로그램이 쥔 카드 메모리를
잘 안 보여 준다(`nvidia-smi` 의 프로그램별 사용량이 `[N/A]`, llama-server 는 「다 올렸다」고 보고). 그래서 메모리 숫자 대신
**그 프로그램이 켜져 있는가 · 깔려 있는가**를 본다 — 켜져 있음은 판 시작에(빠른 모델로 넘김), 깔려 있음은 마법사에서(같이 받아 두기).

게임은 깔려 있음으로 세지 않는다 — 스팀은 웬만한 PC 에 다 있어서 모두에게 경고가 뜬다. 켜져 있을 때만 본다(실행 파일이
게임 가게 폴더 안에 있으면 게임).
"""
from __future__ import annotations

import sys
import time
from typing import Any, Callable, Iterable

# (보일 이름, 실행 파일 이름들(소문자), 설치 목록 이름에 들어 있는 낱말들(소문자))
HEAVY_WORK_APPS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("3ds Max", ("3dsmax.exe",), ("3ds max",)),
    ("Maya", ("maya.exe",), ("autodesk maya",)),
    ("Blender", ("blender.exe",), ("blender",)),
    ("Unity", ("unity.exe",), ("unity 20", "unity 6", "unity hub")),
    ("Unreal Engine", ("unrealeditor.exe", "ue4editor.exe", "ue5editor.exe"), ("unreal engine",)),
    ("Premiere Pro", ("adobe premiere pro.exe",), ("premiere pro",)),
    ("After Effects", ("afterfx.exe",), ("after effects",)),
    ("DaVinci Resolve", ("resolve.exe",), ("davinci resolve",)),
    ("Houdini", ("houdini.exe", "houdinifx.exe", "houdinicore.exe"), ("houdini",)),
    ("Cinema 4D", ("cinema 4d.exe",), ("cinema 4d",)),
    ("Substance 3D Painter", ("adobe substance 3d painter.exe",), ("substance 3d painter",)),
    ("ZBrush", ("zbrush.exe",), ("zbrush",)),
)

# 이 폴더 안에서 도는 프로그램은 게임으로 본다.
GAME_FOLDERS = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\battle.net\\", "\\xboxgames\\")

# 이 크기 이하 카드에서만 따진다 — 24GB 카드는 Swift(13.4GB)와 무거운 프로그램이 같이 들어간다.
SMALL_CARD_GB = 16.5

_CACHE_SEC = 10.0
_cache: dict[str, Any] = {"at": 0.0, "names": []}


def match_running(processes: Iterable[tuple[str, str]]) -> list[str]:
    """(실행 파일 이름, 경로) 목록에서 무거운 프로그램 이름들. 같은 이름은 한 번."""
    found: list[str] = []
    for name, path in processes:
        lowered = str(name or "").lower()
        where = str(path or "").lower()
        label = ""
        for shown, exes, _words in HEAVY_WORK_APPS:
            if lowered in exes:
                label = shown
                break
        if not label and where and any(folder in where for folder in GAME_FOLDERS) and lowered.endswith(".exe"):
            label = f"game ({lowered[:-4]})"
        if label and label not in found:
            found.append(label)
    return found


def match_installed(display_names: Iterable[str]) -> list[str]:
    """설치 목록 이름들에서 무거운 작업 프로그램 이름들(게임은 안 센다)."""
    names = [str(item or "").lower() for item in display_names]
    found: list[str] = []
    for shown, _exes, words in HEAVY_WORK_APPS:
        if any(word in name for name in names for word in words) and shown not in found:
            found.append(shown)
    return found


def _powershell_processes() -> list[tuple[str, str]]:
    """psutil 이 없을 때(스토어 패키지에는 안 들어 있다 — `check_bundle.py` 선택 부품) 윈도우 기본 명령으로 본다.

    ★ 0.4.37.0 첫 굽기 기록에서 psutil 「선택 · 꺼짐」을 보고 넣었다 — 없으면 스토어판에서 이 기능이 조용히 꺼져 있었다.
    """
    if sys.platform != "win32":
        return []
    import subprocess

    command = "Get-Process | ForEach-Object { $_.ProcessName + '.exe|' + $_.Path }"
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=8, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out: list[tuple[str, str]] = []
    for line in (done.stdout or "").splitlines():
        name, _, path = line.strip().partition("|")
        if name:
            out.append((name, path))
    return out


def _processes() -> list[tuple[str, str]]:
    try:
        import psutil
    except ImportError:
        return _powershell_processes()
    out: list[tuple[str, str]] = []
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            out.append((str(proc.info.get("name") or ""), str(proc.info.get("exe") or "")))
        except Exception:  # noqa: BLE001 — 권한 없는 프로그램은 건너뛴다
            continue
    return out


def running(*, list_processes: Callable[[], list[tuple[str, str]]] | None = None) -> list[str]:
    """지금 켜져 있는 무거운 프로그램. 10초 동안은 같은 답을 쓴다(판마다 훑지 않게)."""
    now = time.monotonic()
    if list_processes is None and now - float(_cache["at"]) < _CACHE_SEC and _cache["at"]:
        return list(_cache["names"])
    try:
        names = match_running((list_processes or _processes)())
    except Exception:  # noqa: BLE001 — 못 보면 없다고 하지 않고 빈 목록(모름)
        names = []
    if list_processes is None:
        _cache.update(at=now, names=names)
    return names


def _uninstall_names() -> list[str]:
    if sys.platform != "win32":
        return []
    import winreg

    out: list[str] = []
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(key, sub) as item:
                        out.append(str(winreg.QueryValueEx(item, "DisplayName")[0]))
                except OSError:
                    continue
    return out


def installed(*, list_names: Callable[[], list[str]] | None = None) -> list[str]:
    """이 PC 에 깔린 무거운 작업 프로그램(마법사용)."""
    try:
        return match_installed((list_names or _uninstall_names)())
    except Exception:  # noqa: BLE001
        return []


def small_card(total_gb: Any) -> bool:
    try:
        return 0 < float(total_gb) <= SMALL_CARD_GB
    except (TypeError, ValueError):
        return False
