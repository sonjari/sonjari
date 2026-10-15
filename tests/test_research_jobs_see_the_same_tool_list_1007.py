"""조사 판에도 **같은 도구 목록**을 보낸다 — 갈래 밖의 손은 부르면 되돌려 보낸다 (2026-10-07 서버 기록).

도구 목록은 프롬프트 맨 앞에 그려진다. 웹 조사 판만 좁힌 목록(79개)을 받고 그 밖의 판은 전체(123개)를 받아서,
두 종류의 판이 번갈아 올 때마다 2만~2만 7천 토큰(7~10초)을 처음부터 다시 읽었다(하루 54번).
좁힌 까닭(2026-09-09: 책 조사 판이 진로DB 를 6번 불렀다)은 그대로 막는다 — 헛손은 실행되지 않는다.
"""
from __future__ import annotations

import inspect
from typing import Any

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import (
    _ROUTE_REFUSAL,
    _route_hands,
    _route_refusals,
    _route_scoped_tool_definitions,
)


def _tool(name: str, description: str = "설명") -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": {}}}}


WHOLE = [_tool("browser_open"), _tool("browser_extract"), _tool("local_write_file"), _tool("ask_user"),
         _tool("career_strategy_lookup", "진로 전략 조회 " * 20), _tool("camera_look", "카메라로 본다 " * 20)]
SCOPED = _route_scoped_tool_definitions(WHOLE, web_only=True)


def test_the_web_route_keeps_only_its_own_hands() -> None:
    assert [t["function"]["name"] for t in SCOPED] == ["browser_open", "browser_extract", "local_write_file", "ask_user"]


def test_a_research_job_on_a_wide_window_sees_everything_and_may_call_only_its_route() -> None:
    outside = _route_hands(WHOLE, SCOPED, window=262_144, refused=0)

    assert outside == frozenset({"career_strategy_lookup", "camera_look"}), "막는 것은 전체에는 있고 웹 갈래에는 없는 이름뿐이다"


def test_a_hand_the_harness_swaps_in_is_not_bounced_for_being_off_the_list() -> None:
    """하네스는 검색 호출을 지목한 사이트 열기로 바꿔 부르기도 한다 — 보여 준 목록에 없는 이름이라고 막으면 안 된다."""
    only_search = [_tool("browser_search")]
    scoped = _route_scoped_tool_definitions(only_search, web_only=True)

    assert _route_hands(only_search, scoped, window=262_144, refused=0) is None, "갈래 밖의 손이 하나도 없으면 막을 것도 없다"


def test_a_job_that_is_not_research_has_no_route_limit() -> None:
    same = _route_scoped_tool_definitions(WHOLE, web_only=False)

    assert same is WHOLE
    assert _route_hands(WHOLE, same, window=262_144, refused=0) is None


def test_after_two_refusals_the_job_gets_the_narrow_list_for_good() -> None:
    """되돌려 보내기를 안 따르는 판이 있다(09-28 의 35B). 두 번이면 그 판은 끝까지 좁힌 목록이다."""
    assert _route_hands(WHOLE, SCOPED, window=262_144, refused=1) is not None
    assert _route_hands(WHOLE, SCOPED, window=262_144, refused=2) is None
    steps = [
        {"tool": "career_strategy_lookup", "ok": False, "error": _ROUTE_REFUSAL},
        {"tool": "browser_open", "ok": True, "error": ""},
        {"tool": "camera_look", "ok": False, "error": _ROUTE_REFUSAL},
        {"tool": "browser_extract", "ok": True, "error": ""},
    ]
    assert _route_refusals(steps) == 2, "연달아가 아니라 판 전체로 센다 — 좁혔다 넓혔다 하면 그때마다 캐시가 깨진다"


def test_a_small_window_keeps_the_narrow_list() -> None:
    """창이 작은 모델에게는 그 자리가 본문을 읽을 자리다 — 더 실리는 도구 정의가 창의 5% 를 넘으면 예전처럼 좁힌다."""
    extra_tokens = (len(str(WHOLE)) - len(str(SCOPED))) / agent_module._TOOL_SCHEMA_CHARS_PER_TOKEN
    tight = int(extra_tokens / agent_module._ROUTE_WHOLE_LIST_MAX_SHARE * 0.5)

    assert _route_hands(WHOLE, SCOPED, window=tight, refused=0) is None
    assert _route_hands(WHOLE, SCOPED, window=0, refused=0) is None, "창을 못 재면 좁힌다"


