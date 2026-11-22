"""고정 문 `sonjari_tool` (2026-11-15) — 목록이 안 바뀌어도 새 도구를 부르되, 개별 도구보다 **넓게 열리지는 않는다**.

클로드 데스크톱은 list_changed 를 무시한다(docs/설계_MCP도구목록_자동갱신_2026-11-13.ko.md §5-1). 그래서 이름으로 부르는
문을 하나 둔다. 이 시험이 지키는 것은 둘이다.
1. 새로 생긴 도구를 다시 켜지 않고 부를 수 있다(캐시가 아니라 그때 본체에 묻는다).
2. 이 문이 거름망의 뒷문이 되지 않는다 — 막힌 도구 · 꺼진 팩 · 내보내지 않는 도구는 이 문으로도 안 된다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from alture_jarvis.mcp_server import JarvisMcpBridge, ToolFilter, schema_problems


class _Response:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]


class _Body:
    """손자리 본체 흉내 — 도구 목록 · 팩 · 실행. 목록은 시험 중에 바꿀 수 있다(업데이트로 새 도구가 생긴 것)."""

    def __init__(self, tools: list[dict[str, Any]], packs: list[dict[str, Any]] | None = None,
                 execute: dict[str, Any] | None = None, down: bool = False) -> None:
        self.tools = tools
        self.packs = packs or []
        self.execute_payload = execute or {"ok": True, "status": "completed", "result": {"done": True}}
        self.down = down
        self.posts: list[dict[str, Any]] = []
        self.tool_list_reads = 0

    async def get(self, url: str, headers: Any = None, params: Any = None, timeout: Any = None) -> _Response:
        if self.down:
            raise httpx.ConnectError("refused")
        if url.endswith("/v1/tools"):
            self.tool_list_reads += 1
            return _Response(self.tools)
        if url.endswith("/v1/packs"):
            return _Response({"packs": self.packs})
        if url.endswith("/v1/scribe/story"):
            return _Response({"enabled": False})
        if url.endswith("/health"):
            return _Response({"build": "b1"})
        return _Response({}, 404)

    async def post(self, url: str, json: dict[str, Any], headers: Any = None) -> _Response:  # noqa: A002
        if self.down:
            raise httpx.ConnectError("refused")
        self.posts.append({"url": url, "json": json})
        return _Response(self.execute_payload)

    async def aclose(self) -> None:
        return None


SPLIT_SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}, "parts": {"type": "integer"},
                                                 "mode": {"type": "string", "enum": ["auto", "manual"]}},
                "required": ["path"]}


def _tool(name: str, risk: str = "L0", schema: dict[str, Any] | None = None, enabled: bool = True) -> dict[str, Any]:
    return {"name": name, "description": f"{name} 설명", "risk_level": risk, "enabled": enabled,
            "parameters": schema or {"type": "object", "properties": {}}}


def _gen3d_pack(enabled: bool = True, tools: tuple[str, ...] = ("gen_3d", "gen_3d_split_plan")) -> dict[str, Any]:
    return {"id": "gen3d", "name": "3D 생성", "enabled": enabled, "tools": list(tools)}


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    # 본체가 꺼진 판에서 list_tools 가 1.5초씩 두 번 기다린다 — 시험에서는 기다리지 않는다.
    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr("alture_jarvis.mcp_server.asyncio.sleep", _instant)
    monkeypatch.delenv("JARVIS_MCP_TOOLSET", raising=False)
    monkeypatch.delenv("JARVIS_MCP_DELEGATION", raising=False)


def _bridge(body: _Body, **kwargs: Any) -> JarvisMcpBridge:
    return JarvisMcpBridge(token="t", client=body, **kwargs)


def _names(tools: list[dict[str, Any]]) -> list[str]:
    return [str(tool["name"]) for tool in tools]


# ---- 늘 있는 문 ------------------------------------------------------------------


def test_the_door_is_listed_even_when_sonjari_is_off() -> None:
    body = _Body([], down=True)
    names = _names(asyncio.run(_bridge(body).list_tools()))
    assert "sonjari_tool" in names and "sonjari_guide" in names


def test_the_door_is_listed_when_sonjari_is_on_and_only_once() -> None:
    body = _Body([_tool("gen_3d")], packs=[_gen3d_pack()])
    names = _names(asyncio.run(_bridge(body).list_tools()))
    assert names.count("sonjari_tool") == 1


def test_a_runtime_tool_with_the_door_name_does_not_shadow_it(monkeypatch: pytest.MonkeyPatch) -> None:
    # 전부 내보내기 설정에서 본체가 같은 이름을 줘도 목록에 두 벌이 서지 않는다.
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    body = _Body([_tool("sonjari_tool"), _tool("browser_search")])
    names = _names(asyncio.run(_bridge(body).list_tools()))
    assert names.count("sonjari_tool") == 1


# ---- 목적: 새 도구를 다시 켜지 않고 부른다 -------------------------------------------


def test_a_tool_added_by_an_update_is_callable_through_the_door_without_relisting() -> None:
    body = _Body([_tool("gen_3d")], packs=[_gen3d_pack(tools=("gen_3d",))])
    bridge = _bridge(body)
    first = _names(asyncio.run(bridge.list_tools()))  # 클로드가 처음 받아 간 목록
    assert "gen_3d_split_plan" not in first

    # 손자리 업데이트 — 같은 팩에 새 도구가 생겼다. 클로드(데스크톱)는 목록을 다시 묻지 않는다.
    body.tools.append(_tool("gen_3d_split_plan", schema=SPLIT_SCHEMA))
    body.packs[0]["tools"].append("gen_3d_split_plan")

    direct_text, direct_failed = asyncio.run(bridge.call("gen_3d_split_plan", {"path": "a.stl"}))
    door_text, door_failed = asyncio.run(bridge.call("sonjari_tool", {"name": "gen_3d_split_plan",
                                                                       "arguments": {"path": "a.stl"}}))

    assert direct_failed, "옛 목록만 믿는 개별 호출은 새 도구를 못 부른다 — 그래서 이 문이 있다"
    assert door_failed is False, door_text
    assert body.posts[-1]["json"] == {"name": "gen_3d_split_plan", "arguments": {"path": "a.stl"}}


def test_the_door_asks_the_body_every_time() -> None:
    body = _Body([_tool("gen_3d")], packs=[_gen3d_pack(tools=("gen_3d",))])
    bridge = _bridge(body)
    asyncio.run(bridge.call("sonjari_tool", {"name": "gen_3d"}))
    asyncio.run(bridge.call("sonjari_tool", {"name": "gen_3d"}))
    assert body.tool_list_reads == 2


def test_a_normal_call_returns_exactly_what_the_individual_tool_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    body = _Body([_tool("browser_search", schema={"type": "object", "properties": {"query": {"type": "string"}},
                                                  "required": ["query"]})],
                 execute={"ok": True, "status": "completed", "result": {"hits": ["가", "나"]}})
    bridge = _bridge(body)
    direct = asyncio.run(bridge.call("browser_search", {"query": "손자리"}))
    door = asyncio.run(bridge.call("sonjari_tool", {"name": "browser_search", "arguments": {"query": "손자리"}}))
    assert door == direct
    assert body.posts[0]["json"] == body.posts[1]["json"]


def test_arguments_given_as_a_json_string_are_accepted() -> None:
    body = _Body([_tool("gen_3d_split_plan", schema=SPLIT_SCHEMA)], packs=[_gen3d_pack()])
    text, failed = asyncio.run(_bridge(body).call("sonjari_tool", {"name": "gen_3d_split_plan",
                                                                   "arguments": '{"path": "a.stl", "parts": 3}'}))
    assert failed is False, text
    assert body.posts[-1]["json"]["arguments"] == {"path": "a.stl", "parts": 3}


# ---- 안전: 개별 도구보다 넓게 열리지 않는다 --------------------------------------------


def test_a_blocked_tool_stays_blocked_through_the_door(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    body = _Body([_tool("browser_search"), _tool("google_gmail_send", risk="L2"), _tool("camera_look", risk="L1")])
    bridge = _bridge(body)  # 기본 위험 상한 L1 · camera_ 는 기본 제외
    for name in ("google_gmail_send", "camera_look"):
        direct_text, direct_failed = asyncio.run(bridge.call(name, {}))
        text, failed = asyncio.run(bridge.call("sonjari_tool", {"name": name, "arguments": {}}))
        assert direct_failed and failed, (name, text)
        assert "쓸 수 없습니다" in text
    assert body.posts == [], "막힌 도구가 본체 실행까지 갔다"


def test_a_tool_of_a_turned_off_pack_is_refused_and_says_so() -> None:
    body = _Body([_tool("gen_3d"), _tool("gen_3d_split_plan", schema=SPLIT_SCHEMA)],
                 packs=[_gen3d_pack(enabled=False)])
    text, failed = asyncio.run(_bridge(body).call("sonjari_tool", {"name": "gen_3d_split_plan",
                                                                   "arguments": {"path": "a.stl"}}))
    assert failed
    assert "꺼진 팩" in text and "3D 생성" in text and "대신 켜지 마세요" in text
    assert body.posts == []


def test_a_tool_of_a_turned_off_pack_is_refused_even_if_the_body_hides_it() -> None:
    # 꺼진 팩의 도구를 본체가 목록에서 아예 뺀 경우에도 「없는 이름」이 아니라 「팩이 꺼짐」이라고 말한다.
    body = _Body([], packs=[_gen3d_pack(enabled=False)])
    text, failed = asyncio.run(_bridge(body).call("sonjari_tool", {"name": "gen_3d"}))
    assert failed and "꺼진 팩" in text


def test_in_the_default_lean_toolset_low_tools_are_not_reachable_through_the_door() -> None:
    # 기본(맡기기 전용)이면 개별 낮은 도구는 목록에 없다 — 이 문으로도 browser_* 를 직접 못 부른다.
    body = _Body([_tool("browser_search"), _tool("gen_3d")], packs=[_gen3d_pack(tools=("gen_3d",))])
    text, failed = asyncio.run(_bridge(body).call("sonjari_tool", {"name": "browser_search",
                                                                   "arguments": {"query": "x"}}))
    assert failed and "sonjari_task" in text
    assert body.posts == []


def test_include_override_opens_the_door_the_same_way(monkeypatch: pytest.MonkeyPatch) -> None:
    # 사람이 JARVIS_MCP_INCLUDE 로 연 도구는 개별 호출과 똑같이 이 문으로도 열린다(같은 거름망).
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    body = _Body([_tool("camera_look", risk="L1")])
    bridge = _bridge(body, tool_filter=ToolFilter(include=["camera_look"]))
    text, failed = asyncio.run(bridge.call("sonjari_tool", {"name": "camera_look"}))
    assert failed is False, text


def test_own_doors_are_not_called_through_the_door() -> None:
    body = _Body([_tool("gen_3d")], packs=[_gen3d_pack()])
    for name in ("sonjari_task", "sonjari_tool", "ontelic_task", "sonjari_guide"):
        text, failed = asyncio.run(_bridge(body).call("sonjari_tool", {"name": name, "arguments": {"task": "x"}}))
        assert failed and "직접 부르세요" in text, name
    assert body.posts == []


def test_an_irreversible_tool_goes_through_the_same_approval_as_the_individual_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    body = _Body([_tool("google_gmail_send", risk="L2")],
                 execute={"ok": False, "status": "approval_required", "approval_nonce": "secret-nonce-9"})
    bridge = _bridge(body, tool_filter=ToolFilter(max_risk="L2"))
    direct = asyncio.run(bridge.call("google_gmail_send", {"to": "a@b.c"}))
    door = asyncio.run(bridge.call("sonjari_tool", {"name": "google_gmail_send", "arguments": {"to": "a@b.c"}}))
    assert door == direct
    text, failed = door
    assert failed is False and "같은 인자로 다시 호출" in text
    assert "secret-nonce-9" not in text


# ---- 없는 이름 · 꺼진 본체 · 틀린 인자 ------------------------------------------------


def test_an_unknown_name_gets_similar_names_but_never_blocked_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    body = _Body([_tool("gen_3d_split_plan"), _tool("google_gmail_send", risk="L2")])
    bridge = _bridge(body)
    text, failed = asyncio.run(bridge.call("sonjari_tool", {"name": "gen_3d_split_plann"}))
    assert failed and "없습니다" in text and "gen_3d_split_plan" in text
    text, failed = asyncio.run(bridge.call("sonjari_tool", {"name": "google_gmail_sendd"}))
    assert failed and "google_gmail_send" not in text.replace("google_gmail_sendd", ""), "막힌 도구 이름을 알려 줬다"


def test_when_sonjari_is_off_the_door_says_so() -> None:
    body = _Body([], down=True)
    text, failed = asyncio.run(_bridge(body).call("sonjari_tool", {"name": "gen_3d"}))
    assert failed and "연결하지 못했습니다" in text


@pytest.mark.parametrize("arguments, needle", [
    ({}, "필수 칸 `path`"),
    ({"path": 3}, "`path` 는 string"),
    ({"path": "a.stl", "parts": "3"}, "`parts` 는 integer"),
    ({"path": "a.stl", "parts": True}, "`parts` 는 integer"),
    ({"path": "a.stl", "mode": "fast"}, "`mode` 는"),
])
def test_arguments_that_do_not_fit_the_schema_are_not_sent(arguments: dict[str, Any], needle: str) -> None:
    body = _Body([_tool("gen_3d_split_plan", schema=SPLIT_SCHEMA)], packs=[_gen3d_pack()])
    text, failed = asyncio.run(_bridge(body).call("sonjari_tool", {"name": "gen_3d_split_plan", "arguments": arguments}))
    assert failed and needle in text and "스키마" in text, text
    assert body.posts == []


@pytest.mark.parametrize("raw, needle", [
    ({"name": "gen_3d_split_plan", "path": "a.stl"}, "arguments` 안에"),
    ({"name": "gen_3d_split_plan", "arguments": "{not json"}, "JSON"),
    ({"name": "gen_3d_split_plan", "arguments": ["a.stl"]}, "객체"),
    ({"name": ""}, "비어 있습니다"),
])
def test_malformed_door_calls_are_sent_back(raw: dict[str, Any], needle: str) -> None:
    body = _Body([_tool("gen_3d_split_plan", schema=SPLIT_SCHEMA)], packs=[_gen3d_pack()])
    text, failed = asyncio.run(_bridge(body).call("sonjari_tool", raw))
    assert failed and needle in text, text
    assert body.posts == []


def test_a_closed_schema_rejects_unknown_fields() -> None:
    schema = {**SPLIT_SCHEMA, "additionalProperties": False}
    assert schema_problems(schema, {"path": "a", "colour": "red"}) == ["모르는 칸 `colour`"]
    assert schema_problems(SPLIT_SCHEMA, {"path": "a", "colour": "red"}) == [], "열린 스키마는 본체가 판정한다"


# ---- 쓰는 법: help · 가이드 ----------------------------------------------------------


def test_help_returns_the_schema_and_does_not_run_the_tool() -> None:
    body = _Body([_tool("gen_3d_split_plan", schema=SPLIT_SCHEMA)], packs=[_gen3d_pack()])
    text, failed = asyncio.run(_bridge(body).call("sonjari_tool", {"name": "gen_3d_split_plan", "help": True}))
    assert failed is False
    payload = json.loads(text)
    assert payload["parameters"] == SPLIT_SCHEMA and "gen_3d_split_plan 설명" in payload["description"]
    assert body.posts == []


def test_help_for_a_blocked_tool_is_refused_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    body = _Body([_tool("google_gmail_send", risk="L2")])
    text, failed = asyncio.run(_bridge(body).call("sonjari_tool", {"name": "google_gmail_send", "help": True}))
    assert failed and "parameters" not in text


def test_the_guide_answers_an_exact_tool_name_with_its_schema() -> None:
    body = _Body([_tool("gen_3d_split_plan", schema=SPLIT_SCHEMA)], packs=[_gen3d_pack()])
    text, failed = asyncio.run(_bridge(body).call("sonjari_guide", {"query": "gen_3d_split_plan"}))
    assert failed is False and json.loads(text)["parameters"] == SPLIT_SCHEMA


def test_the_guide_does_not_hand_out_schemas_of_blocked_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    body = _Body([_tool("google_gmail_send", risk="L2")])
    text, _ = asyncio.run(_bridge(body).call("sonjari_guide", {"query": "google_gmail_send"}))
    assert '"parameters"' not in text


def test_the_door_description_tells_when_to_use_it() -> None:
    from alture_jarvis.delegation import DOOR_TOOL, localized_tool

    ko = DOOR_TOOL["description"]
    assert "직접 쓰세요" in ko and "목록에 아직 없는" in ko and "help=true" in ko
    en = localized_tool(DOOR_TOOL, "en")["description"]
    assert "use it directly" in en and "not in the list yet" in en


def test_english_connection_gets_english_door_messages() -> None:
    body = _Body([_tool("gen_3d_split_plan", schema=SPLIT_SCHEMA)], packs=[_gen3d_pack()])
    bridge = _bridge(body, lang="en")
    text, failed = asyncio.run(bridge.call("sonjari_tool", {"name": "gen_3d_split_plan", "arguments": {}}))
    assert failed and "required field `path` is missing" in text


def test_the_installed_guide_mentions_the_door() -> None:
    from alture_jarvis.delegation import DELEGATION_TOOLS, DOOR_TOOL, GUIDE_TOOL
    from alture_jarvis.guide_skill import render_skill

    tools = [*DELEGATION_TOOLS, GUIDE_TOOL, DOOR_TOOL]
    for lang in ("ko", "en"):
        body = render_skill(tools, lang)
        assert 'sonjari_tool(name="<' in body and "help=true" in body and "arguments={...}" in body, lang
