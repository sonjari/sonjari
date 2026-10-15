"""「맡겨 놓고 지켜보는」 조건을 **확정적으로** 만들어 크롬을 띄운다 — 앞을 뺏는가.

유휴를 9999초로 주면 옛 규칙(`idle < 10`)은 「아무도 안 쓰는 PC」로 판정해 `--start-maximized`
로 띄웠다. 그게 사용자님이 두 번 본 고장이다. 사람의 손을 기다릴 필요 없이 그 조건을 만든다.

사용자 프로필은 건드리지 않는다 — 임시 프로필·다른 CDP 포트.
"""
from __future__ import annotations

import ctypes
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, r"C:\RoboMetaFit\tools\alture-jarvis\src")
if __import__("os").environ.get("NO_PSUTIL") == "1":
    # 포장본에는 psutil 이 없다 — 같은 길을 타게 import 자체를 막는다.
    sys.modules["psutil"] = None  # type: ignore[assignment]
sys.stdout.reconfigure(encoding="utf-8")

from alture_jarvis.browser import BrowserWorker  # noqa: E402
from alture_jarvis.config import JarvisConfig  # noqa: E402
from alture_jarvis.user_presence import UserPresence  # noqa: E402

IDLE_FORCED = 9999.0  # 「지켜보는 사람」 — 손은 멈췄지만 자리에 있다


