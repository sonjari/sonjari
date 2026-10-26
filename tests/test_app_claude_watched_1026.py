"""앱 안 Claude Agent 가 맡긴 판은 「사람이 보는 판」이다 — 결 · 이야기판을 기다린다 (2026-10-26 첫 실제 판).

바깥 클로드 앱이 맡긴 판(origin=mcp)은 지금처럼 기다리지 않는다.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from alture_jarvis import claude_agent
from alture_jarvis.local_computer import LocalComputerTools


def _watched(payload: dict) -> bool:
    fake = SimpleNamespace(job_info=lambda job_id: {"payload": payload})
    return LocalComputerTools._deck_watched(fake, "j1")  # type: ignore[arg-type]


def test_app_claude_connection_marks_itself(tmp_path: Path) -> None:
    config = SimpleNamespace(data_dir=tmp_path, host="127.0.0.1", port=8091)
    claude_agent.prepare(config, lang="ko")
    entry = json.loads((tmp_path / "claude_agent" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["sonjari"]
    assert entry["env"]["JARVIS_MCP_VIA"] == "app"


def test_app_claude_job_is_watched_outside_claude_is_not() -> None:
    assert _watched({"origin": "workspace"}) is True
    assert _watched({"origin": "mcp", "via": "app"}) is True
    assert _watched({"origin": "mcp"}) is False
    assert _watched({"origin": "mcp", "via": "remote"}) is False
