"""자비스를 MCP 로 내보낼 때 지켜야 하는 것들.

파는 것을 생각하면 여기가 상품의 핵심이다. 비슷한 데스크톱 자동화 MCP 들은 도구만
던져 준다 — 2026-08-06 에 nuphus 를 검토하고 도입하지 않은 이유가 그것이었다(도구
36개가 우리 게이트웨이 **바깥**에 붙는다). 우리가 내보내는 것은 도구가 아니라
**규칙이 붙은 도구**다. 그 규칙이 여기서 새면 남는 게 없다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from alture_jarvis.mcp_server import JarvisMcpBridge, ToolFilter, describe


@pytest.fixture(autouse=True)
def _full_toolset(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 파일은 **낮은 도구에 붙은 규칙**(승인·토큰·스키마)을 본다. 기본값이 맡기기 전용(2026-09-23)이 된 뒤로는
    낮은 도구가 안 나가므로, 규칙을 보려면 전부 내보내는 설정에서 돌린다 — 규칙은 그 설정에서도 지켜져야 한다."""
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")


class _Response:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(self.status_code)


class _Client:
    """자비스 흉내. 무엇이 오갔는지 기록한다."""

    def __init__(self, tools: list[dict[str, Any]] | None = None, execute: Any = None) -> None:
        self.tools = tools or []
        self.execute_payload = execute or {"ok": True, "tool": "x", "status": "completed", "result": {"v": 1}}
        self.posts: list[dict[str, Any]] = []
        self.status_code = 200

    async def get(self, url: str) -> _Response:
        return _Response(self.tools)

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> _Response:  # noqa: A002
        self.posts.append({"url": url, "json": json, "headers": headers})
        return _Response(self.execute_payload, self.status_code)

    async def aclose(self) -> None:
        return None


TOOLS = [
    {"name": "browser_search", "description": "검색", "risk_level": "L0", "enabled": True,
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "browser_extract", "description": "본문", "risk_level": "L0", "enabled": True, "parameters": {}},
    {"name": "google_gmail_send", "description": "메일 발송", "risk_level": "L2", "enabled": True, "parameters": {}},
    {"name": "camera_look", "description": "카메라", "risk_level": "L1", "enabled": True, "parameters": {}},
    {"name": "ui_click_target", "description": "화면 클릭", "risk_level": "L1", "enabled": True, "parameters": {}},
    {"name": "naver_blog_publish", "description": "발행", "risk_level": "L2", "enabled": False, "parameters": {}},
]


# ---- 승인 규칙이 바깥에서도 살아 있는가 -------------------------------------------


def test_an_irreversible_tool_is_not_executed_without_approval() -> None:
    """★ 이게 새면 상품이 아니라 그냥 도구 모음이다."""
    client = _Client(tools=TOOLS, execute={"ok": False, "tool": "google_gmail_send",
                              "status": "approval_required", "approval_nonce": "n1", "risk_level": "L2"})
    # 기본값에서는 애초에 안 나간다. 일부러 열었을 때 승인이 걸리는지를 잰다.
    bridge = JarvisMcpBridge(token="t", client=client, tool_filter=ToolFilter(max_risk="L2"))

    text, failed = asyncio.run(bridge.call("google_gmail_send", {"to": "a@b.c"}))

    assert failed is False, "오류로 던지면 모델이 다른 도구로 우회한다 — 안내로 돌려줘야 한다"
    assert "승인" in text
    assert "같은 인자로 다시 호출" in text
    assert "대신해 승인할 수 없" in text


def test_the_approval_nonce_is_never_handed_to_the_model() -> None:
    # nonce 를 주면 모델이 그걸로 승인을 흉내내려 든다. 승인은 사람 화면에서만 난다.
    client = _Client(tools=TOOLS, execute={"ok": False, "tool": "google_gmail_send",
                              "status": "approval_required", "approval_nonce": "secret-nonce-1"})
    bridge = JarvisMcpBridge(token="t", client=client, tool_filter=ToolFilter(max_risk="L2"))

    text, _ = asyncio.run(bridge.call("google_gmail_send", {}))

    assert "secret-nonce-1" not in text


def test_irreversible_tools_say_so_in_their_description() -> None:
    # 딱지(risk_level=L2)는 모델에게 아무 뜻이 없다. 무슨 일이 일어나는지 말해야 한다.
    warned = describe({"description": "메일 발송", "risk_level": "L2"})
    plain = describe({"description": "검색", "risk_level": "L0"})

    assert "되돌릴 수 없" in warned and "승인" in warned
    assert "되돌릴 수 없" not in plain


# ---- 무엇을 내보내는가 -----------------------------------------------------------


def test_physical_device_tools_are_not_exposed_by_default() -> None:
    # 카메라·짐벌은 이 PC 에 물린 물리 장치다. 다른 창에서 부르면 보고 있는 화면이
    # 말없이 움직인다.
    names = {tool["name"] for tool in ToolFilter().apply(TOOLS)}

    assert "camera_look" not in names
    assert "ui_click_target" not in names
    assert "browser_search" in names


def test_disabled_tools_are_not_exposed() -> None:
    names = {tool["name"] for tool in ToolFilter().apply(TOOLS)}

    assert "naver_blog_publish" not in names


def test_an_explicit_include_beats_the_default_exclusion() -> None:
    names = {tool["name"] for tool in ToolFilter(include=["camera_look"]).apply(TOOLS)}

    assert "camera_look" in names
    assert "ui_click_target" not in names, "이름을 적은 것만 열려야 한다"


