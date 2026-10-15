"""대형 AI 가 사용량 한도로 멈췄을 때 — 온텔릭이 **실제 창에서** 어떻게 보이고, 이어받아 잘 해내는가 (2026-09-16).

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/e2e_takeover_ui.py [--direction continue] [--round 1]

진짜 한도는 일부러 걸 수 없다. 그래서 **실제 Claude Code 한도 기록과 같은 모양**(isApiErrorMessage · rate_limit · 429 ·
「You've hit your limit」)의 합성 대화 기록을 **가짜 홈**에 쓴다. 사용자의 실제 `~/.claude` 는 건드리지 않는다.

격리는 F3(`e2e_product_flow.py`)와 같다 — 포장본 exe · 가짜 홈/LOCALAPPDATA/APPDATA · `JARVIS_*` 제거 · WebView2 CDP 9333.
첫 실행은 이미 끝낸 PC 로 둔다(`setup_state.json`) — 여기서 보려는 것은 마법사가 아니라 이어받기다.
모델은 운영과 **같은 태그·같은 컨텍스트**로 준다(다르면 러너가 서로 축출한다 — 이 저장소 단골 고장).

화면마다 찍는다: 빈 작업 화면 → 「멈췄어」 한 줄 → 캡슐(찾았다·맥락·방향) → 이어서 일하는 중 → 결과.
채점: 파일을 만들었나 · 그 파일 형식 · 도구가 준 적 없는 숫자(`delegation.summarize_job` 과 같은 대조) · 시간.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from alture_jarvis.delegation import summarize_job  # noqa: E402
from app_window import size_app_window  # noqa: E402

APP = Path(r"C:\RoboMetaFit\tools\JarvisAppStage\app")
SANDBOX = Path(r"C:\RoboMetaFit\tools\e2e_takeover")
BASE = "http://127.0.0.1:8094"
CDP = "http://127.0.0.1:9333"
OPERATING = "http://127.0.0.1:8091"


def _get(url: str, token: str = "", timeout: float = 10) -> dict:
    request = urllib.request.Request(url)
    if token:
        request.add_header("X-JARVIS-TOKEN", token)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def health() -> dict:
    try:
        return _get(f"{BASE}/health", timeout=5)
    except Exception:
        return {}


def kill_app() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -like '{APP}\\*' }} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True, timeout=60)


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(epoch))


def write_limit_log(home: Path) -> tuple[Path, Path]:
    """조사 → 비교표 엑셀 과제를 하던 Claude Code 가 공고 2개를 찾아 메모한 뒤 한도로 멈춘 기록."""
    work = home / "Documents" / "yeosu_jobs"
    work.mkdir(parents=True, exist_ok=True)
    (work / "notes.md").write_text(
        "# 여수 회계 채용 조사 메모\n\n- 사람인에서 「여수 회계」로 찾기 시작함\n- 공고 2개 확인, 1개 더 찾아야 함\n"
        "- 끝나면 회사·마감일·자격 요건 비교표를 엑셀로\n", encoding="utf-8")
    at = time.time() - 180
    cwd = str(work)
    base = {"sessionId": "e2e-limit", "cwd": cwd}
    ask = "사람인에서 여수 회계 채용 공고 3개를 찾아서 회사·마감일·자격 요건 비교표를 엑셀로 만들어줘"
    rows = [
        {**base, "type": "custom-title", "customTitle": "여수 회계 채용 비교표"},
        {**base, "type": "user", "timestamp": _iso(at - 900), "message": {"role": "user", "content": ask}},
        {**base, "type": "assistant", "timestamp": _iso(at - 840), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "TaskCreate", "input": {"subject": "사람인에서 여수 회계 공고 3개 찾기", "description": "", "activeForm": ""}},
            {"type": "tool_use", "name": "TaskCreate", "input": {"subject": "회사·마감일·자격 요건 비교표 엑셀", "description": "", "activeForm": ""}},
            {"type": "tool_use", "name": "WebSearch", "input": {"query": "사람인 여수 회계 채용"}},
        ]}},
        {**base, "type": "assistant", "timestamp": _iso(at - 600), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": f"{cwd}/notes.md", "content": "메모"}},
            {"type": "text", "text": "공고 2개를 확인했습니다. 하나 더 찾은 뒤 비교표 엑셀을 만들겠습니다."}]}},
        {**base, "type": "assistant", "timestamp": _iso(at), "isApiErrorMessage": True, "error": "rate_limit",
         "apiErrorStatus": 429, "message": {"role": "assistant", "content": [
             {"type": "text", "text": "You've hit your limit · resets 6am"}]}},
    ]
    path = home / ".claude" / "projects" / "e2e-limit" / "hit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8") + b"\n")
    return path, work


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--direction", default="continue", choices=["continue", "review", "tasks"])
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--budget", type=float, default=900)
    args = ap.parse_args()
    shots = ROOT / "docs" / "walkthrough" / "ontelic_takeover_2026-09-16" / f"{args.direction}_r{args.round}"
    shots.mkdir(parents=True, exist_ok=True)

    live = _get(f"{OPERATING}/health")
    chat_model = str(((live.get("ollama") or {}).get("roles") or {}).get("chat") or "")
    num_ctx = str((live.get("context") or {}).get("num_ctx") or "")

    kill_app()
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    home = SANDBOX / "home"
    local, roaming = home / "AppData" / "Local", home / "AppData" / "Roaming"
    for folder in (local, roaming, home / "Documents"):
        folder.mkdir(parents=True, exist_ok=True)
    data = local / "Sonjari" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "setup_state.json").write_text(json.dumps(
        {"completed": True, "steps": ["pc", "model", "domains", "connect"], "completed_at": time.time()}), encoding="utf-8")
    log_path, work = write_limit_log(home)

    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("JARVIS_")}
    env.update({
        "USERPROFILE": str(home), "HOME": str(home), "LOCALAPPDATA": str(local), "APPDATA": str(roaming),
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=9333",
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0",
        "JARVIS_TTS_WARMUP_ENABLED": "0", "JARVIS_SCHEDULER_ENABLED": "0", "JARVIS_WATCHES_ENABLED": "0",
        "JARVIS_CAMERA_ENABLED": "0", "JARVIS_VISION_ENABLED": "0",
        # 이어받기 뒤 조사는 브라우저가 필요하다. 운영 크롬(9222)과 겹치지 않게 다른 포트·가짜 홈 프로필.
        "JARVIS_BROWSER_CDP_PORT": "9244",
        "JARVIS_OLLAMA_CHAT_MODEL": chat_model, "JARVIS_OLLAMA_VISION_MODEL": chat_model,
        "JARVIS_OLLAMA_NUM_CTX": num_ctx,
    })
    record: dict = {"direction": args.direction, "round": args.round, "model": chat_model, "num_ctx": num_ctx,
                    "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "limit_log": str(log_path)}

    def step(name: str, value) -> None:
        record[name] = value
        print(f"[{name}] {json.dumps(value, ensure_ascii=False)[:300]}", flush=True)

    launched = time.time()
    subprocess.Popen([str(APP / "Sonjari.exe")], env=env, cwd=str(APP))
    while time.time() - launched < 120 and not health():
        time.sleep(1)
    step("1_backend_up_sec", round(time.time() - launched, 1) if health() else None)
    token = (data / "control.token").read_text(encoding="utf-8-sig").strip() if (data / "control.token").exists() else ""

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
            page = None
            for _ in range(60):
                for context in browser.contexts:
                    for candidate in context.pages:
                        if "mode=workspace" in candidate.url:
                            page = candidate
                if page:
                    break
                time.sleep(1)
                browser = pw.chromium.connect_over_cdp(CDP)
            step("2_workspace_opened", bool(page))
            if page is None:
                raise SystemExit("workspace did not open")
            # 뷰포트를 속이지 않고 **창**을 1440×900 으로 둔다(`app_window` 주석 — 강제 뷰포트는
            # 사람이 창을 최대화하면 검은 여백을 남겼다).
            size_app_window(APP, 1440, 900)
            page.wait_for_timeout(800)
            composer = page.get_by_placeholder("온텔릭에게 메시지를 보내거나 파일을 맡겨보세요")
            composer.wait_for(timeout=60000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(shots / "1_workspace.png"))

            # ③ 사람이 하는 말 그대로 — 「멈췄어」
            composer.fill("클로드 코드가 사용량 한도에 걸려서 멈췄어. 하던 거 이어서 해줄 수 있어?")
            composer.press("Enter")
            said = time.time()
            relay = page.locator(".takeover-relay")
            try:
                relay.wait_for(timeout=180000)
                step("3_capsule_sec", round(time.time() - said, 1))
                page.wait_for_timeout(300)
                page.screenshot(path=str(shots / "2_capsule_detected.png"))
                # ★ 2026-09-16: 「읽어 온 맥락」은 `indexing` **단계에서만** 그려진다. 이 눈금을
                #   단계가 지나간 뒤(고르기 화면)에 읽고 있었고, 그래서 r3·r4 두 판 모두 `""` 였다.
                #   빈 눈금은 「맥락이 없었다」가 아니라 「우리가 못 봤다」였다 — 지나가기 전에 찍는다.
                milestones = page.locator(".takeover-milestones")
                milestones.wait_for(timeout=8000)
                step("4_capsule_facts", milestones.inner_text())
                page.screenshot(path=str(shots / "3_capsule_context.png"))
            except Exception as exc:  # noqa: BLE001 — 캡슐이 안 뜨면 그 화면을 남긴다
                page.screenshot(path=str(shots / "2_no_capsule.png"))
                step("3_capsule_sec", None)
                step("3_capsule_error", f"{type(exc).__name__}: {str(exc)[:200]}")
                raise SystemExit("capsule did not appear")
            form = page.locator("form.takeover-relay-body")
            form.wait_for(timeout=10000)
            labels = {"continue": "멈춘 자리부터 이어가기", "review": "먼저 지금까지 한 일 검토하기", "tasks": "남은 일만 정리하기"}
            page.get_by_text(labels[args.direction]).click()
            page.screenshot(path=str(shots / "4_capsule_choose.png"))
            page.locator("button.takeover-primary").click()
            chose = time.time()

            # ④ 일하는 중
            job_id = ""
            for _ in range(60):
                jobs = _get(f"{BASE}/v1/jobs?limit=5&view=summary")
                running = [j for j in jobs if j.get("status") in ("queued", "running") and float(j.get("created_at") or 0) >= chose - 5]
                if running:
                    job_id = str(running[0]["id"])
                    break
                time.sleep(1)
            step("5_job_started", job_id[:8])
            page.wait_for_timeout(25000)
            page.screenshot(path=str(shots / "5_working.png"))

            final: dict = {}
            while job_id and time.time() - chose < args.budget:
                final = _get(f"{BASE}/v1/jobs/{job_id}")
                if final.get("status") in ("completed", "failed", "cancelled", "waiting_approval", "waiting_continuation"):
                    break
                time.sleep(3)
            step("6_elapsed_sec", round(time.time() - chose, 1))
            page.wait_for_timeout(2500)
            page.screenshot(path=str(shots / "6_result.png"))

            summary = summarize_job(final) if final else {}
            made = sorted(str(p.relative_to(home)) for p in home.rglob("*")
                          if p.is_file() and p.stat().st_mtime >= chose and ".claude" not in p.parts
                          and "AppData" not in p.parts)
            step("7_status", final.get("status"))
            step("7_summary", {k: summary.get(k) for k in ("status", "steps", "files", "unsupported_numbers", "completion_state")})
            step("7_new_user_files", made)
            step("7_xlsx", any(name.lower().endswith(".xlsx") for name in made))
            step("7_answer_head", str((final.get("result") or {}).get("answer") or "")[:500])
    finally:
        kill_app()
        (shots / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
