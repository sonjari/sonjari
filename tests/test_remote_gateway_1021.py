"""원격 입구(2026-10-21 · 원격 첫 판) — 노트북의 클로드 코드가 테일스케일로 집 PC 손자리를 부른다.

지키는 것:
- 원격 열쇠 없이는 /mcp · /story 가 401. /health 만 열쇠 없이(다른 정보 없음). 열쇠를 바꾸면 옛 열쇠는 바로 401.
- 진짜 MCP 클라이언트가 HTTP 로 붙어 도구 목록 · 도구 부르기가 된다(stdio 와 같은 build_server).
- 원격 판은 `via: "remote"` 가 붙고, 코드 일(repo · check)은 받지 않는다.
- /story 는 카드 글만 — 서기가 읽는 폴더 경로(사람 이름이 든 집 경로)는 노트북에 안 보낸다.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

from alture_jarvis.remote_gateway import build_app, connect_command, ensure_token, token_ok


class FakeBridge:
    lang = "ko"
    token = "control"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    async def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "sonjari_task", "description": "맡기기", "parameters": {"type": "object", "properties": {"task": {"type": "string"}}}}]

    async def call(self, name: str, arguments: dict[str, Any], *, caller: str = "") -> tuple[str, bool]:
        self.calls.append((name, arguments, caller))
        return f"받음: {arguments.get('task')}", False


def test_token_is_made_once_and_rotation_replaces_it(tmp_path: Path) -> None:
    first = ensure_token(tmp_path)
    assert len(first) >= 32 and ensure_token(tmp_path) == first
    second = ensure_token(tmp_path, rotate=True)
    assert second != first and ensure_token(tmp_path) == second
    assert token_ok(second, second) and not token_ok(first, second) and not token_ok("", "")


def test_the_gate_needs_the_remote_key_except_health(tmp_path: Path) -> None:
    from starlette.testclient import TestClient

    async def story(session: str, limit: int) -> dict[str, Any]:
        return {"enabled": True, "count": 1, "card": f"## 정한 것\n- {session} 카드"}

    key = {"value": "k1"}
    app = build_app(FakeBridge(), remote_token=lambda: key["value"], story=story)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"ok": True}
        assert client.get("/story", params={"session": "abc"}).status_code == 401
        assert client.get("/story", params={"session": "abc"}, headers={"Authorization": "Bearer nope"}).status_code == 401
        ok = client.get("/story", params={"session": "abc"}, headers={"Authorization": "Bearer k1"})
        assert ok.status_code == 200 and "abc 카드" in ok.json()["card"]
        assert client.post("/mcp", json={}).status_code == 401
        key["value"] = "k2"  # 열쇠 바꾸기 — 재시작 없이 옛 열쇠가 바로 막힌다
        assert client.get("/story", headers={"Authorization": "Bearer k1"}).status_code == 401


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_real_mcp_client_lists_and_calls_tools_over_http() -> None:
    import uvicorn

    bridge = FakeBridge()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(build_app(bridge, remote_token="k1"), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    async def talk() -> tuple[list[str], str]:
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        http = create_mcp_http_client(headers={"Authorization": "Bearer k1"})
        async with http, streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = [tool.name for tool in (await session.list_tools()).tools]
                result = await session.call_tool("sonjari_task", {"task": "노트북에서 맡김"})
                return tools, result.content[0].text

    try:
        tools, text = asyncio.run(talk())
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert tools == ["sonjari_task"]
    assert text == "받음: 노트북에서 맡김" and bridge.calls[0][0] == "sonjari_task"


def test_remote_bridge_marks_via_and_refuses_code_tasks() -> None:
    from alture_jarvis.mcp_server import JarvisMcpBridge

    sent: list[dict[str, Any]] = []

    class Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"job_id": "j1", "status": "queued"}

    class Client:
        async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> Response:
            sent.append(json)
            return Response()

        async def get(self, *args: Any, **kwargs: Any) -> Response:
            return Response()

    bridge = JarvisMcpBridge(token="t", client=Client(), via="remote")
    text, failed = asyncio.run(bridge._delegate("sonjari_task", {"task": "고쳐 줘", "repo": "C:/x", "check": "pytest"}))
    assert failed and "코드 일" in text and sent == [], "원격으로는 코드 일을 받지 않는다 — 백엔드까지 안 간다"
    asyncio.run(bridge._delegate("sonjari_task", {"task": "가격 조사"}))
    assert sent and sent[-1]["via"] == "remote" and sent[-1]["origin"] == "mcp"
    local = JarvisMcpBridge(token="t", client=Client())
    asyncio.run(local._delegate("sonjari_task", {"task": "가격 조사"}))
    assert "via" not in sent[-1], "이 PC 의 stdio 연결은 그대로"


def test_the_backend_keeps_via_in_the_job_payload() -> None:
    from alture_jarvis.api import ChatRequest

    assert ChatRequest(prompt="x", origin="mcp", via="remote").model_dump()["via"] == "remote"
    assert ChatRequest(prompt="x").model_dump()["via"] == ""


def test_the_story_sent_to_the_laptop_has_no_folder_paths() -> None:
    from alture_jarvis import remote_gateway

    class Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"enabled": True, "count": 2, "card": "## 정한 것", "folders": ["C:/Users/사람이름/.claude/projects/x"], "items": [{"a": 1}]}

    class Client:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def get(self, *a: Any, **k: Any) -> Resp:
            return Resp()

    import httpx

    original = httpx.AsyncClient
    httpx.AsyncClient = Client  # type: ignore[misc]
    try:
        data = asyncio.run(remote_gateway._story_fetcher("http://x", "t")("s", 10))
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]
    assert data == {"enabled": True, "count": 2, "card": "## 정한 것"}
    assert "사람이름" not in json.dumps(data, ensure_ascii=False)


def test_the_connect_line_is_the_claude_code_http_form() -> None:
    line = connect_command("abc", "home.tail1.ts.net")
    assert line == 'claude mcp add --transport http sonjari https://home.tail1.ts.net/mcp --header "Authorization: Bearer abc"'


def test_remote_hides_and_blocks_the_unity_pack_tools() -> None:
    """10-21 첫 실행: 원격 목록에 유니티 게임 팩 도구 7개가 같이 나왔다 — 집 PC 프로젝트를 바꾸는 도구라 원격 첫 판에선 뺀다."""
    from alture_jarvis.remote_gateway import remote_filter

    remote = remote_filter({})
    assert not remote.allows({"name": "unity_try_script"}) and not remote.allows({"name": "unity_run_recipe"})
    assert remote.allows({"name": "sonjari_task"}) and remote.allows({"name": "sonjari_story"})
    assert not remote.allows({"name": "camera_snap"}), "이 PC 연결의 기본 제외도 그대로"


def test_the_gateway_binds_only_to_this_pc_or_a_tailscale_address() -> None:
    """10-21: 테일넷 serve 가 꺼져 있어 테일스케일 주소에 직접 묶는 길을 열었다 — 0.0.0.0 · 공유기 주소는 막는다."""
    from alture_jarvis.remote_gateway import bind_host_ok

    assert bind_host_ok("127.0.0.1") and bind_host_ok("100.64.0.10") and bind_host_ok("100.64.0.1")
    for bad in ("0.0.0.0", "192.168.0.10", "192.168.0.91", "8.8.8.8", "localhost", "100.128.0.1", ""):
        assert not bind_host_ok(bad), bad
    assert connect_command("k", "100.64.0.10:8093", scheme="http").startswith("claude mcp add --transport http sonjari http://100.64.0.10:8093/mcp")
