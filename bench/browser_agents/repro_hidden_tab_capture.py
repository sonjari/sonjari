"""숨은 탭 캡처가 브라우저 일꾼을 멈추는가 — 임시 크롬으로 직접 재현한다 (2026-09-16).

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe bench/browser_agents/repro_hidden_tab_capture.py <min|bottom> <active|background> [raw|product]

- `min`    크롬을 최소화해 띄운다(예전 제품 방식)      `bottom` 보이되 활성화 없이 맨 뒤로(지금 제품의 「다 뜬 뒤」 상태)
- `active` 창의 앞 탭을 찍는다                         `background` CDP `background: true` 로 만든 배경 탭
- `raw`     CDP `Page.captureScreenshot` 을 직접 부른다(예전 제품 코드). 8초 넘으면 HANG 을 찍고 끝낸다
- `product` 제품의 `BrowserWorker._capture_live_frame` 을 세 번 부르고, 바로 다음 동작이 되는지 본다
            (PYTHONPATH 로 어느 소스를 재는지 정한다 — C: 런타임이 낡았으면 낡은 코드를 잰다)

2026-09-16 결과(raw): min+active HANG · min+background HANG · bottom+active 0.04초 · bottom+background HANG.
네 조건 모두 페이지 안의 `document.visibilityState` 는 `visible` 이었다 — 페이지 안에서 미리 가를 수 없다.

★ 사람 크롬은 건드리지 않는다. 임시 프로필(`repro-hidden-*`)의 크롬만 명령줄로 골라 닫는다.
  2026-09-16 한 번은 스크립트가 예외로 죽어 정리를 못 타고 크롬 네 벌이 남았다 — 다음 판이 **그 남은
  크롬에 붙어서** 엉뚱한 값을 냈다. 그래서 포트가 이미 열려 있으면 시작하지 않고, 죽어도 정리한다.
"""
from __future__ import annotations

import atexit
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import psutil
from playwright.sync_api import sync_playwright

MODE, TARGET = sys.argv[1], sys.argv[2]
KIND = sys.argv[3] if len(sys.argv) > 3 else "raw"
PORT = 9261
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
user32 = ctypes.windll.user32

try:
    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
    print(json.dumps({"error": "port_busy — 남은 크롬이 있다. 붙어서 재면 값이 무효라 중단"}))
    sys.exit(9)
except OSError:
    pass

profile = tempfile.mkdtemp(prefix="repro-hidden-")


def kill() -> None:
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            if profile in " ".join(process.info["cmdline"] or []):
                process.kill()
        except Exception:  # noqa: BLE001
            pass


atexit.register(kill)
_hook = sys.excepthook
sys.excepthook = lambda *a: (kill(), _hook(*a))


def ours() -> set[int]:
    return {p.pid for p in psutil.process_iter(["name", "cmdline"])
            if (p.info["name"] or "").lower() == "chrome.exe" and profile in " ".join(p.info["cmdline"] or [])}


def windows() -> list[int]:
    pids, found = ours(), []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _):  # type: ignore[no-untyped-def]
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            found.append(hwnd)
        return True

    user32.EnumWindows(proto(visit), None)
    return found


keep = user32.GetForegroundWindow()


def sink(hwnd: int) -> None:
    if MODE == "min":
        user32.ShowWindow(hwnd, 7)  # SW_SHOWMINNOACTIVE
    else:
        user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_BOTTOM · NOSIZE|NOMOVE|NOACTIVATE
    if keep and user32.GetForegroundWindow() != keep:
        user32.SetForegroundWindow(keep)


startup = subprocess.STARTUPINFO()
startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = 7 if MODE == "min" else 4
subprocess.Popen([CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                  "--no-first-run", "--no-default-browser-check"], startupinfo=startup)
stop_at = time.time() + 8


def watch() -> None:
    while time.time() < stop_at:
        for hwnd in windows():
            sink(hwnd)
        time.sleep(0.05)


threading.Thread(target=watch, daemon=True).start()
for _ in range(50):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
        break
    except OSError:
        time.sleep(0.2)

with sync_playwright() as pw:
    context = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}").contexts[0]
    anchor = context.pages[0]
    anchor.goto("data:text/html,<h1>active tab</h1>")
    page = anchor
    if TARGET == "background":
        before = {id(p) for p in context.pages}
        session = context.new_cdp_session(anchor)
        session.send("Target.createTarget", {"url": "about:blank", "background": True})
        session.detach()
        for _ in range(30):
            fresh = [p for p in context.pages if id(p) not in before]
            if fresh:
                page = fresh[-1]
                break
            anchor.wait_for_timeout(100)
        page.goto("data:text/html,<h1>background tab</h1>")
    time.sleep(4)  # 창 내리기가 자리 잡게
    row: dict = {"mode": MODE, "target": TARGET, "kind": KIND,
                 "iconic": [bool(user32.IsIconic(h)) for h in windows()],
                 "visibility_in_page": page.evaluate("document.visibilityState"),
                 "chrome_in_front": user32.GetForegroundWindow() in windows()}

    if KIND == "product":
        from alture_jarvis.browser import BrowserWorker
        from alture_jarvis.config import JarvisConfig

        root = Path(profile)
        worker = BrowserWorker(JarvisConfig(runtime_root=root, data_dir=root / "d", output_dir=root / "o"))

        class _Watching:
            def active(self) -> bool:
                return False

        worker.presence = _Watching()
        worker.config.browser_allow_foreground = False
        worker._context, worker._page = context, page
        worker._context_alive = lambda: True  # type: ignore[method-assign]
        calls = []
        for _ in range(3):
            started = time.time()
            try:
                frame = worker._capture_live_frame()
                outcome = f"ok {len(frame['jpeg'])}B"
            except Exception as exc:  # noqa: BLE001
                outcome = "raised " + str(exc)[:60]
            calls.append([outcome, round(time.time() - started, 3)])
        started = time.time()
        page.evaluate("document.title")
        row["product_frames"] = calls
        row["next_action_sec"] = round(time.time() - started, 3)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    else:
        def guard() -> None:
            time.sleep(8)
            row["raw_capture"] = "HANG>8s"
            print(json.dumps(row, ensure_ascii=False), flush=True)
            kill()
            os._exit(3)

        threading.Thread(target=guard, daemon=True).start()
        started = time.time()
        session = context.new_cdp_session(page)
        data = session.send("Page.captureScreenshot", {"format": "jpeg", "quality": 55}).get("data") or ""
        row["raw_capture"] = f"ok {len(data) * 3 // 4}B {round(time.time() - started, 3)}s"
        print(json.dumps(row, ensure_ascii=False), flush=True)
kill()
shutil.rmtree(profile, ignore_errors=True)
