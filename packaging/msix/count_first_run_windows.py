"""첫 실행 창 개수 — 노트북 첫 설치에서 창이 3개 뜬 사고의 재현·회귀 확인 (2026-09-16 밤).

    E:\\...\\alture-jarvis\\.venv\\Scripts\\python.exe packaging/msix/count_first_run_windows.py [--launches 3]

`run_app_package_test.py` 는 창을 `MainWindowTitle`(프로세스당 제목 **하나**)로만 봐서, 한 프로세스가 창을
셋 띄워도 하나로 보였다. 여기서는 Sonjari.exe 의 **보이는 최상위 창을 전부** 센다.

순서: (깨끗한 상태) 등록 → 켜기 → 창 세기 → 사람처럼 **또 켜기**(설치 창의 「실행」 + 시작 메뉴) → 창 세기 → 제거.
지키는 것: 운영 자비스(8091)는 건드리지 않는다(시험판은 8094). 제거하면 패키지 전용 칸이 지워진다.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
IDENTITY = "RoboMetaFit.OntelicMsixTest"
STAGE = Path(r"C:\RoboMetaFit\tools\JarvisAppStage\app")


def ps(command: str, timeout: float = 180) -> str:
    done = subprocess.run(["powershell", "-NoProfile", "-Command",
                           "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + command],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (done.stdout or "").strip()


def ontelic_pids() -> set[int]:
    out = ps("Get-Process Ontelic -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }")
    return {int(x) for x in out.split() if x.strip().isdigit()}


def windows() -> list[str]:
    """Sonjari.exe 의 보이는 최상위 창 제목(제목 있는 것만)."""
    pids = ontelic_pids()
    user32 = ctypes.windll.user32
    titles: list[str] = []
    raw: list[dict] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):  # type: ignore[no-untyped-def]
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                klass = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, klass, 256)
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                exstyle = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
                raw.append({"title": buffer.value, "class": klass.value,
                            "w": rect.right - rect.left, "h": rect.bottom - rect.top,
                            "toolwindow": bool(exstyle & 0x80)})
                # 사람 눈에 창으로 보이는 것만 센다: 크기가 있고 도구 창(작업 표시줄에 안 뜸)이 아닌 것.
                # ★ 한 번만 실행 플러그인이 만드는 `…-siw` 메시지 창이 「보임」으로 잡혀서 처음엔 2개로 셌다.
                if rect.right - rect.left > 50 and rect.bottom - rect.top > 50 and not exstyle & 0x80:
                    titles.append(buffer.value)
        return True

    user32.EnumWindows(proto(visit), 0)
    windows.raw = raw  # type: ignore[attr-defined]
    return sorted(titles)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--launches", type=int, default=3)
    ap.add_argument("--settle", type=float, default=20.0)
    args = ap.parse_args()
    record: dict = {"exe": str(STAGE / "Sonjari.exe"),
                    "exe_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((STAGE / "Sonjari.exe").stat().st_mtime))}
    ps(f"Get-AppxPackage -Name {IDENTITY} | Remove-AppxPackage")
    ps("Get-Process Ontelic -ErrorAction SilentlyContinue | Stop-Process -Force")
    family = ps(f"Add-AppxPackage -Register '{STAGE / 'AppxManifest.xml'}'; (Get-AppxPackage -Name {IDENTITY}).PackageFamilyName")
    record["family"] = family.splitlines()[-1] if family else ""
    try:
        for n in range(1, args.launches + 1):
            ps(f"Start-Process explorer.exe 'shell:AppsFolder\\{record['family']}!App'")
            time.sleep(args.settle if n == 1 else 8)
            seen = windows()
            record[f"after_launch_{n}"] = {"windows": seen, "count": len(seen), "processes": len(ontelic_pids()),
                                           "all_visible": getattr(windows, "raw", [])}
            print(f"launch {n}: {len(seen)} windows {seen} · processes {len(ontelic_pids())}", flush=True)
    finally:
        ps("Get-Process Ontelic -ErrorAction SilentlyContinue | Stop-Process -Force")
        time.sleep(2)
        ps(f"Get-AppxPackage -Name {IDENTITY} | Remove-AppxPackage")
        record["unregistered"] = not ps(f"Get-AppxPackage -Name {IDENTITY}")
    ok = all(record[f"after_launch_{n}"]["count"] == 1 for n in range(1, args.launches + 1))
    record["one_window_every_time"] = ok
    print(json.dumps(record, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
