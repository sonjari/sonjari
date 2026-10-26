"""레딧 영상 「클로드 한도 → 손자리가 이어받아 브라우저 조사 → 엑셀」 한 판 촬영 (2026-10-23 대표).

준비는 `film_takeover_prep.py`(진짜 클로드 몇 걸음 + 끝에 데모 한도 줄 하나). 여기서부터는 **편집 없는 실제 손자리**다.
- 손자리 창이 화면 전체 · 화면 전체를 한 판으로 녹화(엑셀 창까지).
- 사람이 치는 속도로 이어받기 말을 넣는다.
- 이어받기 카드의 시작 · 승인 카드 · 질문 카드(추천)는 사람이 PC 에서 누르는 자리 — 촬영용 손자리에서만 그 단추를 누른다.

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/film_takeover.py --out <mp4>
"""
from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import film_handoff_excel as base  # noqa: E402  (촬영용 손자리 띄우기 · 창 고정 · 엑셀 창 찾기를 그대로 쓴다)
from playwright.sync_api import sync_playwright  # noqa: E402

W, H = base.HALF_W * 2, base.HEIGHT


def pin_top(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """맨 위에 **고정**(HWND_TOPMOST) — 10-23 첫 판에서 사람이 쓰던 크롬이 손자리 창 위로 올라와 녹화를 가렸다."""
    import ctypes  # noqa: PLC0415
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetWindowPos(hwnd, -1, x, y, w, h, 0x0040)   # HWND_TOPMOST · SWP_SHOWWINDOW


def maximize_top(hwnd: int) -> None:
    """최대화 + 맨 위 고정 — 테두리 · 둥근 모서리 · 뒤가 비치는 틈이 안 보이게(10-23 대표 「전체화면이 아니라 엣지가 이상」)."""
    import ctypes  # noqa: PLC0415
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 3)   # SW_MAXIMIZE
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # HWND_TOPMOST · 크기 · 자리 그대로


def unpin_top(hwnd: int) -> None:
    import ctypes  # noqa: PLC0415
    ctypes.windll.user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)   # HWND_NOTOPMOST · 크기 · 자리 그대로
MESSAGE = ("Claude Code hit its usage limit in the middle of my GitHub research. "
           "Take over and finish it, then open the Excel file for me.")


def human_type(page, text: str) -> None:
    """사람이 치는 속도 — 글자마다 흔들리는 간격, 띄어쓰기 · 쉼표 · 마침표 뒤에 조금 더."""
    rnd = random.Random(23)
    for ch in text:
        page.keyboard.type(ch)
        delay = max(0.03, rnd.gauss(0.075, 0.03))
        if ch == " ":
            delay += rnd.uniform(0.02, 0.08)
        if ch in ",.":
            delay += rnd.uniform(0.15, 0.3)
        time.sleep(delay)


