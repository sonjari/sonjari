"""첫 실행 한 번에 — 설치 파일(포장본 exe)로 **시작 버튼 한 번부터 제품 화면·첫 답·설정 › 모델까지** (2026-09-17).

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/e2e_first_run_oneshot.py --round 1 [--size 1180x780]

2026-09-16 노트북 첫 설치에서 한 판에 나온 고장들을 **기계가** 잡게 한다:
  창이 3개 떴다 · 받는 중인지 안 보였다 · 연결까지 마쳤는데 끝내는 버튼이 없었다 · 받기가 끝났는데 적용이 안 됐다 ·
  「모델 고르기」 글자가 세로로 쌓였다 · 받지도 않은 모델 이름이 머리에 떴다.

검사(판마다 `checks` 에 참/거짓으로 남는다):
  one_window_*       단계마다 온텔릭 창이 하나인가(보이는 최상위 창을 전부 센다 — MainWindowTitle 은 하나만 본다)
  no_vertical_text_* 글자가 세로로 쌓이거나 버튼 밖으로 넘친 요소가 없나(DOM 크기로 판정, 찾으면 목록을 남긴다)
  autopilot_applied  시작 한 번 뒤 사람 손 없이 「적용했습니다」까지 갔나
  no_skip_while_pulling 받는 중에 「받는 동안 다음으로」 같은 샛길이 없나
  finish_opens_product 「온텔릭 시작하기」 → 마법사가 닫히고 제품 화면 하나
  chip_shows_applied_model 머리의 모델 표시가 적용한 모델인가
  no_readiness_banner 「모델이 없습니다」 배너가 안 뜨나
  relaunch_skips_wizard 앱을 다시 켜면 마법사 없이 제품 화면만

격리: 가짜 홈·LOCALAPPDATA·APPDATA, `JARVIS_*` 제거, 운영(8091)과 다른 8094. 실제 Claude 설정은 가짜 홈이라 안 건드린다.
Ollama 는 이 PC 의 것을 쓴다(모델 적용 단계가 실제로 토큰을 만든다).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes
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

# 글자가 세로로 쌓였거나(폭이 글자 두세 개인데 높이는 여러 줄) 버튼 밖으로 넘친 것을 찾는다.
VERTICAL_TEXT_JS = """
() => {
  const bad = [];
  const nodes = document.querySelectorAll('button, a, [role=button], .model-chip, .setup-btn-go, .setup-btn-quiet, .imp-link, .readiness-action, .model-row-btn, summary');
  for (const el of nodes) {
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    const text = (el.innerText || '').trim();
    if (text.length < 3 || text.includes('\\n')) continue;
    const font = parseFloat(style.fontSize) || 14;
    const line = parseFloat(style.lineHeight) || font * 1.4;
    const lines = Math.round((rect.height - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)) / line);
    const vertical = lines >= 3 && rect.width < font * 4;
    const overflow = el.scrollWidth > el.clientWidth + 2 && style.overflow === 'visible' && el.tagName === 'BUTTON';
    if (vertical || overflow) bad.push({text: text.slice(0, 30), w: Math.round(rect.width), h: Math.round(rect.height), vertical, overflow});
  }
  return bad;
}
"""


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
    time.sleep(1.5)


def app_windows() -> list[str]:
    """포장본 exe 의 보이는, 작업 표시줄에 뜨는 크기의 최상위 창 제목."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -eq '{APP / 'Sonjari.exe'}' }} | "
                          "ForEach-Object { $_.ProcessId }"], capture_output=True, text=True, timeout=30).stdout
    pids = {int(x) for x in out.split() if x.strip().isdigit()}
    user32 = ctypes.windll.user32
    titles: list[str] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):  # type: ignore[no-untyped-def]
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids or not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right - rect.left < 50 or rect.bottom - rect.top < 50 or user32.GetWindowLongW(hwnd, -20) & 0x80:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        titles.append(buffer.value)
        return True

    user32.EnumWindows(proto(visit), 0)
    return sorted(titles)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--size", default="", help="창 크기 WxH — 비우면 앱 기본 크기 그대로(사람이 처음 보는 크기)")
    ap.add_argument("--apply-budget", type=float, default=1800)
    ap.add_argument("--ollama-url", default="", help="isolate the rehearsal from the running user's Ollama server")
    ap.add_argument("--laptop-like", action="store_true",
                    help="노트북 조건: Claude Desktop 만 설치·켜져 있음, PATH 에 claude 없음(Desktop 에 딸린 Claude Code 만)")
    ap.add_argument("--switch-to", default="", help="설정 › 모델에서 이 이름의 모델로 「바꾸기」까지 해 본다(안 받은 모델이면 실제로 받는다)")
    args = ap.parse_args()
    shots = ROOT / "docs" / "walkthrough" / "ontelic_first_run_2026-09-17" / f"r{args.round}"
    shots.mkdir(parents=True, exist_ok=True)
    size = tuple(int(x) for x in args.size.lower().split("x")) if args.size else None

    kill_app()
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    home = SANDBOX / "home"
    local, roaming = home / "AppData" / "Local", home / "AppData" / "Roaming"
    for folder in (local, roaming, home / "Documents"):
        folder.mkdir(parents=True, exist_ok=True)
    desktop_config = roaming / "Claude" / "claude_desktop_config.json"
    if args.laptop_like:
        # ① Claude Desktop 설치 흔적(설정 파일) ② Desktop 에 딸린 Claude Code — 실제 PC 의 것을 가짜 홈으로 복사
        desktop_config.parent.mkdir(parents=True, exist_ok=True)
        desktop_config.write_text(json.dumps({"preferences": {"e2e": True}}), encoding="utf-8")
        real_bundle = sorted((Path(os.environ["APPDATA"]) / "Claude" / "claude-code").glob("*/claude.exe"))
        if not real_bundle:
            raise SystemExit("이 PC 에 Claude Desktop 에 딸린 Claude Code 가 없어 노트북 조건을 못 만든다")
        target = roaming / "Claude" / "claude-code" / real_bundle[-1].parent.name / "claude.exe"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(real_bundle[-1], target)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("JARVIS_")}
    if args.laptop_like:
        # ③ PATH 에서 npm 의 claude 를 뺀다 — 노트북에는 없다
        env["PATH"] = os.pathsep.join(part for part in env.get("PATH", "").split(os.pathsep)
                                      if "npm" not in part.lower())
    env.update({
        "USERPROFILE": str(home), "HOME": str(home), "LOCALAPPDATA": str(local), "APPDATA": str(roaming),
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=9333",
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0",
        "JARVIS_TTS_WARMUP_ENABLED": "0", "JARVIS_SCHEDULER_ENABLED": "0", "JARVIS_WATCHES_ENABLED": "0",
        "JARVIS_BROWSER_ENABLED": "0", "JARVIS_CAMERA_ENABLED": "0", "JARVIS_VISION_ENABLED": "0",
    })
    if args.ollama_url:
        env["JARVIS_OLLAMA_BASE_URL"] = args.ollama_url
    record: dict = {"round": args.round, "size": args.size or "app default",
                    "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "checks": {}, "facts": {}}

    def check(name: str, ok: bool, detail=None) -> None:
        record["checks"][name] = bool(ok)
        if detail is not None:
            record["facts"][name] = detail
        print(f"[{'OK ' if ok else 'BAD'}] {name} {json.dumps(detail, ensure_ascii=False)[:240] if detail is not None else ''}", flush=True)

    def fact(name: str, value) -> None:
        record["facts"][name] = value
        print(f"[..] {name} {json.dumps(value, ensure_ascii=False)[:240]}", flush=True)

    def launch():
        return subprocess.Popen([str(APP / "Sonjari.exe")], env=env, cwd=str(APP))

    started = time.time()
    launch()
    while time.time() - started < 120 and not health():
        time.sleep(1)
    fact("backend_up_sec", round(time.time() - started, 1) if health() else None)

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
                page.screenshot(path=str(shots / f"{name}.png"))
                bad = page.evaluate(VERTICAL_TEXT_JS)
                check(f"no_vertical_text_{name}", not bad, bad or None)

            setup = page_with("mode=setup")
            check("first_run_opens_wizard", bool(setup))
            if setup is None:
                raise SystemExit("wizard did not open")
            if size:
                size_app_window(APP, *size)
            setup.wait_for_timeout(1200)
            check("one_window_at_start", app_windows() == ["Sonjari 시작하기"], app_windows())

            # 사람처럼 한 번 더 켠다(설치 창 「실행」 + 시작 메뉴) — 창이 늘면 안 된다
            launch()
            time.sleep(6)
            check("one_window_after_second_launch", app_windows() == ["Sonjari 시작하기"], app_windows())

            # ① PC 확인 → 시작 한 번
            start = setup.get_by_role("button", name="이 PC 에 맞게 설정 시작")
            start.wait_for(timeout=90000)
            setup.wait_for_function("() => !document.querySelector('.setup-actions .setup-btn-go')?.disabled", timeout=90000)
            shot(setup, "1_pc_check")
            fact("pc_lead", setup.locator(".setup-lead").first.inner_text())
            clicked = time.time()
            start.click()

            # ①-2 모델 단계 — 추천이 골라져 있다. 받기는 사람이 누른다(2026-10-07: 묻지 않고 받지 않는다).
            setup.wait_for_function(
                "() => { const b = document.querySelector('.setup-actions .setup-btn-go');"
                " return !!b && !b.disabled && (b.innerText.includes('적용하기')); }", timeout=90000)
            check("nothing_downloads_before_the_click", setup.locator(".setup-dock").count() == 0)
            setup.locator(".setup-actions .setup-btn-go").first.click()

            # ② 모델 — 그 한 번 뒤로는 사람 손 없이 적용까지
            skip_seen = []
            while time.time() - clicked < args.apply_budget:
                if setup.locator(".setup-done").count() or setup.locator(".setup-human .setup-warn[role=alert]").count():
                    break
                labels = setup.locator(".setup-actions button").all_inner_texts()
                if any("받는 동안" in label or "나중에" in label for label in labels):
                    skip_seen.append(labels)
                time.sleep(1)
            done = setup.locator(".setup-done").count() > 0
            line = (setup.locator(".setup-done").first.inner_text() if done else
                    (setup.locator(".setup-human .setup-warn[role=alert]").first.inner_text()
                     if setup.locator(".setup-human .setup-warn[role=alert]").count() else "timeout"))
            check("autopilot_applied", done, {"sec": round(time.time() - clicked, 1), "line": line})
            check("no_skip_while_pulling", not skip_seen, skip_seen[:2] or None)
            shot(setup, "2_model_applied")
            picked = setup.locator(".model-card.is-picked h2").first
            applied_model = picked.inner_text() if picked.count() else ""
            fact("applied_model_card", applied_model)
            if not done:
                raise SystemExit("model was not applied — stopping here")

            # ③ 쓰임
            setup.get_by_role("button", name="쓰임 고르기").click()
            setup.wait_for_selector(".skill-domain", timeout=30000)
            shot(setup, "3_usage")
            setup.locator(".setup-actions .setup-btn-go").first.click()

            # ④ 연결 → 「Sonjari 시작하기」(09-29 이름 2단계 — 옛 「온텔릭 시작하기」를 찾다 30초에 멈췄다, 09-30)
            finish = setup.get_by_role("button", name=re.compile(r"(Sonjari|손자리|온텔릭) 시작하기"))
            finish.wait_for(timeout=30000)
            time.sleep(3)
            if args.laptop_like:
                # 자동 잇기가 끝날 때까지 — Claude Code 는 연결됨, Desktop 은 켜져 있으니 「닫으면 잇기」 대기
                deadline = time.time() + 120
                while time.time() < deadline:
                    rows = setup.locator(".imp-row").all_inner_texts()
                    code_row = next((r for r in rows if r.startswith("Claude Code")), "")
                    desk_row = next((r for r in rows if r.startswith("Claude Desktop")), "")
                    if "연결됨" in code_row and ("닫으면" in desk_row or "연결됨" in desk_row):
                        break
                    time.sleep(2)
                rows = setup.locator(".imp-row").all_inner_texts()
                code_row = next((r for r in rows if r.startswith("Claude Code")), "")
                desk_row = next((r for r in rows if r.startswith("Claude Desktop")), "")
                check("laptop_claude_code_connected_via_desktop_bundle", "연결됨" in code_row, code_row)
                check("laptop_desktop_waits_for_close", "닫으면" in desk_row or "연결됨" in desk_row, desk_row)
                claude_json = home / ".claude.json"
                check("laptop_claude_code_registered_on_disk",
                      claude_json.exists() and '"ontelic"' in claude_json.read_text(encoding="utf-8", errors="ignore"))
                note = home / ".claude" / "CLAUDE.md"
                check("laptop_global_note_points_to_guide", note.exists() and "sonjari-guide" in note.read_text(encoding="utf-8-sig", errors="ignore"))
                check("laptop_guide_skill_installed", (home / ".claude" / "skills" / "sonjari-guide" / "SKILL.md").exists())
                check("laptop_desktop_config_untouched_while_running",
                      "mcpServers" not in json.loads(desktop_config.read_text(encoding="utf-8")),
                      desktop_config.read_text(encoding="utf-8")[:200])
            shot(setup, "4_connect")
            check("finish_button_visible_without_scroll", finish.is_visible() and finish.bounding_box() is not None
                  and finish.bounding_box()["y"] + finish.bounding_box()["height"] <= setup.viewport_size["height"] + 1
                  if setup.viewport_size else finish.is_visible(),
                  finish.bounding_box())
            finish.click()

            work = page_with("mode=workspace", wait=60)
            time.sleep(4)
            windows = app_windows()
            check("finish_opens_product", bool(work) and windows == ["Sonjari"], windows)
            if work is None:
                raise SystemExit("product window did not open")
            if size:
                size_app_window(APP, *size)
            work.wait_for_selector("textarea", timeout=30000)
            time.sleep(4)
            chip = work.locator(".model-chip").first.inner_text() if work.locator(".model-chip").count() else ""
            roles = (health().get("ollama") or {}).get("roles") or {}
            fact("health_chat_model", roles.get("chat"))
            check("chip_shows_applied_model", bool(chip) and "확인 중" not in chip, chip)
            check("no_readiness_banner", work.locator(".readiness-banner").count() == 0,
                  work.locator(".readiness-banner").all_inner_texts() or None)
            shot(work, "5_product")

            box = work.locator("textarea").first
            box.fill("한 줄로만 자기소개해 줘.")
            box.press("Enter")
            asked = time.time()
            work.wait_for_selector(".message-assistant:not(.streaming-message)", timeout=600000)
            time.sleep(1)
            answer = work.locator(".message-assistant .message-body").last.inner_text()
            check("first_answer", bool(answer.strip()), {"sec": round(time.time() - asked, 1), "text": answer[:120]})
            shot(work, "6_first_answer")

            # ⑤ 설정 › 모델 — 목록·가능/불가·사용 중
            work.get_by_role("button", name="설정").first.click()
            work.wait_for_selector(".settings-screen", timeout=20000)
            work.locator(".settings-nav-item").filter(has_text="모델").first.click()
            work.wait_for_selector(".model-row", timeout=60000)
            time.sleep(1.5)
            rows = work.locator(".model-row").all_inner_texts()
            current = [row for row in rows if "사용 중" in row]
            check("settings_model_list_has_one_current", len(current) == 1, {"rows": len(rows), "current": current})
            check("settings_model_list_says_fit", any("가능" in row or "불가" in row for row in rows))
            shot(work, "7_settings_model")

            if args.switch_to:
                # ⑤-2 설정 › 모델에서 실제로 바꾸기 — 안 받은 모델이면 **실제로 받고**, 백엔드가 받은 뒤 적용까지 한다.
                row = work.locator(".model-row").filter(has_text=args.switch_to).first
                button = row.locator(".model-row-btn")
                label = button.inner_text()
                fact("switch_button", label)
                clicked = time.time()
                button.click()
                progress_seen = False
                while time.time() - clicked < args.apply_budget:
                    if row.locator(".model-row-progress").count():
                        if not progress_seen:
                            progress_seen = True
                            shot(work, "8_settings_model_pulling")
                    if "사용 중" in row.inner_text():
                        break
                    if row.locator(".model-row-error").count():
                        break
                    time.sleep(2)
                switched = "사용 중" in row.inner_text()
                # 설정 창을 닫기 **전에** 읽는다 — 닫은 뒤 읽어 값이 비었다(4판 첫 실행, 눈금 버그).
                row_text = row.inner_text()
                check("settings_switch_applied", switched,
                      {"sec": round(time.time() - clicked, 1), "button": label,
                       "error": row.locator(".model-row-error").all_inner_texts() or None})
                if "받고" in label:
                    check("settings_switch_showed_progress", progress_seen)
                work.keyboard.press("Escape")
                time.sleep(3)
                chip_after = work.locator(".model-chip").first.inner_text() if work.locator(".model-chip").count() else ""
                import re as _re
                ctx_in_list = _re.search(r"(\d+K) 까지", row_text)
                check("chip_context_matches_list", bool(ctx_in_list) and ctx_in_list.group(1) in chip_after,
                      {"list": ctx_in_list.group(1) if ctx_in_list else None, "chip": chip_after})
                # 태그 그대로(소문자로 시작, 예: 「granite4.1」)면 읽히지 않는 이름이다. 「Qwen3.5」의 n3.5 를 잡던 눈금 버그를 고쳤다.
                check("chip_name_is_readable", not _re.match(r"[a-z]", chip_after.strip()),
                      chip_after)
                check("chip_follows_switch", chip_after != chip and "확인 중" not in chip_after,
                      {"before": chip, "after": chip_after, "health": ((health().get("ollama") or {}).get("roles") or {}).get("chat")})
                shot(work, "9_product_after_switch")

        # ⑥ 다시 켜기 — 마법사 없이 제품 화면만
        kill_app()
        launch()
        time.sleep(25)
        check("relaunch_skips_wizard", app_windows() == ["Sonjari"], app_windows())
    finally:
        kill_app()
        record["passed"] = all(record["checks"].values())
        record["failed"] = [name for name, ok in record["checks"].items() if not ok]
        (shots / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print("PASSED" if record["passed"] else f"FAILED: {record['failed']}", "->", shots)


if __name__ == "__main__":
    main()
