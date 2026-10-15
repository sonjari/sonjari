"""**운영 백엔드의 콜드스타트**를 밖에서 관찰한다 (2026-09-21, 사장님: 「내 PC 운영 앱은 콜드스타트하면 아직 번쩍인다」).

`measure_chrome_flash.py` 는 워커를 **스스로 만들어** 돌린다 — 임시 프로필이라 조용한 경로(`_spawn_chrome` + CDP 붙기)가
성공했고, 운영은 실제 프로필에서 폴백해 **다른 경로**를 탔다. 그래서 실험실 0/8 이 운영을 못 덮었다. 이 스크립트는 워커를
건드리지 않고 **운영 API 그대로** 브라우저를 닫았다 열게 하면서, 우리 크롬 창(프로필 경로로 식별)의 상태를 5ms 마다 적는다.

    python watch_live_flash.py            # 운영 8091 (토큰 파일에서 읽는다 — 출력하지 않는다)

기록:
  transitions  창의 상태가 바뀔 때마다(나타남·최소화·복원·위치) 시각과 상태
  flashes      **사람 눈에 보이는** 동안 = 최소화 아님 + 화면 위 + 알파>0 + 겹치는 다른 앱 창 **위**
  front_ms     우리 크롬이 앞창이던 시간
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import measure_chrome_flash as m  # noqa: E402  (희생양·알파·앱 창 판정을 그대로 쓴다)

user32 = ctypes.windll.user32
TOKEN = Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\control.token").read_text(encoding="utf-8-sig").strip()
BASE = "http://127.0.0.1:8091"
PROFILE_MARK = "browser-profile"


def api(path: str, body: dict | None = None, timeout: float = 90) -> dict:
    request = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"X-JARVIS-TOKEN": TOKEN, "Content-Type": "application/json"},
        method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def chrome_pids() -> set[int]:
    """운영 프로필로 뜬 크롬 프로세스들(창을 가진 것도 자식도 다)."""
    script = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
              f"Where-Object {{ $_.CommandLine -match '{PROFILE_MARK}' }} | ForEach-Object {{ $_.ProcessId }}")
    done = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                          timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {int(x) for x in done.stdout.split() if x.strip().isdigit()}


def main() -> None:
    proc, scapegoat = m._spawn_scapegoat()
    time.sleep(0.8)
    started = time.perf_counter()
    stop = threading.Event()
    pids: set[int] = set()
    transitions: list[dict] = []
    flashes: list[dict] = []
    stats = {"front_ms": 0.0, "ticks": 0}
    foreground: list[dict] = []
    scapegoat_log: list[dict] = []
    last_fg = {"hwnd": 0}

    def refresh_pids() -> None:
        nonlocal pids
        while not stop.is_set():
            try:
                pids = chrome_pids()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.4)

    threading.Thread(target=refresh_pids, daemon=True).start()

    def our_windows() -> list[int]:
        found: list[int] = []
        cur = user32.GetTopWindow(0)
        for _ in range(6000):
            if not cur:
                break
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(cur, ctypes.byref(pid))
            if int(pid.value) in pids:
                cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(cur, cls, 64)
                if cls.value == "Chrome_WidgetWin_1" and user32.IsWindowVisible(cur):
                    rect = wt.RECT()
                    user32.GetWindowRect(cur, ctypes.byref(rect))
                    if rect.right - rect.left > 200 and rect.bottom - rect.top > 200:  # 말풍선·툴팁 같은 작은 창은 뺀다
                        found.append(int(cur))
            cur = user32.GetWindow(cur, 2)
        return found

    last_state: dict[int, tuple] = {}
    episode = {"start": 0.0, "active": False, "who": None}

    def watch() -> None:
        while not stop.is_set():
            stats["ticks"] += 1
            now = time.perf_counter() - started
            ours = our_windows()
            visible_cover, under = False, ""
            # 상태 전이
            seen_now = set()
            for h in ours:
                seen_now.add(h)
                state = (bool(user32.IsIconic(h)), tuple(m._rect(h)), m._layered_alpha(h),
                         user32.GetWindowLongW(h, -20) & 0x80000 != 0)
                if last_state.get(h) != state:
                    last_state[h] = state
                    transitions.append({"at": round(now, 3), "hwnd": h, "iconic": state[0], "rect": list(state[1]),
                                        "alpha": state[2], "title": m._title(h)[:30]})
            # 보이는 번쩍임: 우리 창(최소화 아님·화면 위·알파>0)이 겹치는 다른 앱 창 위
            visible_ours = [h for h in ours if not user32.IsIconic(h) and m._on_a_monitor(h) and m._layered_alpha(h) > 0]
            if visible_ours:
                cur, seen = user32.GetTopWindow(0), []
                for _ in range(6000):
                    if not cur:
                        break
                    if int(cur) in visible_ours:
                        seen.append(int(cur))
                    elif seen and m._is_app_window(cur) and int(cur) not in ours:
                        if any(m._rect(o) and _overlap(o, cur) for o in seen):
                            visible_cover, under = True, m._title(cur)[:30]
                            break
                    cur = user32.GetWindow(cur, 2)
            if visible_cover:
                if not episode["active"]:
                    episode.update(start=now, active=True, who=under)
                    flashes.append({"at": round(now, 3), "over": under, "ms": 0})
                flashes[-1]["ms"] = round((now - episode["start"]) * 1000)
            elif episode["active"]:
                episode["active"] = False
            fg = user32.GetForegroundWindow()
            if fg:
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
                if int(pid.value) in pids:
                    stats["front_ms"] += 5
                if int(fg) != last_fg["hwnd"] and len(foreground) < 60:
                    last_fg["hwnd"] = int(fg)
                    foreground.append({"at": round(now, 3), "hwnd": int(fg), "ours": int(pid.value) in pids,
                                       "title": m._title(fg)[:28]})
            if scapegoat and (user32.IsIconic(scapegoat) != (scapegoat_log[-1]["iconic"] if scapegoat_log else False)):
                scapegoat_log.append({"at": round(now, 3), "iconic": bool(user32.IsIconic(scapegoat))})
            time.sleep(0.005)

    def _overlap(a: int, b: int) -> bool:
        ra, rb = wt.RECT(), wt.RECT()
        user32.GetWindowRect(a, ctypes.byref(ra))
        user32.GetWindowRect(b, ctypes.byref(rb))
        return ra.left < rb.right and rb.left < ra.right and ra.top < rb.bottom and rb.top < ra.bottom

    threading.Thread(target=watch, daemon=True).start()
    out: dict = {}
    try:
        time.sleep(1.0)
        out["close"] = str(api("/v1/tools/execute", {"name": "browser_close", "arguments": {}}).get("status"))
        for _ in range(40):  # 크롬이 정말 내려갈 때까지 — 콜드스타트가 되려면 안 떠 있어야 한다
            time.sleep(0.5)
            if not chrome_pids():
                break
        out["chrome_gone"] = not chrome_pids()
        time.sleep(3.0)
        mark = time.perf_counter() - started
        out["open_called_at"] = round(mark, 3)
        res = api("/v1/tools/execute", {"name": "browser_open", "arguments": {"url": "https://example.com"}})
        out["open"] = {"ok": res.get("ok"), "status": res.get("status"), "error": str(res.get("error"))[:120]}
        out["open_returned_at"] = round(time.perf_counter() - started, 3)
        time.sleep(12)
        try:
            st = api("/v1/browser/status", timeout=15)
            out["connect_mode"] = st.get("connect_mode")
            out["window_sink"] = st.get("window_sink")
            out["last_restore_path"] = st.get("last_restore_path")
            out["attach_error"] = str(st.get("attach_error"))[:200]
        except Exception as exc:  # noqa: BLE001
            out["status_error"] = str(exc)[:100]
    finally:
        stop.set()
        time.sleep(0.3)
        proc.kill()
    out["scapegoat_valid"] = bool(not user32.IsIconic(scapegoat))
    out["transitions"] = transitions[:40]
    out["flashes"] = flashes
    out["foreground"] = foreground
    out["scapegoat_log"] = scapegoat_log
    out["front_ms"] = stats["front_ms"]
    out["avg_tick_ms"] = round((time.perf_counter() - started) / max(1, stats["ticks"]) * 1000, 1)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
