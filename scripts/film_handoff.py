"""README 영상 ② 「클로드 코드와 같이」 촬영 (2026-10-20).

화면 오른쪽 절반에 촬영용 손자리(가짜 홈 · 8094), 왼쪽 절반에 촬영 전용 클로드 코드 창을 놓고 주 모니터를 ffmpeg 로 녹화한다.
- 클로드 코드는 촬영 전용 설정 폴더(`CLAUDE_CONFIG_DIR`)로 띄운다 — 사람의 전역 지침 · 대화 기록이 안 실린다.
- 클로드에는 **촬영용 손자리만** 잇는다(`--mcp-config` + `--strict-mcp-config`) — 운영 손자리 · 사람의 크롬은 안 쓴다.
- 손자리 도구 셋만 미리 허락해 둔다(`--allowedTools`) — 촬영 중에 사람이나 내가 키를 칠 일이 없게.

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/film_handoff.py --out <mp4> --task "<클로드에게 줄 말>"
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import re
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
try:  # 화면 배율(125% 등)에서 창 좌표가 어긋나지 않게 — 실제 픽셀 좌표로 다룬다
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_window import size_app_window  # noqa: E402

APP = Path(r"C:\RoboMetaFit\tools\JarvisAppStage\app")
SANDBOX = Path(r"C:\RoboMetaFit\tools\e2e_oneshot")
BASE = "http://127.0.0.1:8094"
CDP = "http://127.0.0.1:9333"
FILM = Path(r"D:\bench_tmp\film_cc")
RUNTIME_SRC = Path(r"C:\RoboMetaFit\tools\alture-jarvis\src")
RUNTIME_PY = Path(r"C:\RoboMetaFit\tools\alture-jarvis\.venv\Scripts\python.exe")
FFMPEG = Path(os.environ["LOCALAPPDATA"]) / r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
HALF_W, HEIGHT = 960, 1032  # 주 모니터 1920x1080 · 작업 표시줄 위까지


def health() -> dict:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def sandbox_env() -> dict[str, str]:
    home = SANDBOX / "home"
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("JARVIS_")}
    env.update({
        "USERPROFILE": str(home), "HOME": str(home), "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": "--remote-debugging-port=9333",
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0",
        "JARVIS_TTS_WARMUP_ENABLED": "0", "JARVIS_SCHEDULER_ENABLED": "0", "JARVIS_WATCHES_ENABLED": "0",
        "JARVIS_CAMERA_ENABLED": "0", "JARVIS_VISION_ENABLED": "0", "JARVIS_BROWSER_CDP_PORT": "9444",
    })
    return env


def api(token: str, path: str) -> object:
    req = urllib.request.Request(f"{BASE}{path}", headers={"X-Jarvis-Token": token})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def visible_windows() -> set[int]:
    """보이는 최상위 창 전부(제목 있는 것). 띄우기 전 · 뒤를 견줘 새로 생긴 창을 찾는다 — conhost 는 창을 다른 프로세스가 쥔다."""
    user32 = ctypes.windll.user32
    found: set[int] = set()
    proto = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def visit(hwnd, _param):  # type: ignore[no-untyped-def]
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            found.add(int(hwnd))
        return True

    user32.EnumWindows(proto(visit), 0)
    return found


def pin(hwnd: int, x: int, y: int, w: int, h: int, top: bool = True) -> None:
    """창을 그 자리 · 크기로 두고 맨 위에 고정한다(뒤의 다른 창이 녹화에 안 들어가게). top=False 면 고정을 푼다."""
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetWindowPos(hwnd, 0, x, y, w, h, 0x0040 | 0x0004)  # SWP_SHOWWINDOW | SWP_NOZORDER  # HWND_TOPMOST/NOTOPMOST · SWP_SHOWWINDOW


def app_windows() -> list[int]:
    """촬영용 손자리 앱(APP 폴더의 exe)이 띄운 큰 창."""
    from app_window import _exe_of  # noqa: PLC0415
    user32 = ctypes.windll.user32
    out = []
    for hwnd in visible_windows():
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not _exe_of(int(pid.value)).lower().startswith(str(APP).lower()):
            continue
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right - rect.left >= 200 or user32.IsIconic(hwnd):
            out.append(hwnd)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--budget", type=float, default=900)
    args = ap.parse_args()

    # 1) 촬영용 손자리
    if not health():
        subprocess.Popen([str(APP / "Sonjari.exe")], env=sandbox_env(), cwd=str(APP))
        started = time.time()
        while time.time() - started < 120 and not health():
            time.sleep(1)
    if not health():
        raise SystemExit("sandbox backend did not come up")
    token_file = SANDBOX / "home" / "AppData" / "Local" / "Sonjari" / "data" / "control.token"
    token = token_file.read_text(encoding="utf-8").strip()
    # 앞 판(멈춘 촬영)이 남긴 일은 취소한다 — 새 판이 줄 뒤에서 기다리면 그 시간이 영상에 들어간다.
    for job in api(token, "/v1/jobs?limit=20") or []:
        if str(job.get("status")) in {"queued", "running", "waiting_approval", "waiting_continuation"}:
            req = urllib.request.Request(f"{BASE}/v1/jobs/{job['id']}/cancel", data=b"{}", method="POST",
                                         headers={"X-Jarvis-Token": token, "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=20).read()
            print(f"left-over job cancelled: {str(job['id'])[:8]}", flush=True)
    before = {str(j.get("id")) for j in api(token, "/v1/jobs?limit=50") or []}

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
        page = next((p for c in browser.contexts for p in c.pages if "mode=setup" not in p.url), None)
        if page is None:
            raise SystemExit("product window not found")
        size_app_window(APP, HALF_W, HEIGHT, x=HALF_W, y=0)
        page.wait_for_timeout(1000)
        page.get_by_role("tab", name="Cowork").first.click()
        page.get_by_role("button", name=re.compile(r"^(새 대화|New conversation)$")).first.click()  # 영어 화면도(README 영어 영상)
        page.wait_for_timeout(800)

        # 2) 촬영 전용 클로드 코드 — 촬영용 손자리에만 잇는다
        FILM.mkdir(parents=True, exist_ok=True)
        (FILM / "work").mkdir(exist_ok=True)
        mcp = {"mcpServers": {"sonjari": {
            "command": str(RUNTIME_PY), "args": ["-m", "alture_jarvis.mcp_server"],
            "env": {"PYTHONPATH": str(RUNTIME_SRC), "PYTHONIOENCODING": "utf-8", "JARVIS_BASE_URL": BASE,
                    "JARVIS_TOKEN_FILE": str(token_file), "JARVIS_MCP_MAX_RISK": "L1"}}}}
        (FILM / "mcp.json").write_text(json.dumps(mcp, ensure_ascii=False, indent=2), encoding="utf-8")
        task = args.task.replace('"', "'")
        (FILM / "run.cmd").write_text(
            "@echo off\r\nchcp 65001 >nul\r\ntitle Claude Code\r\n"
            f"set CLAUDE_CONFIG_DIR={FILM / 'config'}\r\ncd /d {FILM / 'work'}\r\ncls\r\n"
            f"claude --mcp-config \"{FILM / 'mcp.json'}\" --strict-mcp-config "
            "--allowedTools mcp__sonjari__sonjari_task mcp__sonjari__sonjari_task_status mcp__sonjari__sonjari_guide "
            f"-- \"{task}\"\r\n", encoding="utf-8")
        before_windows = visible_windows()
        console = subprocess.Popen(["conhost.exe", "cmd.exe", "/k", str(FILM / "run.cmd")])
        hwnd = 0
        for _ in range(75):
            fresh = [h for h in visible_windows() - before_windows if h not in app_windows()]
            if fresh:
                hwnd = fresh[0]
                break
            time.sleep(0.2)
        app_hwnds = app_windows()
        for app_hwnd in app_hwnds:
            pin(app_hwnd, HALF_W, 0, HALF_W, HEIGHT)
        if hwnd:
            time.sleep(1.0)
            pin(hwnd, 0, 0, HALF_W, HEIGHT)
        print(f"console hwnd={hwnd} app={app_hwnds}", flush=True)
        if not hwnd or not app_hwnds:
            raise SystemExit("could not place both windows — not recording (other windows would show)")

        # 3) 녹화 — 창 단위(Windows 창 캡처 · ffmpeg gfxcapture). 겹친 다른 창은 안 들어간다. 편집에서 나란히 붙인다.
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)

        def record(target: int, path: Path) -> subprocess.Popen:
            return subprocess.Popen([str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                     f"gfxcapture=hwnd={int(target)}:max_framerate=15:width=-2:height=-2,hwdownload,format=bgra",
                                     "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", str(path)],
                                    stdin=subprocess.PIPE)

        recs = [record(hwnd, out.with_name(out.stem + "_claude.mp4")),
                record(app_hwnds[0], out.with_name(out.stem + "_sonjari.mp4"))]
        started = time.time()
        done_at = 0.0
        while time.time() - started < args.budget:
            time.sleep(3)
            jobs = [j for j in api(token, "/v1/jobs?limit=20") or [] if str(j.get("id")) not in before]
            if jobs and all(str(j.get("status")) in {"completed", "failed", "cancelled"} for j in jobs):
                done_at = done_at or time.time()
                # 손자리 일이 끝난 뒤 클로드가 결과를 받아 답을 쓰는 시간까지 찍는다
                if time.time() - done_at > 75:
                    break
            print(f"{round(time.time() - started)}s jobs={[str(j.get('status')) for j in jobs]}", flush=True)
        for rec in recs:
            try:
                rec.stdin.write(b"q")
                rec.stdin.flush()
            except OSError:
                pass
        for rec in recs:
            rec.wait(timeout=60)
        for h in [hwnd, *app_hwnds]:
            pin(h, 0 if h == hwnd else HALF_W, 0, HALF_W, HEIGHT, top=False)
    print(f"saved -> {out}  ({round(time.time() - started)}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
