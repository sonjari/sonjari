"""실측용 — 온텔릭 크롬 창을 최소화한 채로 유지하고, 누가 창을 되살렸는지 센다 (2026-09-16, H2-A).

「사람이 PC 를 쓰는 중이면 창을 앞으로 안 가져온다」를 켠 뒤, 가장 나쁜 경우(창이 최소화돼 화면에 안 그려짐)에도
판이 성공하는지 잰다. 창이 되살아나면 그 사실을 세고 다시 내린다 — 되살림이 있으면 어딘가 아직 창을 올리는 자리가
있다는 뜻이다.

    python keep_ontelic_chrome_minimized.py <프로필 폴더> <로그 파일>

멈추려면 프로세스를 끈다.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
SW_MINIMIZE = 6


def profile_pids(profile: str) -> set[int]:
    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
         "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    rows = json.loads(done.stdout or "[]")
    rows = rows if isinstance(rows, list) else [rows]
    needle = profile.lower().replace("/", "\\")
    return {int(r["ProcessId"]) for r in rows if needle in str(r.get("CommandLine") or "").lower().replace("/", "\\")}


def top_windows(pids: set[int]) -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) in pids and user32.GetWindowTextLengthW(hwnd) > 0:
            found.append(int(hwnd))
        return True

    user32.EnumWindows(collect, 0)
    return found


def main() -> None:
    profile, log_path = sys.argv[1], sys.argv[2]
    restored = 0
    pids: set[int] = set()
    last_pid_check = 0.0
    last_seen_log = 0.0

    def note(text: str) -> None:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    # ★ 2026-09-16 첫 판: 프로필 경로를 틀리게 줘서 창을 **하나도 못 찾았는데** 로그는 「되살림 0」만 남겼다 —
    #   아무것도 안 한 것이 좋은 결과로 읽혔다. 이제 찾은 창 수와 최소화 상태를 1분마다 남긴다.
    while True:
        now = time.time()
        if now - last_pid_check > 20 or not pids:
            pids = profile_pids(profile)
            last_pid_check = now
        windows = top_windows(pids)
        if now - last_seen_log > 60:
            note(f"seen pids={len(pids)} windows={len(windows)} iconic={sum(1 for h in windows if user32.IsIconic(h))}")
            last_seen_log = now
        for hwnd in windows:
            if not user32.IsIconic(hwnd):
                restored += 1
                user32.ShowWindow(hwnd, SW_MINIMIZE)
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"{time.strftime('%H:%M:%S')} restored->minimized hwnd={hwnd} total={restored}\n")
        time.sleep(1.0)


if __name__ == "__main__":
    main()
