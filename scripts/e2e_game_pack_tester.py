"""게임 팩을 **테스터처럼** 한 판 — 스토어판(시험 포장본)에서 설정 › 팩 켜기부터 유니티 점검 답까지 (2026-10-01).

왜: 베타 테스터 둘(크래프톤 CTO·데브시스터즈 총괄디렉터)이 게임 쪽이라 **제일 먼저 써 볼 기능**이다. 게임 팩은 일부러 기본
꺼짐(09-27)이라, 사람이 「설정 › 팩」에서 켜고 → 마법사가 프로젝트 허락을 묻고 → 점검을 시키는 길이 실제로 이어지는지 본다.

격리: `e2e_first_run_oneshot.py` 와 같은 가짜 홈(`C:\\RoboMetaFit\\tools\\e2e_oneshot`)·8094·CDP 9333. 대표의 실제 클로드
지침(CLAUDE.md)은 안 건드린다 — 팩을 켜면 이은 AI 지침에 한 줄이 들어가는데, 여기선 가짜 홈의 것이다.
가짜 홈은 **지우지 않는다**(앞 판의 첫 실행이 끝난 상태에서 시작한다 — 그래야 테스터가 마법사를 끝낸 뒤와 같다).

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/e2e_game_pack_tester.py --step look
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

ROOT = Path(__file__).resolve().parents[1]
APP = Path(r"C:\RoboMetaFit\tools\JarvisAppStage\app")
SANDBOX = Path(r"C:\RoboMetaFit\tools\e2e_oneshot")
HOME = SANDBOX / "home"
BASE = "http://127.0.0.1:8094"
CDP = "http://127.0.0.1:9333"
SHOTS = ROOT / "docs" / "walkthrough" / "game_pack_tester_2026-10-01"


def health() -> dict:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def token() -> str:
    return (HOME / "AppData" / "Local" / "Sonjari" / "data" / "control.token").read_text(encoding="utf-8").strip()


def api(path: str, body: dict | None = None, method: str = "GET") -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method="POST" if body is not None else method,
                                     headers={"X-Jarvis-Token": token(), "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def env() -> dict[str, str]:
    local, roaming = HOME / "AppData" / "Local", HOME / "AppData" / "Roaming"
    out = {k: v for k, v in os.environ.items() if not k.upper().startswith("JARVIS_")}
    out.update({
        "USERPROFILE": str(HOME), "HOME": str(HOME), "LOCALAPPDATA": str(local), "APPDATA": str(roaming),
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=9333",
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0",
        "JARVIS_TTS_WARMUP_ENABLED": "0", "JARVIS_SCHEDULER_ENABLED": "0", "JARVIS_WATCHES_ENABLED": "0",
        "JARVIS_CAMERA_ENABLED": "0", "JARVIS_VISION_ENABLED": "0",
    })
    return out


def launch() -> None:
    if health():
        return
    subprocess.Popen([str(APP / "Sonjari.exe")], env=env(), cwd=str(APP))
    started = time.time()
    while time.time() - started < 120 and not health():
        time.sleep(1)
    print("[..] backend_up_sec", round(time.time() - started, 1), flush=True)


def page_of(pw):
    for _ in range(60):
        try:
            browser = pw.chromium.connect_over_cdp(CDP)
            for context in browser.contexts:
                for page in context.pages:
                    if not page.is_closed() and "devtools" not in page.url:
                        return browser, page
        except Exception:
            pass
        time.sleep(1)
    raise SystemExit("앱 창에 CDP 로 못 붙었다")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", default="look")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--tag", default="1")
    ap.add_argument("--budget", type=float, default=900)
    args = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    launch()
    with sync_playwright() as pw:
        _browser, page = page_of(pw)
        page.wait_for_timeout(2500)
        print("[..] url", page.url)
        page.screenshot(path=str(SHOTS / f"{args.step}_0.png"))
        if args.step == "look":
            print("[..] buttons", [b.strip() for b in page.locator("button").all_inner_texts() if b.strip()][:60])
        if args.step == "settings":
            # 테스터가 하는 그대로: 왼쪽 아래 「설정」을 누르고, 팩이 어디 있는지 본다.
            if not page.locator(".settings-veil").count():
                page.get_by_role("button", name="설정").first.click()
                page.wait_for_timeout(1500)
            page.screenshot(path=str(SHOTS / "settings_1.png"))
            print("[..] nav", [b.strip() for b in page.locator("nav button, aside button, [role=tab]").all_inner_texts() if b.strip()][:40])
            text = page.locator("body").inner_text()
            print("[..] 팩 글자 있음", "팩" in text, "게임 팩" in text)
            veil = page.locator(".settings-veil")
            veil.get_by_role("button", name="팩", exact=True).first.click()
            page.wait_for_timeout(1500)
            page.screenshot(path=str(SHOTS / "settings_2_packs.png"))
            main = veil
            print("[..] 팩 화면 글", main.inner_text()[:1500])
            print("[..] 팩 화면 버튼", [b.strip() for b in main.locator("button").all_inner_texts() if b.strip()][:30])
        if args.step == "enable":
            if not page.locator(".settings-veil").count():
                page.get_by_role("button", name="설정").first.click()
                page.wait_for_timeout(1500)
            veil = page.locator(".settings-veil")
            veil.get_by_role("button", name="팩", exact=True).first.click()
            page.wait_for_timeout(1200)
            started = time.time()
            veil.get_by_role("button", name="켜기", exact=True).first.click()
            page.wait_for_timeout(4000)
            print("[..] 켜기 뒤 초", round(time.time() - started, 1))
            page.screenshot(path=str(SHOTS / "enable_1_after.png"))
            print("[..] 켠 뒤 글", veil.inner_text()[:1800])
            print("[..] 켠 뒤 버튼", [b.strip() for b in veil.locator("button").all_inner_texts() if b.strip()][14:40])
            print("[..] API 팩", json.dumps(api("/v1/packs")["packs"][0].get("enabled")))
        if args.step == "allow":
            if not page.locator(".settings-veil").count():
                page.get_by_role("button", name="설정").first.click()
                page.wait_for_timeout(1500)
            veil = page.locator(".settings-veil")
            veil.get_by_role("button", name="팩", exact=True).first.click()
            page.wait_for_timeout(1500)
            veil.get_by_role("button", name="이 폴더 허락").first.click()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(SHOTS / "allow_1_after.png"))
            wizard = api("/v1/packs/game/unity")
            print("[..] 허락 뒤", json.dumps({"projects": wizard.get("projects"), "next": wizard.get("next")}, ensure_ascii=False)[:600])
        if args.step == "ask":
            # 테스터가 처음 칠 법한 말 — 레시피 이름을 모르는 채로.
            prompt = args.prompt or "OntelicPlayground 유니티 프로젝트에서 너무 큰 텍스처랑 빠진 참조 있는지 점검해 줘"
            veil = page.locator(".settings-veil")
            if veil.count():
                veil.get_by_role("button", name="닫기").first.click() if veil.get_by_role("button", name="닫기").count() else page.keyboard.press("Escape")
                page.wait_for_timeout(800)
            page.get_by_role("button", name="새 대화").first.click()
            page.wait_for_timeout(1000)
            box = page.locator("textarea").first
            box.fill(prompt)
            started = time.time()
            box.press("Enter")
            print("[..] 보냄", prompt, flush=True)
            last = ""
            while time.time() - started < args.budget:
                page.wait_for_timeout(5000)
                busy = page.locator(".streaming-message").count() > 0
                cards = page.locator(".approval-card, [data-approval]").count()
                if cards:
                    print("[..] 승인 카드", round(time.time() - started), "초", flush=True)
                    page.screenshot(path=str(SHOTS / f"ask_{args.tag}_approval.png"))
                if not busy and time.time() - started > 15:
                    break
            took = round(time.time() - started, 1)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(SHOTS / f"ask_{args.tag}_done.png"))
            answers = page.locator(".message-assistant").all_inner_texts()
            last = answers[-1] if answers else ""
            print("[..] 걸린 초", took)
            print("[..] 답", last[:2500])


if __name__ == "__main__":
    main()
