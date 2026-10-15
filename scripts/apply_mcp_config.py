"""클로드 데스크톱 설정에 alture-jarvis MCP 서버를 넣는다 (기존 키는 보존).

★ 앱이 켜진 채로 고치면 종료할 때 덮어쓴다(2026-08-08 에 그렇게 날아갔다).
   **앱을 완전히 종료한 뒤** 이 스크립트를 돌리고 그다음에 앱을 켜라.

    python scripts/apply_mcp_config.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUNTIME = Path(r"C:\RoboMetaFit\tools\alture-jarvis")
CONFIG = Path(os.path.expandvars(r"%APPDATA%\Claude\claude_desktop_config.json"))


def token() -> str:
    env = RUNTIME / ".env"
    for line in env.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if line.startswith("JARVIS_CONTROL_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("JARVIS_CONTROL_TOKEN 이 .env 에 없다. scripts/setup_mcp.py 를 먼저 돌려라.")


entry = {
    "command": str(RUNTIME / ".venv" / "Scripts" / "python.exe"),
    "args": ["-m", "alture_jarvis.mcp_server"],
    "env": {
        "PYTHONPATH": str(RUNTIME / "src"),
        "PYTHONIOENCODING": "utf-8",
        "JARVIS_CONTROL_TOKEN": token(),
        "JARVIS_BASE_URL": "http://127.0.0.1:8091",
        "JARVIS_MCP_MAX_RISK": "L1",
    },
}

data = {}
if CONFIG.exists():
    shutil.copy2(CONFIG, CONFIG.with_suffix(".json.bak"))
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    print(f"백업: {CONFIG.with_suffix('.json.bak')}")

data.setdefault("mcpServers", {})["alture-jarvis"] = entry
CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

back = json.loads(CONFIG.read_text(encoding="utf-8"))
print("최상위 키 보존:", list(back.keys()))
print("mcpServers  :", list(back["mcpServers"].keys()))
print("토큰 길이   :", len(back["mcpServers"]["alture-jarvis"]["env"]["JARVIS_CONTROL_TOKEN"]), "자")
print("\n완료. 클로드 데스크톱을 켜라(이미 켜져 있었다면 완전 종료 후 이 스크립트를 다시 돌려라).")