def click_if(page, selector: str, log: list[str], started: float, label: str, pause_ms: int = 1500) -> bool:
    loc = page.locator(selector).first
    try:
        if loc.count() and loc.is_visible() and loc.is_enabled():
            page.wait_for_timeout(pause_ms)   # 카드가 화면에 잠깐 보이게
            loc.click()
            log.append(f"{round(time.time() - started)}s clicked {label}")
            print(log[-1], flush=True)
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"{label} check: {type(exc).__name__}", flush=True)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget", type=float, default=1500)
    ap.add_argument("--dry", action="store_true", help="녹화 · 맨 위 고정 없이 한 판만 돌린다(원인 확인용)")
    args = ap.parse_args()

    if not base.health():
        subprocess.Popen([str(base.APP / "Sonjari.exe")], env=base.sandbox_env(), cwd=str(base.APP))
        t0 = time.time()
        while time.time() - t0 < 120 and not base.health():
            time.sleep(1)
    if not base.health():
        raise SystemExit("sandbox backend did not come up")
    token = (base.SANDBOX / "home" / "AppData" / "Local" / "Sonjari" / "data" / "control.token").read_text(encoding="utf-8").strip()
    before = {str(j.get("id")) for j in base.api(token, "/v1/jobs?limit=50") or []}

    with sync_playwright() as pw:
        browser = None
        for _ in range(60):
            try:
                browser = pw.chromium.connect_over_cdp(base.CDP)
                break
            except Exception:
                time.sleep(1)
        if browser is None:
            raise SystemExit("could not attach over CDP")
        page = next((p for c in browser.contexts for p in c.pages if "mode=setup" not in p.url), None)
        if page is None:
            raise SystemExit("product window not found")
        if page.evaluate("() => window.localStorage.getItem('sonjari.ui_language')") != "en":
            page.evaluate("() => window.localStorage.setItem('sonjari.ui_language', 'en')")
            page.reload()
            page.wait_for_timeout(4000)
        if not args.dry:
            base.size_app_window(base.APP, W, H, x=0, y=0)
            for hwnd in base.app_windows():
                maximize_top(hwnd)
        page.wait_for_timeout(1000)
        page.get_by_role("tab", name="Cowork").first.click()
        page.get_by_role("button", name=re.compile(r"^(새 대화|New conversation)$")).first.click()
        page.wait_for_timeout(1500)

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        rec = None if args.dry else subprocess.Popen([str(base.FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
                                "-f", "gdigrab", "-framerate", "15", "-offset_x", "0", "-offset_y", "0",
                                "-video_size", f"{W}x{H}", "-draw_mouse", "1", "-i", "desktop",
                                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)],
                               stdin=subprocess.PIPE)
        started = time.time()
        log: list[str] = []
        time.sleep(2.0)
        box = page.locator("textarea").first
        box.click()
        time.sleep(0.6)
        if args.dry:
            page.keyboard.type(MESSAGE)
        else:
            human_type(page, MESSAGE)
        time.sleep(0.8)
        page.keyboard.press("Enter")
        log.append(f"{round(time.time() - started)}s message sent")
        print(log[-1], flush=True)

        done_at = 0.0
        placed: set[int] = set()
        excel_shown: dict[int, float] = {}   # 엑셀 창 → 작게 뜬 시각(2.5초 뒤 전체 화면으로 · 나래 씨 의견)
        excel_full: dict[int, float] = {}
        last_print = 0.0
        while time.time() - started < args.budget:
            time.sleep(1.5)
            for x_hwnd in ([] if args.dry else base.excel_windows()):
                if x_hwnd not in placed:
                    time.sleep(1.0)
                    pin_top(x_hwnd, W - 1000, 160, 940, 600)
                    placed.add(x_hwnd)
                    excel_shown[x_hwnd] = time.time()
                    log.append(f"{round(time.time() - started)}s excel window placed")
                    print(log[-1], flush=True)
            for x_hwnd, shown_at in excel_shown.items():
                if x_hwnd not in excel_full and time.time() - shown_at > 2.5:
                    maximize_top(x_hwnd)
                    excel_full[x_hwnd] = time.time()
                    log.append(f"{round(time.time() - started)}s excel maximized")
                    print(log[-1], flush=True)
            click_if(page, ".takeover-primary", log, started, "takeover start")
            click_if(page, ".decision-actions button.approve", log, started, "approve")
            click_if(page, ".question-option.recommended", log, started, "question (recommended)")
            jobs = [j for j in base.api(token, "/v1/jobs?limit=20") or [] if str(j.get("id")) not in before]
            if jobs and all(str(j.get("status")) in {"completed", "failed", "cancelled"} for j in jobs):
                if not done_at:
                    done_at = time.time()
                    log.append(f"{round(done_at - started)}s jobs finished: {[str(j.get('status')) for j in jobs]}")
                    print(log[-1], flush=True)
                full_for = max((time.time() - at for at in excel_full.values()), default=0.0)
                if (excel_full and full_for > 6) or time.time() - done_at > 40:
                    break
            elif jobs and done_at:
                done_at = 0.0
            if time.time() - last_print > 20:
                last_print = time.time()
                print(f"{round(time.time() - started)}s jobs={[str(j.get('status')) for j in jobs]}", flush=True)
        if rec is not None:
            try:
                rec.stdin.write(b"q")
                rec.stdin.flush()
            except OSError:
                pass
            rec.wait(timeout=60)
        for hwnd in [*base.app_windows(), *placed]:
            unpin_top(hwnd)
    out.with_suffix(".log.txt").write_text("\n".join(log), encoding="utf-8")
    print(f"saved -> {out}  ({round(time.time() - started)}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
