"""스토어용 이어받기 장면을 **지금 빌드**로 찍는다 (2026-10-05).

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/capture_takeover_shots.py --lang en --name takeover_en

`e2e_takeover_ui.py`(09-16) 와 같은 원리 — 진짜 한도는 일부러 걸 수 없으니 **실제 Claude Code 한도 기록과 같은 모양**의
대화 기록을 가짜 홈에 쓴다. 그 뒤 화면에서 벌어지는 일(찾기 → 맥락 읽기 → 방향 고르기 → 이어서 일하기)은 전부 실제다.
다른 점: 가짜 홈은 `capture_store_shots.py` 와 같은 것(마법사를 끝낸 새 프로필)을 쓰고, 화면 언어를 고르고, 스토어 크기로 찍는다.

찍는 것: 10_said(멈췄다고 말함) · 20_found(찾았다) · 30_context(읽어 온 맥락) · 40_choose(어떻게 이어갈지) · 50_working · 60_result.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_window import size_app_window  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = Path(r"C:\RoboMetaFit\tools\JarvisAppStage\app")
SANDBOX = Path(r"C:\RoboMetaFit\tools\e2e_oneshot")
BASE = "http://127.0.0.1:8094"
CDP = "http://127.0.0.1:9333"

SCENES = {
    "ko": {
        "folder": "python_books",
        "title": "파이썬 책 비교표",
        "notes": "# 파이썬 책 조사 메모\n\n- 교보문고에서 「파이썬」으로 찾기 시작함\n- 책 2권 확인, 1권 더 찾아야 함\n"
                 "- 끝나면 제목·판매가·적립 포인트 비교표를 엑셀로\n",
        "ask": "교보문고에서 파이썬 책 3권을 찾아서 제목·판매가·적립 포인트 비교표를 엑셀로 만들어줘",
        "tasks": ["교보문고에서 파이썬 책 3권 찾기", "제목·판매가·적립 포인트 비교표 엑셀"],
        "query": "교보문고 파이썬 책",
        "progress": "책 2권을 확인했습니다. 하나 더 찾은 뒤 비교표 엑셀을 만들겠습니다.",
        "say": "클로드 코드가 사용량 한도에 걸려서 멈췄어. 하던 거 이어서 해줄 수 있어?",
    },
    "en": {
        "folder": "trending_table",
        "title": "GitHub trending table",
        "notes": "# GitHub trending notes\n\n- Started from github.com/trending/python\n- Read 2 repositories, 1 more to go\n"
                 "- Then save a table of name, stars and description as an Excel file\n",
        "ask": "Open github.com/trending/python, read the top 3 repositories, and save a table of name, stars and "
               "description as an Excel file",
        "tasks": ["Read the top 3 repositories on github.com/trending/python", "Save name, stars and description as an Excel table"],
        "query": "github trending python",
        "progress": "I have read two repositories. I will read one more and then build the Excel table.",
        "say": "Claude Code hit its usage limit and stopped. Can you pick up where it left off?",
    },
}


def call(path: str, body: dict | None = None, token: str = "", timeout: float = 20) -> object:
    req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-Jarvis-Token": token},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def health() -> dict:
    try:
        return call("/health", timeout=5)  # type: ignore[return-value]
    except Exception:
        return {}


def kill_app() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -like '{APP}\\*' -or "
                    f"($_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*{SANDBOX}*') }} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True, timeout=60)
    time.sleep(1.5)


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(epoch))


def write_limit_log(home: Path, scene: dict) -> Path:
    """조사 → 표 과제를 하던 Claude Code 가 둘을 읽고 메모한 뒤 한도로 멈춘 기록. 앞 촬영이 남긴 기록은 지운다(하나만 보이게)."""
    projects = home / ".claude" / "projects"
    if projects.exists():
        shutil.rmtree(projects, ignore_errors=True)
    work = home / "Documents" / scene["folder"]
    work.mkdir(parents=True, exist_ok=True)
    (work / "notes.md").write_text(scene["notes"], encoding="utf-8")
    at = time.time() - 180
    cwd = str(work)
    base = {"sessionId": "store-shot-limit", "cwd": cwd}
    rows = [
        {**base, "type": "custom-title", "customTitle": scene["title"]},
        {**base, "type": "user", "timestamp": _iso(at - 900), "message": {"role": "user", "content": scene["ask"]}},
        {**base, "type": "assistant", "timestamp": _iso(at - 840), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "TaskCreate", "input": {"subject": scene["tasks"][0], "description": "", "activeForm": ""}},
            {"type": "tool_use", "name": "TaskCreate", "input": {"subject": scene["tasks"][1], "description": "", "activeForm": ""}},
            {"type": "tool_use", "name": "WebSearch", "input": {"query": scene["query"]}},
        ]}},
        {**base, "type": "assistant", "timestamp": _iso(at - 600), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": f"{cwd}/notes.md", "content": "notes"}},
            {"type": "text", "text": scene["progress"]}]}},
        {**base, "type": "assistant", "timestamp": _iso(at), "isApiErrorMessage": True, "error": "rate_limit",
         "apiErrorStatus": 429, "message": {"role": "assistant", "content": [
             {"type": "text", "text": "You've hit your limit · resets 6am"}]}},
    ]
    path = projects / "store-shot-limit" / "hit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8") + b"\n")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--lang", default="ko", choices=("ko", "en"))
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--budget", type=float, default=600)
    ap.add_argument("--stop-at-choose", action="store_true", help="방향 고르기 화면까지만 찍고 끝낸다")
    ap.add_argument("--collapse-sidebar", action="store_true", help="옆 대화 목록을 접고 찍는다(가짜 홈의 시험 대화가 사진에 안 보이게)")
    args = ap.parse_args()
    scene = SCENES[args.lang]

    home = SANDBOX / "home"
    if not (home / "AppData" / "Local").exists():
        raise SystemExit("가짜 홈이 없다 — 먼저 capture_first_run_shots.py 를 돌릴 것")
    out = ROOT / "docs" / "store" / "raw" / args.name
    out.mkdir(parents=True, exist_ok=True)
    record: dict = {"lang": args.lang, "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    def step(name: str, value) -> None:
        record[name] = value
        print(f"[{name}] {json.dumps(value, ensure_ascii=False)[:300]}", flush=True)

    # 기록은 앱이 뜨기 **전에** 쓴다 — 뜬 뒤에 쓰면 앱이 이미 훑은 목록에 없을 수 있다.
    kill_app()
    record["limit_log"] = str(write_limit_log(home, scene))
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("JARVIS_")}
    env.update({
        "USERPROFILE": str(home), "HOME": str(home), "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=9333",
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0",
        "JARVIS_TTS_WARMUP_ENABLED": "0", "JARVIS_SCHEDULER_ENABLED": "0", "JARVIS_WATCHES_ENABLED": "0",
        "JARVIS_CAMERA_ENABLED": "0", "JARVIS_VISION_ENABLED": "0", "JARVIS_BROWSER_CDP_PORT": "9444",
    })
    subprocess.Popen([str(APP / "Sonjari.exe")], env=env, cwd=str(APP))
    started = time.time()
    while time.time() - started < 120 and not health():
        time.sleep(1)
    if not health():
        raise SystemExit("backend did not come up")
    step("model", ((health().get("ollama") or {}).get("roles") or {}).get("chat"))
    tokens = sorted(home.glob("AppData/Local/*/data/control.token"))
    token = tokens[-1].read_text(encoding="utf-8").strip() if tokens else ""
    for job in call("/v1/jobs?limit=20", token=token) or []:  # type: ignore[union-attr]
        if str(job.get("status")) in {"queued", "running", "waiting_approval", "waiting_continuation"}:
            call(f"/v1/jobs/{job['id']}/cancel", {}, token=token)
    width, height = (int(v) for v in args.size.split("x"))

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
            page.evaluate("(v) => window.localStorage.setItem('sonjari.ui_language', v)", args.lang)
            page.reload()
            page.wait_for_timeout(3000)
            page.get_by_role("tab", name="Cowork").first.click()
            page.wait_for_timeout(800)
            page.get_by_role("button", name="New conversation" if args.lang == "en" else "새 대화").first.click()
            page.wait_for_timeout(800)
            if args.collapse_sidebar:
                page.locator("aside.workspace-sidebar:not(.sidebar-collapsed) button:has(svg.lucide-chevron-left)").first.click()
                page.wait_for_timeout(600)
            box = page.locator("textarea:not(#code-preview-note)").last
            box.click()
            box.fill(scene["say"])
            page.wait_for_timeout(500)
            page.screenshot(path=str(out / "10_said.png"))
            box.press("Enter")
            said = time.time()
            relay = page.locator(".takeover-relay")
            try:
                relay.wait_for(timeout=180000)
            except Exception as exc:  # noqa: BLE001 — 안 뜨면 그 화면을 남긴다
                page.screenshot(path=str(out / "20_no_capsule.png"))
                step("capsule_error", f"{type(exc).__name__}: {str(exc)[:200]}")
                return 1
            step("capsule_sec", round(time.time() - said, 1))
            page.wait_for_timeout(300)
            page.screenshot(path=str(out / "20_found.png"))
            try:
                milestones = page.locator(".takeover-milestones")
                milestones.wait_for(timeout=8000)
                step("capsule_facts", milestones.inner_text())
                page.screenshot(path=str(out / "30_context.png"))
            except Exception:  # noqa: BLE001 — 이 단계는 빨리 지나갈 수 있다
                step("capsule_facts", None)
            form = page.locator("form.takeover-relay-body")
            form.wait_for(timeout=20000)
            page.wait_for_timeout(900)
            step("choose_text", form.inner_text()[:400])
            page.screenshot(path=str(out / "40_choose.png"))
            if args.stop_at_choose:
                return 0
            page.locator("button.takeover-primary").click()
            chose = time.time()
            job_id = ""
            for _ in range(60):
                jobs = call("/v1/jobs?limit=5&view=summary", token=token) or []
                running = [j for j in jobs if j.get("status") in ("queued", "running")  # type: ignore[union-attr]
                           and float(j.get("created_at") or 0) >= chose - 5]
                if running:
                    job_id = str(running[0]["id"])
                    break
                time.sleep(1)
            step("job", job_id[:8])
            final: dict = {}
            n = 0
            while job_id and time.time() - chose < args.budget:
                page.wait_for_timeout(12000)
                n += 1
                page.screenshot(path=str(out / f"50_working_{n:02d}.png"))
                final = call(f"/v1/jobs/{job_id}", token=token)  # type: ignore[assignment]
                if final.get("status") in ("completed", "failed", "cancelled", "waiting_approval", "waiting_continuation"):
                    break
            step("elapsed_sec", round(time.time() - chose, 1))
            page.wait_for_timeout(2500)
            page.screenshot(path=str(out / "60_result.png"))
            result = final.get("result") or {}
            step("status", final.get("status"))
            step("requested", (result.get("requested") or result.get("completion") or {}))
            step("answer_head", str(result.get("answer") or "")[:500])
            made = sorted(str(p.relative_to(home)) for p in home.rglob("*")
                          if p.is_file() and p.stat().st_mtime >= chose and ".claude" not in p.parts and "AppData" not in p.parts)
            step("new_files", made)
    finally:
        (out / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
