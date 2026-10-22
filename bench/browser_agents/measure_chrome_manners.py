"""크롬이 앞으로 나오는가 · 탭이 몇 장 남는가 — 실제 조사 한 판을 돌리며 잰다.

    python measure_chrome_manners.py "<과제>" [--budget 600]

재는 것:
  ① 앞창을 0.2초마다 표집해 **크롬이 앞을 차지한 시간**(초)과 최대 연속 구간
  ② 끝났을 때 자동화 크롬의 **탭 장수**(CDP /json/list)
  ③ 그 판이 실제로 성공했는가(걸음·산출물) — 뒤에서 일해도 결과가 같은지 확인용

사람의 손은 건드리지 않는다. 지금 이 PC 는 사용자가 쓰는 중일 수도, 아닐 수도 있다 —
유휴 초를 같이 기록해 「지켜보는 사람」 조건이 실제로 재였는지 남긴다.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8091"
CDP = "http://127.0.0.1:9222"


def token() -> str:
    from pathlib import Path
    for candidate in (Path(r"C:\Users\user\AppData\Local\Ontelic\data\control.token"),
                      Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\control.token")):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8-sig").strip()
    return ""


TOKEN = token()


def call(method: str, path: str, body: dict | None = None, timeout: float = 90):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if TOKEN:
        request.add_header("X-JARVIS-TOKEN", TOKEN)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class Front:
    """앞창을 0.2초마다 재서 크롬이 앞을 쥔 시간을 센다."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self.samples: list[tuple[float, bool, str]] = []

    def _title_and_exe(self, hwnd: int) -> tuple[str, str]:
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        name = ""
        if handle:
            size = ctypes.c_ulong(260)
            path = ctypes.create_unicode_buffer(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                name = path.value.rsplit("\\", 1)[-1]
            kernel32.CloseHandle(handle)
        return buffer.value, name

    def run(self) -> None:
        while not self.stop.is_set():
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            title, exe = self._title_and_exe(hwnd) if hwnd else ("", "")
            self.samples.append((time.time(), exe.lower() == "chrome.exe", f"{exe}|{title[:60]}"))
            time.sleep(0.2)

    def report(self) -> dict:
        chrome = [s for s in self.samples if s[1]]
        longest = current = 0
        for _, is_chrome, _label in self.samples:
            current = current + 1 if is_chrome else 0
            longest = max(longest, current)
        return {
            "samples": len(self.samples),
            "chrome_front_sec": round(len(chrome) * 0.2, 1),
            "chrome_front_longest_sec": round(longest * 0.2, 1),
            "chrome_front_titles": sorted({s[2] for s in chrome})[:5],
            "front_seen": sorted({s[2].split("|")[0] for s in self.samples}),
        }


def tabs() -> dict:
    try:
        status = call("GET", "/v1/browser/status", timeout=10)
    except Exception as exc:
        return {"reachable": False, "why": type(exc).__name__}
    return {k: status.get(k) for k in
            ("tabs", "max_tabs", "ours_of_tabs", "tabs_closed_total", "tabs_measured_at", "connect_mode")}


def idle_sec() -> float:
    class _LastInput(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = _LastInput()
    info.cbSize = ctypes.sizeof(_LastInput)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--budget", type=float, default=600.0)
    args = ap.parse_args()

    out: dict = {"task": args.task, "tabs_before": tabs(), "idle_at_start_sec": round(idle_sec(), 1)}
    watcher = Front()
    threading.Thread(target=watcher.run, daemon=True).start()

    started = time.time()
    job = call("POST", "/v1/chat", {"prompt": args.task, "session_id": "measure-chrome",
                                    "delivery": "screen", "origin": "workspace", "open_results": False,
                                    "measurement": True})
    final: dict = {}
    idles: list[float] = []
    while time.time() - started < args.budget:
        final = call("GET", f"/v1/jobs/{job['id']}")
        idles.append(idle_sec())
        if final.get("status") in {"completed", "failed", "cancelled", "needs_review", "waiting_approval"}:
            break
        time.sleep(4)
    out["sec"] = round(time.time() - started, 1)
    watcher.stop.set()
    time.sleep(0.5)

    detail = call("GET", f"/v1/jobs/{job['id']}/steps")
    steps = detail.get("steps") or detail.get("items") or []
    browsed = [s for s in steps if str(s.get("tool") or "").startswith("browser_") and s.get("ok")]
    outputs = call("GET", f"/v1/outputs?job_id={job['id']}").get("items") or []
    out.update({
        "status": final.get("status"),
        "steps": len(steps),
        "browser_steps_ok": len(browsed),
        "files_on_disk": [str(i.get("path")) for i in outputs if i.get("exists")][:4],
        "front": watcher.report(),
        "tabs_after": tabs(),
        # 「지켜보는 사람」 조건이 실제로 재였나 — 유휴가 10초를 넘긴 적이 있어야 옛 규칙이 풀렸다
        "idle_max_sec": round(max(idles), 1) if idles else None,
        "idle_over_10s_share": round(sum(1 for value in idles if value > 10) / len(idles), 2) if idles else None,
    })
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
