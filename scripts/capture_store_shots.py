"""스토어 스크린샷 찍기 (2026-09-23) — 첫 실행 E2E 가 설정을 마친 **깨끗한 가짜 홈**의 앱에 실제 과제를 맡기고
정해진 간격으로 화면을 저장한다. 사람이 쓰는 앱(대화 기록·로그인)은 안 찍힌다.

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/capture_store_shots.py --name cowork \\
        --task "다나와에서 …" [--mode cowork|code] [--every 10] [--budget 600]

먼저 `e2e_first_run_oneshot.py --size 1920x1080` 을 한 번 돌려 가짜 홈을 만들어 둔다(마법사를 안 거치고 제품 화면으로 열린다).
브라우저는 **켠다**(E2E 는 끈다) — 가짜 홈의 빈 크롬 프로필이라 개인 로그인이 없다.
저장: docs/store/raw/<name>/NN.png — 고르는 것은 사람 눈으로.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_window import size_app_window  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = Path(r"C:\RoboMetaFit\tools\JarvisAppStage\app")
SANDBOX = Path(r"C:\RoboMetaFit\tools\e2e_oneshot")
BASE = "http://127.0.0.1:8094"
CDP = "http://127.0.0.1:9333"


def health() -> dict:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def kill_app() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    # ★ 가짜 홈 프로필로 뜬 크롬도 같이 닫는다 — 앱만 닫으면 크롬 12개가 남아 가짜 홈 폴더를 쥐었다(2026-09-30).
                    #   명령줄에 가짜 홈 경로가 든 것만 — 사람이 쓰는 크롬은 건드리지 않는다.
                    f"Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -like '{APP}\\*' -or "
                    f"($_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*{SANDBOX}*') }} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True, timeout=60)
    time.sleep(1.5)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--mode", default="cowork", choices=("cowork", "code"))
    ap.add_argument("--every", type=float, default=10)
    ap.add_argument("--budget", type=float, default=600)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--keep-open", action="store_true", help="끝나도 앱을 안 끈다(다음 장면을 이어 찍을 때)")
    ap.add_argument("--workspace", default="", help="코드 모드 작업 폴더(가짜 홈 안에 만든 예제 폴더)")
    ap.add_argument("--lang", default="", choices=("", "ko", "en"),
                    help="화면 언어(영어 스토어 스크린샷은 en). 비우면 그 가짜 홈에 저장된 대로")
    ap.add_argument("--approve-after", type=float, default=0,
                    help="승인 카드가 이만큼(초) 떠 있으면 화면의 승인 단추를 누른다. 0 이면 안 누른다")
    args = ap.parse_args()

    home = SANDBOX / "home"
    if not (home / "AppData" / "Local").exists():
        raise SystemExit("가짜 홈이 없다 — 먼저 e2e_first_run_oneshot.py 를 돌릴 것")
    out = ROOT / "docs" / "store" / "raw" / args.name
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("JARVIS_")}
    env.update({
        "USERPROFILE": str(home), "HOME": str(home), "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=9333",
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0",
        "JARVIS_TTS_WARMUP_ENABLED": "0", "JARVIS_SCHEDULER_ENABLED": "0", "JARVIS_WATCHES_ENABLED": "0",
        "JARVIS_CAMERA_ENABLED": "0", "JARVIS_VISION_ENABLED": "0",
        # ★ 자기 크롬을 쓰게 한다. 기본 9222 에는 이 PC 의 평소 온텔릭 크롬이 떠 있고, 그대로 두면 거기에 **같이 붙는다**
        #   (2026-09-23 첫 촬영: 두 앱이 크롬 하나를 같이 조종해 본문 읽기가 180초씩 멈췄고, 로그인된 프로필이 찍힐 뻔했다).
        "JARVIS_BROWSER_CDP_PORT": "9444",
    })
    if not health():
        kill_app()
        subprocess.Popen([str(APP / "Sonjari.exe")], env=env, cwd=str(APP))
        started = time.time()
        while time.time() - started < 120 and not health():
            time.sleep(1)
    if not health():
        raise SystemExit("backend did not come up")
    # ★ 앞 판이 승인 카드 앞에서 멈춘 채 끝나면 그 잡이 가짜 홈에 남아 「새 대화」가 막힌다(2026-09-30: 30초 대기 뒤 실패).
    #   촬영은 늘 새 판부터 — 남은 잡은 취소한다. 가짜 홈 기록이라 사람이 쓰는 앱과 무관하다.
    tokens = sorted((SANDBOX / "home").glob("AppData/Local/*/data/control.token"))
    if tokens:
        token = tokens[-1].read_text(encoding="utf-8").strip()
        def api(path: str, body: dict | None = None) -> object:
            req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json", "X-Jarvis-Token": token},
                                         method="POST" if body is not None else "GET")
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        for job in api("/v1/jobs?limit=20") or []:
            if str(job.get("status")) in {"queued", "running", "waiting_approval", "waiting_continuation"}:
                api(f"/v1/jobs/{job['id']}/cancel", {})
                print(f"left-over job cancelled: {str(job['id'])[:8]} ({job.get('status')})", flush=True)
    width, height = (int(v) for v in args.size.split("x"))

    with sync_playwright() as pw:
        browser = None
        for _ in range(60):
            try:
                browser = pw.chromium.connect_over_cdp(CDP)
                break
            except Exception:
                time.sleep(1)
        if browser is None:
            raise SystemExit("could not attach over CDP")
        page = None
        for _ in range(60):
            pages = [p for c in browser.contexts for p in c.pages if "mode=setup" not in p.url and not p.is_closed()]
            if pages:
                page = pages[0]
                break
            time.sleep(1)
        if page is None:
            raise SystemExit("product window not found")
        size_app_window(APP, width, height)
        page.wait_for_timeout(1500)
        if args.lang:
            # 화면 언어는 창의 저장소에 있다(`ui/src/i18n.ts` STORAGE_KEY). 바꾸고 다시 그리면 화면이 백엔드에도 알린다.
            page.evaluate("(v) => window.localStorage.setItem('sonjari.ui_language', v)", args.lang)
            page.reload()
            page.wait_for_timeout(3000)
        # 모드 전환은 role=tab. 앞 판이 다른 모드로 끝났을 수 있으니 **매번** 누른다(09-23: 코드 모드에 남아 과제가 엉뚱한 칸으로 갔다).
        page.get_by_role("tab", name="Code" if args.mode == "code" else "Cowork").first.click()
        page.wait_for_timeout(800)
        if args.mode == "code":
            page.wait_for_timeout(1200)
            if args.workspace:
                Path(args.workspace).mkdir(parents=True, exist_ok=True)
                field = page.locator(".code-workspace-field input").first
                field.fill(args.workspace)
                page.wait_for_timeout(500)
        page.get_by_role("button", name="New conversation" if args.lang == "en" else "새 대화").first.click()
        page.wait_for_timeout(800)
        page.screenshot(path=str(out / "00_home.png"))
        # ★ 대화 입력칸만 — 코드 모드 오른쪽의 「써 보니 무엇이 이상했나요?」(#code-preview-note)도 textarea 다.
        box = page.locator("textarea:not(#code-preview-note)").last
        box.click()
        box.fill(args.task)
        page.wait_for_timeout(600)
        page.screenshot(path=str(out / "00_typed.png"))
        box.press("Enter")
        started = time.time()
        n = 1
        card_seen_at = 0.0
        while time.time() - started < args.budget:
            page.wait_for_timeout(int(args.every * 1000))
            page.screenshot(path=str(out / f"{n:02d}.png"))
            print(f"shot {n:02d} at {round(time.time() - started)}s", flush=True)
            n += 1
            # ★ 새 가짜 홈은 권한이 「수동」이라 문서 폴더에 쓰기 전에 승인 카드가 뜬다(2026-09-30: 촬영 판이 그 카드 앞에서
            #   10분 예산을 다 쓰고 끝났다). 카드가 뜬 모습을 몇 장 찍은 뒤 **사람처럼 화면의 승인 단추를** 누른다.
            approve = page.locator("section.spine-decision button.approve")
            # 질문 카드(ask_user)는 승인 단추 대신 선택지다 — 추천이 있으면 그것, 없으면 첫 선택지를 고른다.
            question = page.locator("section.question-card button.question-option")
            if args.approve_after and question.count():
                card_seen_at = card_seen_at or time.time()
                if time.time() - card_seen_at >= args.approve_after:
                    recommended = page.locator("section.question-card button.question-option.recommended")
                    (recommended.first if recommended.count() else question.first).click()
                    card_seen_at = 0.0
                    print(f"answered question at {round(time.time() - started)}s", flush=True)
            elif args.approve_after and approve.count():
                card_seen_at = card_seen_at or time.time()
                if time.time() - card_seen_at >= args.approve_after:
                    approve.first.click()
                    card_seen_at = 0.0
                    print(f"approved at {round(time.time() - started)}s", flush=True)
            # 끝났나: 잡이 도는 동안에만 보이는 중지 단추(.stop-button, WorkspaceApp.tsx)가 사라지면 끝난 판이다
            busy = page.locator("button.stop-button").count()
            if not busy and time.time() - started > 30:
                page.wait_for_timeout(4000)
                page.screenshot(path=str(out / f"{n:02d}_final.png"))
                print("done", flush=True)
                break
    if not args.keep_open:
        kill_app()
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
