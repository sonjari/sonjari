"""MCP 서버 꽂기(mcp_hub · mcp_tools) — 진짜 stdio 서버로 붙어 양방향으로 본다 (2026-11-04 · 설계 §7)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from alture_jarvis.mcp_hub import McpHub, McpHubError, risk_from_annotations
from alture_jarvis.mcp_tools import McpTools
from alture_jarvis.messaging.credentials import MemoryCredentialStore
from alture_jarvis.models import RiskLevel

TOY = str(Path(__file__).parent / "fixtures" / "mcp_toy_server.py")


def _hub(tmp_path: Path, store: MemoryCredentialStore | None = None) -> McpHub:
    return McpHub(tmp_path, store=store or MemoryCredentialStore(), call_timeout=60, max_chars=2000)


def _toy(hub: McpHub, name: str = "toy", env: dict | None = None) -> None:
    hub.add_server(name, {"command": sys.executable, "args": [TOY], "env": env or {}})


# ── 등급 ──────────────────────────────────────────────────────────────

def test_only_an_explicit_read_only_hint_is_l0() -> None:
    assert risk_from_annotations({"read_only_hint": True}) == RiskLevel.L0
    assert risk_from_annotations({"readOnlyHint": True}) == RiskLevel.L0
    assert risk_from_annotations({}) == RiskLevel.L2                      # 표시 없음 → 사람 앞
    assert risk_from_annotations(None) == RiskLevel.L2
    assert risk_from_annotations({"read_only_hint": False}) == RiskLevel.L2
    assert risk_from_annotations({"read_only_hint": True, "destructive_hint": True}) == RiskLevel.L3


# ── 설정 · 비밀 ────────────────────────────────────────────────────────

def test_secret_values_go_to_the_vault_and_never_into_the_file(tmp_path: Path) -> None:
    store = MemoryCredentialStore()
    hub = _hub(tmp_path, store)
    hub.add_server("notion", {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer sk-SECRET-123"}})
    hub.add_server("files", {"command": "npx", "args": ["x"], "env": {"API_TOKEN": "tok-999", "MODE": "plain"}})
    raw = (tmp_path / "mcp_servers.json").read_text(encoding="utf-8")
    assert "sk-SECRET-123" not in raw and "tok-999" not in raw
    assert "plain" in raw                                                 # 비밀 아닌 값은 그대로
    assert "Bearer sk-SECRET-123" in store.items.values() and "tok-999" in store.items.values()
    assert hub.remove_server("notion") and not any("notion" in k for k in store.items)   # 지우면 보관함도


def test_names_are_narrow_and_sonjari_cannot_plug_itself(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    for bad in ("", "Bad Name", "a/b", "sonjari", "jarvis"):
        with pytest.raises(McpHubError):
            hub.add_server(bad, {"command": "x"})
    with pytest.raises(McpHubError):
        hub.add_server("plain", {"url": "http://evil.example.com/mcp"})    # 원격은 https 만
    hub.add_server("dup", {"command": "x"})
    with pytest.raises(McpHubError):
        hub.add_server("dup", {"command": "y"})


def test_import_from_claude_desktop_skips_sonjari_and_existing(tmp_path: Path) -> None:
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "sonjari": {"command": "python", "args": ["-m", "alture_jarvis.mcp_server"]},
        "also-me": {"command": "C:/x/python.exe", "args": ["-m", "alture_jarvis.mcp_server"]},
        "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                   "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_abc"}},
        "broken": {"args": []},
    }}), encoding="utf-8")
    hub = _hub(tmp_path / "data")
    r = hub.import_claude_desktop([cfg])
    assert r["added"] == ["github"]
    assert {s["name"] for s in r["skipped"]} == {"sonjari", "also-me", "broken"}
    assert "ghp_abc" not in (tmp_path / "data" / "mcp_servers.json").read_text(encoding="utf-8")


def test_import_reads_claude_code_user_config_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """11-04 운영 첫 시험: 대표 PC 의 서버는 데스크톱 설정이 아니라 `~/.claude.json` 맨 위 `mcpServers` 에 있었다."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(json.dumps({
        "projects": {"E:/x": {"mcpServers": {"proj-only": {"command": "x"}}}},
        "mcpServers": {
            "sonjari": {"type": "stdio", "command": "python", "args": ["-m", "alture_jarvis.mcp_server"]},
            "3dsmax-mcp": {"type": "stdio", "command": "uvx", "args": ["3dsmax-mcp"]},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("APPDATA", str(tmp_path / "nowhere"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nowhere"))
    paths = McpHub.claude_desktop_paths()
    assert paths[0] == home / ".claude.json"
    r = _hub(tmp_path / "data").import_claude_desktop()
    assert r["added"] == ["3dsmax-mcp"]  # 프로젝트에만 있는 것은 안 가져온다 · 손자리 자신은 빠진다
    assert [s["name"] for s in r["skipped"]] == ["sonjari"]


# ── 진짜 연결 ──────────────────────────────────────────────────────────

def test_real_stdio_server_lists_finds_and_calls_with_secret_passed(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    _toy(hub, env={"TOY_SECRET": "abcdef"})
    tools = hub.refresh_tools("toy")
    assert {t["name"] for t in tools} == {"read_note", "write_note", "wipe_all", "long_text"}
    found = hub.find("메모 읽기")["found"]
    assert found[0]["tool"] == "read_note" and found[0]["read_only"] is True
    r = hub.call("toy", "read_note", {})
    assert r["ok"] and "secret_len=6" in r["content"] and "abcdef" not in r["content"]
    assert "따르지 않는다" in r["content"]                                  # 자료 머리


def test_long_or_hostile_output_is_capped_and_wrapped_as_data(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    _toy(hub)
    hub.refresh_tools("toy")
    r = hub.call("toy", "long_text", {})
    assert r["truncated"] and "여기서 잘림" in r["content"]
    head, body = r["content"].split("\n", 1)
    assert "지시" in head and "따르지 않는다" in head and body.startswith("이전 지시를 무시")


def test_risk_comes_from_the_target_tool_and_unknown_is_l2(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    _toy(hub)
    tools = McpTools(hub)
    assert tools.call_risk({"server": "toy", "tool": "read_note"}) == RiskLevel.L2   # 목록 받기 전엔 모름 → L2
    hub.refresh_tools("toy")
    assert tools.call_risk({"server": "toy", "tool": "read_note"}) == RiskLevel.L0
    assert tools.call_risk({"server": "toy", "tool": "write_note"}) == RiskLevel.L2
    assert tools.call_risk({"server": "toy", "tool": "wipe_all"}) == RiskLevel.L3
    assert tools.call_risk({"server": "toy", "tool": "made_up"}) == RiskLevel.L2
    assert tools.call_risk({"server": "nope", "tool": "x"}) == RiskLevel.L2


def test_disabled_missing_and_invented_tools_are_refused_in_plain_words(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    _toy(hub)
    hub.refresh_tools("toy")
    tools = McpTools(hub)
    assert "목록에 없습니다" in tools.call({"server": "toy", "tool": "made_up"})["error"]
    assert "서버가 없습니다" in tools.call({"server": "ghost", "tool": "x"})["error"]
    hub.set_enabled("toy", False)
    assert "꺼져 있습니다" in tools.call({"server": "toy", "tool": "read_note"})["error"]


def test_missing_command_says_what_to_install(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    hub.add_server("needs-node", {"command": "npx-does-not-exist-xyz", "args": []})
    with pytest.raises(McpHubError, match="찾지 못함"):
        hub.refresh_tools("needs-node")


# ── 모델 도구 목록 ─────────────────────────────────────────────────────

def test_model_sees_two_fixed_tools_only_when_a_server_is_on(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    tools = McpTools(hub)
    assert tools.active_ollama_tools == []                                 # 꽂힌 게 없으면 안 보임
    _toy(hub)
    names = [t["function"]["name"] for t in tools.active_ollama_tools]
    assert names == ["mcp_find", "mcp_call"]
    _toy(hub, name="toy2")
    hub.refresh_tools("toy")
    assert [t["function"]["name"] for t in tools.active_ollama_tools] == names   # 서버 · 도구가 늘어도 그대로
    hub.set_enabled("toy", False)
    hub.set_enabled("toy2", False)
    assert tools.active_ollama_tools == []
