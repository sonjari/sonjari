"""W3·W4 라이브 — 설정 화면 값이 **다시 띄운 백엔드에서도 이기는지** 진짜 프로세스로 잰다.

    python scripts/e2e_settings_roundtrip.py --root C:\\RoboMetaFit\\tools\\e2e_w3

격리: 빈 런타임 루트 · 포트 8093 · 가짜 홈. 운영(8091)은 안 건드린다. 모델은 안 부른다.
`task_entry` 처럼 환경변수를 먼저 넣고(`JARVIS_TAKEOVER_ENABLED=true` 등), `.env` 에도 반대 값을 적어 둔다 —
세 자리가 다 반대를 말하는 상태에서 화면 값이 이겨야 한다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8093"


def call(method: str, path: str, token: str = "", body: dict | None = None) -> Any:
    request = urllib.request.Request(f"{BASE}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("X-JARVIS-TOKEN", token)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.code, "body": exc.read().decode("utf-8", "replace")[:300]}


def start(root: Path, home: Path) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env.update({
        "JARVIS_RUNTIME_ROOT": str(root / "runtime"), "JARVIS_PORT": "8093", "USERPROFILE": str(home), "HOME": str(home),
        "PYTHONPATH": str(REPO / "src"), "PYTHONIOENCODING": "utf-8",
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0", "JARVIS_VISION_ENABLED": "0",
        "JARVIS_SCHEDULER_ENABLED": "0", "JARVIS_WATCHES_ENABLED": "0", "JARVIS_STARTUP_WARMUP_ENABLED": "0",
        "JARVIS_TTS_WARMUP_ENABLED": "0", "JARVIS_BROWSER_ENABLED": "0",
        # task_entry 가 setdefault 로 넣는 모양 — 화면 값과 반대
        "JARVIS_TAKEOVER_ENABLED": "true", "JARVIS_OLLAMA_MAX_TOOL_STEPS": "30",
    })
    log = (root / "backend.log").open("ab")
    return subprocess.Popen([str(REPO / ".venv" / "Scripts" / "python.exe"), "-m", "alture_jarvis"], cwd=str(root),
                            env=env, stdout=log, stderr=subprocess.STDOUT)


def wait_up(timeout: float = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            call("GET", "/health")
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("backend did not start")


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    root = Path(args.root)
    home = root / "home"
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    (root / "runtime" / ".env").write_text("JARVIS_USER_LABEL=닷엔브값\nJARVIS_SKILLS_ROUTE_ENABLED=false\n", encoding="utf-8")
    out: dict[str, Any] = {}

    proc = start(root, home)
    try:
        wait_up()
        token = (root / "runtime" / "data" / "control.token").read_text(encoding="utf-8").strip()
        rows = {r["key"]: r for r in call("GET", "/v1/settings", token)["settings"]}
        out["before"] = {k: rows[k]["value"] for k in ("takeover_enabled", "user_label", "ollama_max_tool_steps", "voice_enabled")}
        out["rejects_secret"] = call("PATCH", "/v1/settings", token, {"values": {"control_token": "x"}})
        out["rejects_range"] = call("PATCH", "/v1/settings", token, {"values": {"approval_ttl_sec": 1}})
        patched = call("PATCH", "/v1/settings", token, {"values": {
            "takeover_enabled": False, "user_label": "화면값", "ollama_max_tool_steps": 9, "voice_enabled": True}})
        out["patch"] = {"ok": patched.get("ok"), "applied": patched.get("applied"), "restart_required": patched.get("restart_required")}
        domains = call("POST", "/v1/skills/domains", token, {"domains": ["career", "office"]})
        out["domains"] = {"selected": domains.get("selected"), "route_enabled": domains.get("route_enabled"),
                          "active_count": domains.get("active_count")}
        made = call("POST", "/v1/diagnostics/export", token, {})
        text = Path(made["path"]).read_text(encoding="utf-8") if made.get("ok") else ""
        out["diagnostics"] = {"ok": made.get("ok"), "bytes": made.get("bytes"), "has_token": token in text,
                              "has_home_path": str(home) in text}
    finally:
        stop(proc)

    proc = start(root, home)
    try:
        wait_up()
        token = (root / "runtime" / "data" / "control.token").read_text(encoding="utf-8").strip()
        rows = {r["key"]: r for r in call("GET", "/v1/settings", token)["settings"]}
        out["after_restart"] = {k: (rows[k]["value"], rows[k]["source"], rows[k]["restart_required"])
                                for k in ("takeover_enabled", "user_label", "ollama_max_tool_steps", "skills_route_enabled", "skills_domains")}
        public = call("GET", "/v1/config")
        out["public_config_user_label"] = public.get("user_label")
    finally:
        stop(proc)
    text = json.dumps(out, ensure_ascii=False, indent=2)
    (root / "result.json").write_text(text, encoding="utf-8")
    sys.stdout.buffer.write(text.encode("utf-8") + b"\n")


if __name__ == "__main__":
    main()
