"""손자리를 업데이트해도 클로드를 껐다 켜지 않게 — 본체 판이 바뀌면 list_changed 를 한 번 보낸다 (2026-11-13).

설계 docs/설계_MCP도구목록_자동갱신_2026-11-13.ko.md. 실측(클로드 코드 2.1.241 · 프로토콜 2025-11-25): 신호를 받으면 즉시
tools/list 를 다시 부르고 새 도구를 그 세션에서 쓴다 · 신호가 없으면 다시 안 부른다.
"""
from __future__ import annotations

import asyncio

from alture_jarvis.mcp_server import ToolListWatch, watch_tool_list_once


def test_watch_notifies_once_per_new_build_and_only_after_a_list() -> None:
    w = ToolListWatch()
    assert w.observe("b2") is False          # 아직 목록을 안 줬다 — 첫 목록이 어차피 새것
    w.listed("b1")
    assert w.observe("b1") is False          # 같은 판
    assert w.observe("") is False            # 본체 재시작 중 · 오류
    assert w.observe("b2") is True           # 바뀜 → 한 번
    assert w.observe("b2") is False          # 같은 바뀜을 또 알리지 않는다
    w.listed("b2")                           # 클로드가 다시 받아 갔다
    assert w.observe("b2") is False
    assert w.observe("b3") is True


class _Session:
    def __init__(self) -> None:
        self.sent = 0

    async def send_tool_list_changed(self) -> None:
        self.sent += 1


class _Bridge:
    def __init__(self, builds: list[str], session: _Session | None) -> None:
        self.builds = builds
        self.session = session
        self.tool_watch = ToolListWatch()

    async def current_build(self) -> str:
        return self.builds.pop(0)


def test_one_watch_round_sends_on_the_session_only_when_the_build_moved() -> None:
    session = _Session()
    bridge = _Bridge(["b1", "", "b2", "b2"], session)
    bridge.tool_watch.listed("b1")
    results = [asyncio.run(watch_tool_list_once(bridge)) for _ in range(4)]
    assert results == [False, False, True, False] and session.sent == 1


def test_no_session_yet_means_nothing_is_sent() -> None:
    bridge = _Bridge(["b2"], None)
    bridge.tool_watch.listed("b1")
    assert asyncio.run(watch_tool_list_once(bridge)) is False


def test_the_server_tells_claude_it_may_change_its_tool_list() -> None:
    """tools.listChanged = true 를 알려야 클로드가 우리 신호를 받는다 — _run 이 넘기는 옵션과 같은 것을 만든다."""
    from mcp.server.lowlevel import NotificationOptions

    from alture_jarvis.mcp_server import JarvisMcpBridge, ToolFilter, build_server

    bridge = JarvisMcpBridge(base_url="http://127.0.0.1:1", token="t", tool_filter=ToolFilter.from_env(), lang="ko")
    options = build_server(bridge).create_initialization_options(NotificationOptions(tools_changed=True))
    assert options.capabilities.tools is not None and options.capabilities.tools.list_changed is True
    import inspect

    from alture_jarvis import mcp_server
    assert "NotificationOptions(tools_changed=True)" in inspect.getsource(mcp_server._run)


def test_the_app_tells_when_claude_still_runs_an_old_connection(tmp_path) -> None:
    """데스크톱 앱은 list_changed 로 목록을 새로 고치지 않는다(실측) — 연결 프로그램이 붙이는 판 머리글로 「옛 판」을 가른다."""
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.mcp_server import MCP_BUILD

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="t", camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    auth = {"X-JARVIS-TOKEN": "t"}
    with TestClient(app) as client:
        app_build = client.get("/health").json()["build"]
        assert client.get("/v1/claude/mcp-freshness", headers=auth).json()["stale"] is False     # 아직 아무 연결도 없음
        client.get("/health", headers={"X-Sonjari-Mcp-Build": app_build})
        assert client.get("/v1/claude/mcp-freshness", headers=auth).json()["stale"] is False     # 같은 판
        client.get("/health", headers={"X-Sonjari-Mcp-Build": "old0build000"})
        body = client.get("/v1/claude/mcp-freshness", headers=auth).json()
        assert body["stale"] is True and "old0build000" in body["mcp_builds"]
    assert len(MCP_BUILD) == 12
