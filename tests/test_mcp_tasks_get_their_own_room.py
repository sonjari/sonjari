"""MCP 로 맡긴 과제는 **제 대화방**에서 돈다 (2026-09-29 1순위 버그).

대화 번호를 안 보내면 `/v1/chat` 이 「사람이 지금 보고 있는 대화」로 넣었다 — 바깥 AI 과제끼리, 그리고 대표
대화와 문맥이 섞였다(「example.com 열어 제목」에 앞 과제 「깃허브 조직 생성…」으로 답함, 잡 57f2f258).
"""

import asyncio
import json

import httpx

from alture_jarvis.mcp_server import JarvisMcpBridge

TOKEN = "t0ken"


def _send_two() -> list[dict]:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat":
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"id": f"j{len(sent)}"})
        return httpx.Response(404)

    async def run() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        bridge = JarvisMcpBridge("http://ontelic.test", TOKEN, client=client)
        for task in ("깃허브 조직 만드는 곳 열어 줘", "example.com 열어 제목 알려 줘"):
            _text, error = await bridge._delegate("sonjari_task", {"task": task})
            assert not error
        await client.aclose()

    asyncio.run(run())
    return sent


def test_each_task_gets_its_own_conversation():
    first, second = _send_two()
    for body in (first, second):
        room = str(body.get("session_id") or "")
        assert room.startswith("mcp-"), "대화 번호가 없으면 사람이 보고 있는 방으로 들어간다"
        assert room not in {"office-main", ""}
    assert first["session_id"] != second["session_id"], "과제끼리 같은 방을 쓰면 앞 과제가 문맥으로 샌다"
    assert first["origin"] == "mcp"


def test_the_room_name_survives_the_api_normalizer():
    """정규화기가 `mcp-` 방 이름을 깎아 다른 방으로 만들면 안 된다."""
    from alture_jarvis.memory import normalize_session_id

    (body, _second) = _send_two()
    assert normalize_session_id(body["session_id"]) == body["session_id"]