def test_hiding_a_tool_also_blocks_calling_it() -> None:
    """★ 감추는 것만으로는 못 막는다 (2026-08-06 실측).

    목록에서 뺀 `google_gmail_send` 를 그냥 불렀더니 그대로 자비스까지 갔다 —
    MCP 클라이언트는 목록에 없는 이름도 보낼 수 있고, 모델은 앞선 대화나 짐작으로
    이름을 안다. 승인 게이트가 있어 실행되지는 않았지만, "안 내보낸다"는 약속이
    목록에서만 지켜지고 호출에서는 안 지켜지고 있었다.
    """
    client = _Client(tools=TOOLS)
    bridge = JarvisMcpBridge(token="t", client=client)

    text, failed = asyncio.run(bridge.call("google_gmail_send", {"to": "a@b.c"}))

    assert failed is True
    assert client.posts == [], "자비스까지 가면 안 된다 — 여기서 끊겨야 한다"
    assert "이 연결로 쓸 수 없습니다" in text
    assert "우회하려 하지" in text


def test_an_allowed_tool_still_goes_through() -> None:
    client = _Client(tools=TOOLS)
    bridge = JarvisMcpBridge(token="t", client=client)

    _, failed = asyncio.run(bridge.call("browser_search", {"query": "x"}))

    assert failed is False
    assert len(client.posts) == 1


def test_a_jarvis_outage_does_not_masquerade_as_a_forbidden_tool() -> None:
    # 목록을 못 가져온 것과 "금지된 도구"를 섞으면 진짜 원인이 가려진다.
    class _Broken(_Client):
        async def get(self, url: str) -> _Response:
            raise RuntimeError("connection refused")

    client = _Broken()
    bridge = JarvisMcpBridge(token="t", client=client)

    _, failed = asyncio.run(bridge.call("browser_search", {"query": "x"}))

    assert len(client.posts) == 1, "막지 말고 보내야 진짜 오류 메시지가 나온다"


def test_irreversible_tools_are_not_exported_by_default() -> None:
    """★ 사용자님 결정(2026-08-06): 바깥 클라이언트에는 그 능력을 아예 주지 않는다.

    승인을 건너뛰는 것이 아니다 — 목록에 없으면 부를 수가 없다. 승인 카드는 자비스
    창에 뜨는데 클로드 데스크톱에서 부르면 사용자님은 다른 화면을 보고 계시고, 아무도
    안 보는 카드는 5분 뒤 만료된다(같은 창 안에서도 이미 한 번 놓쳤다).

    메일 발송·일정 삭제·블로그 발행은 자비스 창에 그대로 남는다.
    """
    names = {tool["name"] for tool in ToolFilter().apply(TOOLS)}

    assert "google_gmail_send" not in names
    assert "browser_search" in names, "읽고 조사하는 일은 전부 열려 있어야 한다"


def test_the_ceiling_can_be_raised_on_purpose() -> None:
    # 열더라도 승인은 여전히 걸린다 — 게이트웨이가 판정하지 이 필터가 하는 게 아니다.
    names = {tool["name"] for tool in ToolFilter(max_risk="L2").apply(TOOLS)}

    assert "google_gmail_send" in names


def test_an_empty_env_value_does_not_silently_open_everything() -> None:
    # JARVIS_MCP_MAX_RISK= (빈 값)이 L2 로 읽히면 설정 실수 하나로 전부 열린다.
    names = {tool["name"] for tool in ToolFilter.from_env({"JARVIS_MCP_MAX_RISK": ""}).apply(TOOLS)}

    assert "google_gmail_send" not in names


def test_the_filter_reads_the_environment() -> None:
    tool_filter = ToolFilter.from_env({
        "JARVIS_MCP_INCLUDE": "camera_look, ui_click_target",
        "JARVIS_MCP_EXCLUDE": "browser_extract",
        "JARVIS_MCP_MAX_RISK": "L1",
    })
    names = {tool["name"] for tool in tool_filter.apply(TOOLS)}

    assert {"camera_look", "ui_click_target"} <= names
    assert "browser_extract" not in names
    assert "google_gmail_send" not in names


# ---- 스키마가 실려 나가는가 -------------------------------------------------------


def test_tools_carry_their_argument_schema() -> None:
    """이름과 설명만 내보내면 모델이 인자를 지어낸다 — 도구를 안 주느니만 못하다."""
    bridge = JarvisMcpBridge(token="t", client=_Client(tools=TOOLS))

    tools = asyncio.run(bridge.list_tools())

    search = next(tool for tool in tools if tool["name"] == "browser_search")
    assert search["parameters"]["properties"]["query"]["type"] == "string"
    assert search["parameters"]["required"] == ["query"]


# ---- 못 붙었을 때 ----------------------------------------------------------------


def test_a_wrong_token_says_what_to_fix() -> None:
    client = _Client(tools=TOOLS)
    client.status_code = 401
    bridge = JarvisMcpBridge(token="wrong", client=client)

    text, failed = asyncio.run(bridge.call("browser_search", {"query": "x"}))

    assert failed is True
    assert "JARVIS_CONTROL_TOKEN" in text


def test_the_token_rides_on_every_call() -> None:
    client = _Client(tools=TOOLS)
    bridge = JarvisMcpBridge(token="tok-1", client=client)

    asyncio.run(bridge.call("browser_search", {"query": "x"}))

    assert client.posts[0]["headers"]["X-JARVIS-TOKEN"] == "tok-1"


def test_a_result_comes_back_as_readable_text() -> None:
    client = _Client(tools=TOOLS, execute={"ok": True, "tool": "browser_search", "status": "completed",
                              "result": {"results": [{"rank": 1, "title": "제주 경비"}]}})
    bridge = JarvisMcpBridge(token="t", client=client)

    text, failed = asyncio.run(bridge.call("browser_search", {"query": "제주"}))

    assert failed is False
    assert "제주 경비" in text, "한글이 \\uXXXX 로 나가면 사람도 모델도 못 읽는다"