def test_the_run_loop_sends_the_whole_list_only_when_the_route_allows_it() -> None:
    source = inspect.getsource(agent_module.BrowserAgent.run)
    scope = source.index("route_scoped_tools = _route_scoped_tool_definitions(")
    decide = source.index("route_hands = None if compact_surface else _route_hands(")
    narrow = source.index("if route_hands is None:\n                    available_model_tools = route_scoped_tools")
    assert scope < decide < narrow


def test_a_hand_outside_the_route_is_bounced_before_it_runs() -> None:
    source = inspect.getsource(agent_module.BrowserAgent.run)
    bounce = source.index("elif route_hands and name in route_hands:")
    unknown = source.index('observation = {"ok": False, "tool": name, "error": "unknown_tool"}')
    assert bounce < unknown, "실행으로 가기 전에 되돌려 보낸다"
    refusal = source[bounce: bounce + 900]
    assert '"error": _ROUTE_REFUSAL' in refusal and "권한이나 정책 거절이 아니다" in refusal


# ── 2026-10-10: the whole-list rule had silently switched off at 128K ─────────────────────────────────────────
#
# 10-07 에 이 장치를 넣을 때 운영 창은 256K 였고, 위 시험들도 256K 로만 쟀다. 10-08 에 운영 모델이 128K 창으로 바뀌자
# 「더 실리는 도구 정의」가 창의 5% 를 넘어(어림 8,335토큰 = 6.4%) 조사 판이 다시 좁힌 목록을 받았다 — 아무 말 없이.
# 종류가 바뀔 때마다 앞부분 2만~3만 토큰을 처음부터 읽는 것을 대표가 「아직 살짝 느리다」로 찾았다.
# 아래 크기는 그날 운영 카탈로그에서 잰 값이다: 갈래 밖의 손 56개 · JSON 으로 25,005자.
_REAL_OUTSIDE_TOOLS = 56
_REAL_OUTSIDE_CHARS = 25_005


def _real_sized_lists() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import json

    inside = [_tool(f"browser_tool_{i}") for i in range(81)]
    per_tool = _REAL_OUTSIDE_CHARS // _REAL_OUTSIDE_TOOLS
    outside: list[dict[str, Any]] = []
    for i in range(_REAL_OUTSIDE_TOOLS):
        tool = _tool(f"camera_tool_{i}", "")
        pad = per_tool - len(json.dumps(tool, ensure_ascii=False)) - 2   # ", " between list items
        tool["function"]["description"] = "x" * max(pad, 0)
        outside.append(tool)
    whole = inside + outside
    scoped = _route_scoped_tool_definitions(whole, web_only=True)
    assert len(scoped) == 81
    extra = len(json.dumps(whole, ensure_ascii=False)) - len(json.dumps(scoped, ensure_ascii=False))
    assert abs(extra - _REAL_OUTSIDE_CHARS) < 400, extra
    return whole, scoped


def test_the_whole_list_is_shown_at_the_128k_window_we_actually_run() -> None:
    whole, scoped = _real_sized_lists()

    assert _route_hands(whole, scoped, window=131_072, refused=0) is not None, "128K 에서 꺼지면 종류가 바뀔 때마다 앞부분을 다시 읽는다"
    assert _route_hands(whole, scoped, window=262_144, refused=0) is not None


def test_a_64k_window_still_gets_the_narrow_list() -> None:
    """64K 에서는 더 실리는 양이 창의 약 13% 다 — 그 자리는 본문을 읽을 자리다."""
    whole, scoped = _real_sized_lists()

    assert _route_hands(whole, scoped, window=65_536, refused=0) is None
    assert _route_hands(whole, scoped, window=49_152, refused=0) is None


def test_the_rule_has_room_for_the_tool_list_to_grow_at_128k() -> None:
    """도구가 늘면 더 실리는 양도 는다 — 그날 크기에서 2할쯤 더 늘어도 128K 에서는 켜져 있어야 한다(턱걸이로 두지 않는다)."""
    limit_tokens = 131_072 * agent_module._ROUTE_WHOLE_LIST_MAX_SHARE
    today_tokens = _REAL_OUTSIDE_CHARS / agent_module._TOOL_SCHEMA_CHARS_PER_TOKEN

    assert today_tokens * 1.2 <= limit_tokens
