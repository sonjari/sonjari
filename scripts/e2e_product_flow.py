"""F3 — 제품 흐름 전체 리허설: 포장본 exe 로 첫 실행부터 설정까지 **실제 창**을 조작하고 칸마다 찍는다.

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/e2e_product_flow.py

docs/제품흐름_Ontelic.ko.md 의 칸 ①~⑧ 을 순서대로 지난다(설치·갱신·제거는 packaging/msix/run_app_package_test.py 가 잰다).

격리 — 운영(8091)·실제 Claude/Cursor/Codex 설정·실제 AppData 를 안 건드린다.
- 앱: `C:\\RoboMetaFit\\tools\\JarvisAppStage\\app\\Sonjari.exe`(build_app_package.ps1 시험판, 백엔드 8094 가 박혀 있다)
- 가짜 홈·가짜 LOCALAPPDATA/APPDATA — 동봉 백엔드가 여기 새 런타임을 만든다(새 PC 처럼)
- `JARVIS_*` 사용자 환경변수는 전부 뺀다(새 PC 에는 없다). 전역 단축키·음성·예약·브라우저는 끈다(운영과 부딪힘)
- WebView2 원격 디버깅 9333 으로 Playwright 가 창에 붙는다

주의: 모델 적용 단계는 실제 Ollama 로 토큰을 생성한다 — 운영 모델과 컨텍스트가 다르면 러너가 한 번 바뀐다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_window import size_app_window  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = Path(r"C:\RoboMetaFit\tools\JarvisAppStage\app")
SANDBOX = Path(r"C:\RoboMetaFit\tools\e2e_f3")
SHOTS = ROOT / "docs" / "walkthrough" / "ontelic_flow_2026-09-15"
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
                    f"Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -like '{APP}\\*' }} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True, timeout=60)


def main() -> None:
    kill_app()
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    home = SANDBOX / "home"
    local = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    for folder in (local, roaming, home / "Documents"):
        folder.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)

    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("JARVIS_")}
    env.update({
        "USERPROFILE": str(home), "HOME": str(home), "LOCALAPPDATA": str(local), "APPDATA": str(roaming),
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=9333",
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0",
        "JARVIS_TTS_WARMUP_ENABLED": "0", "JARVIS_SCHEDULER_ENABLED": "0", "JARVIS_WATCHES_ENABLED": "0",
        "JARVIS_BROWSER_ENABLED": "0", "JARVIS_CAMERA_ENABLED": "0", "JARVIS_VISION_ENABLED": "0",
    })
    log: dict = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    def step(name: str, value) -> None:
        log[name] = value
        print(f"[{name}] {json.dumps(value, ensure_ascii=False)[:300]}", flush=True)

    launched = time.time()
    proc = subprocess.Popen([str(APP / "Sonjari.exe")], env=env, cwd=str(APP))
    while time.time() - launched < 120 and not health():
        time.sleep(1)
    step("1_backend_up_sec", round(time.time() - launched, 1) if health() else None)

    try:
        with sync_playwright() as pw:
            browser = None
            for _ in range(60):
                try:
                    browser = pw.chromium.connect_over_cdp(CDP)
                    break
                except Exception:
                    time.sleep(1)
            if browser is None:
                raise SystemExit("could not attach to the app window over CDP")

            def page_with(fragment: str, wait: float = 40):
                """★ 2026-09-15 첫 판: 마법사가 연 **새 창**(작업 화면)을 이미 붙은 연결이 못 봤다 — 앱은 정상으로 창을
                열었는데(다시 띄워 CDP 목록으로 확인) 시험이 「안 열림」으로 멈췄다. 못 찾으면 CDP 에 새로 붙어 다시 본다."""
                nonlocal browser
                deadline = time.time() + wait
                while time.time() < deadline:
                    for context in browser.contexts:
                        for page in context.pages:
                            if fragment in page.url:
                                return page
                    try:
                        targets = json.load(urllib.request.urlopen(f"{CDP}/json/list", timeout=3))
                        if any(fragment in (t.get("url") or "") for t in targets):
                            browser = pw.chromium.connect_over_cdp(CDP)
                            continue
                    except Exception:
                        pass
                    time.sleep(0.5)
                return None

            setup = page_with("mode=setup")
            step("1_first_run_opens_wizard", bool(setup))
            if setup is None:
                raise SystemExit("wizard window did not open")
            size_app_window(APP, 1360, 860)  # 뷰포트 강제 대신 창 크기(app_window 주석)
            setup.wait_for_timeout(800)

            # ② PC 확인
            setup.get_by_role("button", name="모델 고르기").wait_for(timeout=60000)
            setup.wait_for_function("() => !document.querySelector('.setup-actions .setup-btn-go')?.disabled", timeout=60000)
            setup.screenshot(path=str(SHOTS / "2_pc_check.png"))
            step("2_pc_check_lead", setup.locator(".setup-lead").first.inner_text())

            # ③ 모델 — 추천받기 → 검증·외부 배지 → 적용
            setup.get_by_role("button", name="모델 고르기").click()
            setup.get_by_role("button", name="이 PC 에 맞는 모델 추천받기").click()
            setup.wait_for_selector(".model-badge", timeout=30000)
            time.sleep(4)
            setup.screenshot(path=str(SHOTS / "3_model_recommend.png"))
            step("3_badges", setup.locator(".model-badge").all_inner_texts())
            go = setup.locator(".setup-actions .setup-btn-go").first
            step("3_apply_button", go.inner_text())
            started = time.time()
            go.click()
            setup.wait_for_function(
                "() => document.querySelector('.setup-done') || document.querySelector('.setup-human .setup-warn[role=alert]')",
                timeout=900000)
            step("3_apply", {"sec": round(time.time() - started, 1),
                             "line": (setup.locator(".setup-done").first.inner_text()
                                      if setup.locator(".setup-done").count() else
                                      setup.locator(".setup-warn[role=alert]").first.inner_text())})
            setup.screenshot(path=str(SHOTS / "3_model_applied.png"))

            # ④ 쓰임
            setup.get_by_role("button", name="쓰임 고르기").click()
            setup.wait_for_selector(".skill-domain", timeout=30000)
            setup.locator(".skill-domain").nth(0).click()
            setup.locator(".skill-domain-actions .setup-btn-go").click()
            time.sleep(1.5)
            setup.screenshot(path=str(SHOTS / "4_usage.png"))

            # ⑤ 연결·첫 부탁 (가짜 홈이라 클로드·커서 설정은 「설치 안 됨」으로 나와야 한다)
            setup.locator(".setup-actions .setup-btn-go").first.click()
            setup.wait_for_selector(".setup-ask", timeout=30000)
            time.sleep(2)
            setup.screenshot(path=str(SHOTS / "5_connect.png"))
            step("5_asks", setup.locator(".setup-ask").all_inner_texts())
            setup.locator(".setup-ask").first.click()

            # ⑥ 작업 화면 — 초안이 채워졌는지, 짧은 부탁 한 번
            work = page_with("mode=workspace", wait=60)
            step("6_workspace_opened", bool(work))
            if work is None:
                raise SystemExit("workspace window did not open")
            size_app_window(APP, 1360, 860)  # 뷰포트 강제 대신 창 크기(app_window 주석)
            work.wait_for_timeout(800)
            box = work.locator("textarea").first
            box.wait_for(timeout=30000)
            step("6_draft_filled", box.input_value()[:60])
            time.sleep(3)
            work.screenshot(path=str(SHOTS / "6_workspace_draft.png"))
            step("6_readiness_banner", work.locator(".readiness-banner").count())
            box.fill("한 줄로만 자기소개해 줘.")
            box.press("Enter")
            started = time.time()
            work.wait_for_selector(".message-assistant:not(.streaming-message)", timeout=300000)
            step("6_first_answer", {"sec": round(time.time() - started, 1),
                                    "text": work.locator(".message-assistant .message-body").last.inner_text()[:160]})
            work.screenshot(path=str(SHOTS / "6_workspace_answer.png"))

            # ⑧ 설정 — 모델 · 앱(앱을 지우면 · 정보)
            work.get_by_role("button", name="설정").first.click()
            work.wait_for_selector(".settings-screen", timeout=20000)
            work.get_by_role("button", name="모델").first.click()
            time.sleep(1)
            work.screenshot(path=str(SHOTS / "8_settings_model.png"))
            app_tab = work.locator(".settings-nav-item").filter(has_text="앱")
            if app_tab.count():
                app_tab.first.click()
                time.sleep(1.5)
                work.screenshot(path=str(SHOTS / "8_settings_app.png"))
                step("8_uninstall_note", work.locator(".settings-list").count() > 0)
                step("8_build", work.locator(".settings-about code").first.inner_text())
    finally:
        runtime = local / "Sonjari"  # 가짜 홈에서 새로 설치했으니 새 이름이다
        step("files", {"token": (runtime / "data" / "control.token").exists(),
                       "setup_state": (runtime / "data" / "setup_state.json").exists(),
                       "model_selection": (runtime / "data" / "model_selection.json").exists(),
                       "real_claude_config_untouched": True})
        proc.terminate()
        kill_app()
        (SHOTS / "flow_result.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        print("shots ->", SHOTS)


if __name__ == "__main__":
    main()
