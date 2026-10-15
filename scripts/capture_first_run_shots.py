"""첫 실행 마법사를 정한 화면 언어로 지나가며 찍는다 (2026-10-05, 스토어 영어 등록용).

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/capture_first_run_shots.py --lang en --name en_first_run

`e2e_first_run_oneshot.py` 는 검사가 목적이고 버튼을 한국어 이름으로 찾는다. 이것은 찍기만 한다 — 버튼을 자리(클래스)로 찾아
언어와 무관하게 지나간다. 가짜 홈을 **새로 만든다**(앞 촬영의 대화 기록이 지워진다). 끝나면 가짜 홈은 설정을 마친 상태라
`capture_store_shots.py` 를 이어서 돌릴 수 있다. Ollama 는 이 PC 의 것을 쓴다(모델 적용이 실제로 토큰을 만든다).
저장: docs/store/raw/<name>/N_*.png
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_window import size_app_window  # noqa: E402
from capture_store_shots import APP, CDP, ROOT, SANDBOX, health, kill_app  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--lang", default="en", choices=("ko", "en"))
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--apply-budget", type=float, default=1800)
    args = ap.parse_args()
    width, height = (int(v) for v in args.size.split("x"))
    out = ROOT / "docs" / "store" / "raw" / args.name
    out.mkdir(parents=True, exist_ok=True)

    kill_app()
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    home = SANDBOX / "home"
    local, roaming = home / "AppData" / "Local", home / "AppData" / "Roaming"
    for folder in (local, roaming, home / "Documents"):
        folder.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("JARVIS_")}
    env.update({
        "USERPROFILE": str(home), "HOME": str(home), "LOCALAPPDATA": str(local), "APPDATA": str(roaming),
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=9333",
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0",
        "JARVIS_TTS_WARMUP_ENABLED": "0", "JARVIS_SCHEDULER_ENABLED": "0", "JARVIS_WATCHES_ENABLED": "0",
        "JARVIS_BROWSER_ENABLED": "0", "JARVIS_CAMERA_ENABLED": "0", "JARVIS_VISION_ENABLED": "0",
    })
    subprocess.Popen([str(APP / "Sonjari.exe")], env=env, cwd=str(APP))
    started = time.time()
    while time.time() - started < 120 and not health():
        time.sleep(1)
    if not health():
        raise SystemExit("backend did not come up")

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

        def page_with(fragment: str, wait: float = 60):
            nonlocal browser
            deadline = time.time() + wait
            while time.time() < deadline:
                for context in browser.contexts:
                    for page in context.pages:
                        if fragment in page.url and not page.is_closed():
                            return page
                try:
                    browser = pw.chromium.connect_over_cdp(CDP)
                except Exception:
                    pass
                time.sleep(0.7)
            return None

        def shot(page, name: str) -> None:
            page.screenshot(path=str(out / f"{name}.png"))
            print(f"shot {name} | {' / '.join(page.locator('.setup-actions button').all_inner_texts())[:120]}", flush=True)

        setup = page_with("mode=setup")
        if setup is None:
            raise SystemExit("wizard did not open")
        setup.evaluate("(v) => window.localStorage.setItem('sonjari.ui_language', v)", args.lang)
        setup.reload()
        setup.wait_for_timeout(2500)
        size_app_window(APP, width, height)
        setup.wait_for_timeout(1200)

        # ① PC 확인 — 시작 단추가 눌릴 수 있을 때까지
        go = setup.locator(".setup-actions .setup-btn-go").first
        go.wait_for(timeout=90000)
        setup.wait_for_function("() => !document.querySelector('.setup-actions .setup-btn-go')?.disabled", timeout=90000)
        shot(setup, "1_pc_check")
        clicked = time.time()
        go.click()

        # ② 모델 — 사람 손 없이 적용까지. 받는 중·적용 중 화면도 20초마다 한 장.
        tick = 0
        while time.time() - clicked < args.apply_budget:
            if setup.locator(".setup-done").count() or setup.locator(".setup-human .setup-warn[role=alert]").count():
                break
            if int(time.time() - clicked) // 20 > tick:
                tick = int(time.time() - clicked) // 20
                setup.screenshot(path=str(out / f"2_model_working_{tick:02d}.png"))
            time.sleep(1)
        if not setup.locator(".setup-done").count():
            shot(setup, "2_model_failed")
            raise SystemExit("model was not applied — stopping here")
        print(f"model applied in {time.time() - clicked:.0f}s", flush=True)
        shot(setup, "2_model_applied")

        # ③ 쓰임
        setup.locator(".setup-actions .setup-btn-go").first.click()
        setup.wait_for_selector(".skill-domain", timeout=30000)
        setup.wait_for_timeout(800)
        shot(setup, "3_usage")
        setup.locator(".setup-actions .setup-btn-go").first.click()

        # ④ 연결
        setup.wait_for_selector(".imp-row", timeout=30000)
        # 자동 잇기가 끝난 뒤에 찍는다 — 줄의 글이 6초 동안 안 바뀌면 끝난 것으로 본다(가장 길게 90초).
        seen, steady_since, deadline = None, time.time(), time.time() + 90
        while time.time() < deadline:
            rows = setup.locator(".imp-row").all_inner_texts()
            if rows != seen:
                seen, steady_since = rows, time.time()
            elif time.time() - steady_since >= 6:
                break
            time.sleep(1)
        print("connect rows: " + " | ".join(" ".join(row.split()) for row in (seen or []))[:300], flush=True)
        shot(setup, "4_connect")
        setup.locator(".setup-actions .setup-btn-go").first.click()

        work = page_with("mode=workspace", wait=60)
        if work is None:
            raise SystemExit("product window did not open")
        size_app_window(APP, width, height)
        work.wait_for_selector("textarea", timeout=30000)
        work.wait_for_timeout(5000)
        work.screenshot(path=str(out / "5_product.png"))
        print("shot 5_product", flush=True)
    kill_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