def front_pid() -> int:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def front_label() -> str:
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "|"
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    name = ""
    if handle:
        size = ctypes.c_ulong(260)
        buffer = ctypes.create_unicode_buffer(260)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            name = buffer.value.rsplit("\\", 1)[-1]
        kernel32.CloseHandle(handle)
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, length + 1)
    return f"{name}|{title.value[:50]}"


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="chrome-manners-"))
    config = JarvisConfig(
        runtime_root=root,
        data_dir=root / "data",
        yield_to_user_enabled=True,
        browser_headless=False,
        # off: Playwright 가 띄우는 폴백 길 · auto: 포트 열고 우리가 띄워 붙는 **운영 기본** 길
        browser_attach_mode=__import__("os").environ.get("ATTACH_MODE", "off"),
        browser_profile_dir=root / "profile",
        browser_cdp_port=9351,
        browser_max_tabs=6,
    )
    worker = BrowserWorker(config)
    worker.presence = UserPresence(config, idle=lambda: IDLE_FORCED)

    out: dict = {
        "psutil": __import__("os").environ.get("NO_PSUTIL") != "1",
        "idle_forced_sec": IDLE_FORCED,
        "presence_active": worker.presence.active(),          # False — 옛 규칙은 여기서 양보를 풀었다
        "may_take_foreground": worker._may_take_foreground(),  # False 여야 한다(새 규칙)
        # 사람이 보던 창의 **제목은 적지 않는다** — 2026-09-16 원본에 보던 영상 제목이 찍혀 커밋 전에 지웠다.
        "front_before": front_label().split("|")[0],
    }

    samples: list[str] = []
    pids: list[int] = []
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            samples.append(front_label())
            pids.append(front_pid())
            time.sleep(0.2)

    threading.Thread(target=watch, daemon=True).start()
    started = time.time()
    try:
        result = worker.execute_trusted("browser_open", {"url": "https://example.com"})
        out["open_ok"] = True
        out["open_url"] = str((result or {}).get("url") or "")[:80]
    except Exception as exc:
        out["open_ok"] = False
        out["open_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    out["open_sec"] = round(time.time() - started, 1)
    time.sleep(3)  # 창이 늦게 올라오는 것까지 본다
    stop.set()
    time.sleep(0.4)

    # ★ 2026-09-16 밤: 전에는 `chrome.exe` 면 **다 뺏김**으로 셌다. 그런데 한 판을 열어 보니 앞에
    #   있던 것은 사람 자신의 크롬(「메일 내용 정리 - Chrome」 — 띄우기 **전부터** 앞)이었다.
    #   「0~5초 들쭉날쭉」은 그때 사람 크롬이 앞에 있었나를 잰 것이었을 수 있다. 우리 프로필의
    #   크롬만 센다(`_is_our_chrome_pid` — 제품이 창을 내릴 때 쓰는 바로 그 판단).
    ours_cache: dict[int, bool] = {}

    def ours(pid: int) -> bool:
        if pid not in ours_cache:
            try:
                ours_cache[pid] = bool(pid) and bool(worker._is_our_chrome_pid(pid))
            except Exception:  # noqa: BLE001
                ours_cache[pid] = False
        return ours_cache[pid]

    flags = [ours(pid) for pid in pids]
    # 독립 대조: 제품 판단(`_is_our_chrome_pid`)이 틀리면 제품과 눈금이 **같이** 틀린다.
    # 명령줄의 프로필 경로로 따로 가린다(PowerShell CIM — wmic 은 이 PC 에 없다).
    import subprocess as _sp
    listing = _sp.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
         "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    ).stdout
    profile = str(config.browser_profile_dir).lower()
    by_cmdline = {int(line.split("\t", 1)[0]) for line in listing.splitlines()
                  if "\t" in line and profile in line.lower() and line.split("\t", 1)[0].isdigit()}
    cross = [pid in by_cmdline for pid in pids]
    chrome = [s for s, mine in zip(samples, flags) if mine]
    other_chrome = [s for s, mine in zip(samples, flags) if not mine and s.lower().startswith("chrome.exe")]
    longest = current = 0
    for mine in flags:
        current = current + 1 if mine else 0
        longest = max(longest, current)
    out.update({
        "samples": len(samples),
        "chrome_front_sec": round(len(chrome) * 0.2, 1),
        "chrome_front_longest_sec": round(longest * 0.2, 1),
        "chrome_front_titles": sorted(set(chrome))[:4],
        # 사람 크롬이 앞에 있던 시간 — 뺏김이 아니다. 따로 적어 두어야 헷갈리지 않는다.
        "people_chrome_front_sec": round(len(other_chrome) * 0.2, 1),
        "ours_by_cmdline_front_sec": round(sum(cross) * 0.2, 1),
        "judgments_disagree": sum(1 for a, b in zip(flags, cross) if a != b),
        # 꼬리가 **언제** 나는가 — 띄우는 중인가, 홈으로 가는 중인가, 감시가 끝난 뒤인가.
        "ours_front_at_sec": [round(i * 0.2, 1) for i, mine in enumerate(flags) if mine][:12],
        # 띄우기 전 크롬 목록이 비면 사람 크롬까지 「새 것 = 우리 것」으로 읽힌다.
        "chrome_pids_before_launch": len(getattr(worker, "_chrome_pids_before_launch", set()) or ()),
        "chrome_running_now": len(listing.splitlines()),
        "front_processes_seen": sorted({s.split("|")[0] for s in samples}),
    })
    try:
        import urllib.request as _u
        with _u.urlopen("http://127.0.0.1:9351/json/list", timeout=4) as r:
            targets = json.loads(r.read().decode("utf-8"))
        out["tabs"] = len([t for t in targets if t.get("type") == "page"])
    except Exception as exc:
        out["tabs"] = f"unreachable: {type(exc).__name__}"
    # ★ 2026-09-16: 창을 최소화 대신 **맨 뒤로** 보낸다. 그 목적이 「실시간 화면이 찍히는가」이므로
    #   앞창만 재면 반쪽이다 — 같은 판에서 캡처가 되는지, 창이 최소화됐는지도 같이 적는다.
    try:
        frame = worker.live_frame()
        out["live_frame_bytes"] = len(frame.get("jpeg") or b"")
        out["live_frame_reason"] = str(frame.get("reason") or "")[:120]
    except Exception as exc:  # noqa: BLE001
        out["live_frame_bytes"] = 0
        out["live_frame_reason"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    try:
        windows = worker._our_chrome_windows()  # 최소화된 창은 이 목록에 안 든다
        out["our_visible_windows"] = len(windows)
    except Exception as exc:  # noqa: BLE001
        out["our_visible_windows"] = f"{type(exc).__name__}"
    out["sink_report"] = getattr(worker, "_sink_report", {})
    out["connect_mode"] = getattr(worker, "_connect_mode", "?")
    out["attach_error"] = str(getattr(worker, "_attach_error", ""))[:160]
    out["headless_cfg"] = bool(worker.config.browser_headless)
    try:
        worker.stop()
    except Exception:
        pass
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
