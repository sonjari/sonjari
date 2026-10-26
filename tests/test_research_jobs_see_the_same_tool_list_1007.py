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
    narrow = source.index("if route_hands is None:")
    assign = source.index("available_model_tools = route_scoped_tools", narrow)
    assert scope < decide < narrow < assign


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


# ── 2026-10-24: the same disease came back, and the order made every switch a full re-read ──────────────────────
#
# 도구가 늘어 128K 에서도 조사 판이 다시 좁힌 목록(79개)을 받았다 — 판 첫 걸음 30.6초(133개 · 30,154토큰). 위 시험은 10-10 날의
# 크기를 숫자로 박아 둬서 못 잡았다. 그리고 등록부 순서로는 갈래 밖의 손이 목록 맨 앞에 끼어 있어, 좁힌 목록과 넓은 목록이
# **첫 도구부터** 달랐다. 아래는 실제 앱의 목록으로 잰다(시험용 앱은 운영보다 도구가 적다 — 크기 대신 모양을 붙든다).

def _real_app_tools(tmp_path) -> list[dict[str, Any]]:  # noqa: ANN001
    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs", control_token="test-token",
        camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False, camera_control_enabled=False,
        google_oauth_client_id="test.apps.googleusercontent.com", google_write_enabled=True,
    )
    return create_app(config, start_services=False).state.jarvis.agent_tools.ollama_tools


def _names(tools: list[dict[str, Any]]) -> list[str]:
    return [str(tool["function"]["name"]) for tool in tools]


def test_the_narrow_research_list_is_the_head_of_the_wide_list(tmp_path) -> None:  # noqa: ANN001
    """좁힌 목록이 넓은 목록의 앞부분과 같아야, 판 종류가 바뀌어도 늘어난 뒤쪽만 다시 읽는다."""
    from alture_jarvis.tool_roster import _platform_scoped_tool_definitions, _stable_tool_order

    ordered = _stable_tool_order(_real_app_tools(tmp_path))
    for said in ("깃허브 저장소 셋을 조사해 엑셀로 정리해 줘", "조사해서 메일로 보내고 일정도 잡아 줘"):
        wide = _platform_scoped_tool_definitions(ordered, said)
        narrow = _platform_scoped_tool_definitions(_route_scoped_tool_definitions(ordered, web_only=True), said)
        assert len(narrow) < len(wide)
        assert _names(wide)[: len(narrow)] == _names(narrow), said


def test_the_raw_registry_order_would_have_broken_the_head(tmp_path) -> None:  # noqa: ANN001
    """이 시험이 보려는 빈칸 — 등록부 순서 그대로면 갈래 밖의 손이 앞에 끼어 앞부분이 갈린다."""
    raw = _real_app_tools(tmp_path)
    narrow = _route_scoped_tool_definitions(raw, web_only=True)
    assert _names(raw)[: len(narrow)] != _names(narrow)


def test_ordering_keeps_every_tool_and_the_order_inside_each_group(tmp_path) -> None:  # noqa: ANN001
    from alture_jarvis.tool_roster import _in_web_route, _is_platform_write, _stable_tool_order

    raw = _real_app_tools(tmp_path)
    ordered = _stable_tool_order(raw)
    assert sorted(_names(ordered)) == sorted(_names(raw))
    group = lambda name: 2 if _is_platform_write(name) else 0 if _in_web_route(name) else 1  # noqa: E731
    groups = [group(name) for name in _names(ordered)]
    assert groups == sorted(groups)
    for g in (0, 1, 2):
        assert [n for n in _names(ordered) if group(n) == g] == [n for n in _names(raw) if group(n) == g]
    assert any(group(n) == 2 for n in _names(raw)), "올리기 손이 하나도 없으면 맨 뒤로 보내는 것을 못 본다"


def test_the_extra_is_measured_on_what_is_actually_sent() -> None:
    """올리기 손은 바로 다음에 빠진다 — 그것까지 세어 128K 조사 판을 좁히지 않는다(10-24: 11,434 대 실제 9,397토큰)."""
    from alture_jarvis.tool_roster import _platform_scoped_tool_definitions

    inside = [_tool(f"browser_tool_{i}") for i in range(80)]
    outside = [_tool(f"camera_tool_{i}", "x" * 400) for i in range(50)]          # 보내는 차 ≈ 8,600토큰 · 128K 의 6.6%
    posting = [_tool(f"naver_blog_step_{i}", "x" * 1500) for i in range(10)]     # 말 안 하면 빠지는 손 ≈ 5,300토큰
    whole = inside + outside + posting
    scoped = _route_scoped_tool_definitions(whole, web_only=True)
    said = "책 세 권 쪽수 조사해 줘"
    sent_whole = _platform_scoped_tool_definitions(whole, said)
    sent_scoped = _platform_scoped_tool_definitions(scoped, said)
    assert _route_hands(sent_whole, sent_scoped, window=131_072, refused=0) is not None
    assert _route_hands(whole, scoped, window=131_072, refused=0) is None, "옛 재기로는 좁혔다 — 이 시험이 보려는 빈칸"


def test_the_run_loop_orders_the_list_and_measures_the_sent_lists() -> None:
    source = inspect.getsource(agent_module.BrowserAgent)
    assert "_stable_tool_order(self.tools.ollama_tools)" in source
    assert "_platform_scoped_tool_definitions(available_model_tools, platform_request_text, planned=planned_action_tools)" in source
    assert '"agent_route_list_narrowed"' in source
