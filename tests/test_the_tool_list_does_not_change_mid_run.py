"""판 도중 **도구 목록을 바꾸지 않는다** — 좁히는 것은 부를 때 한다.

★ 2026-09-28 캐시 깨짐 계측기 첫 기록(02:41): 메시지는 뒤에 붙기만 했는데(54→56) 도구 목록이 바뀌었다. Qwen 템플릿은 도구 목록을
시스템 지시(≈2만 토큰) 바로 뒤에 그려서, 목록이 바뀌면 딱 그 지점부터 대화 전체를 다시 읽는다 — 레딧 판이 늘 20,923 토큰으로
떨어진 것과 같은 모양이다. 판 도중 목록을 바꾸던 자리 둘(산출물 집중 · 코드 최종 답)을 「보낼 목록은 그대로, 부를 수 있는 이름만
좁힘」으로 바꿨다.
"""

from __future__ import annotations

from alture_jarvis.agent import _focused_tool_definitions, _offered_and_allowed


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object"}}}


TOOLS = [_tool(name) for name in ("browser_search", "browser_open", "local_write_document", "artifact_from_observations")]


def test_artifact_focus_keeps_the_list_and_narrows_the_hands() -> None:
    focused = _focused_tool_definitions(TOOLS, "artifact")

    offered, hands = _offered_and_allowed(TOOLS, focused, final_answer_only=False)

    assert offered is TOOLS, "산출물 집중에서 목록을 바꿨다 — 시스템 지시 뒤부터 다시 읽는다"
    assert hands == {"local_write_document", "artifact_from_observations"}


def test_code_final_answer_keeps_the_list_and_allows_nothing() -> None:
    offered, hands = _offered_and_allowed(TOOLS, TOOLS, final_answer_only=True)

    assert offered is TOOLS, "코드 최종 답에서 목록을 비웠다 — 마지막 걸음에 대화 전체를 다시 읽는다"
    assert hands == frozenset()


def test_an_ordinary_step_allows_everything() -> None:
    offered, hands = _offered_and_allowed(TOOLS, _focused_tool_definitions(TOOLS, ""), final_answer_only=False)

    assert offered is TOOLS
    assert hands is None


def test_ignored_refusals_fall_back_to_narrowing_the_list() -> None:
    """확인 판 947a1d65: 되돌려 보내기만으로는 35B 가 `browser_open` 을 다섯 번 되풀이했다. 두 번 무시하면 목록 자체를 좁힌다."""
    focused = _focused_tool_definitions(TOOLS, "artifact")

    offered, hands = _offered_and_allowed(TOOLS, focused, final_answer_only=False, refused=2)
    assert offered is focused

    offered, _ = _offered_and_allowed(TOOLS, TOOLS, final_answer_only=True, refused=2)
    assert offered == []


def test_stage_refusals_are_not_a_stuck_screen() -> None:
    """차례 규칙 되돌림은 「같은 자리에서 연속 실패 → 사람에게 넘김」으로 세지 않는다."""
    from alture_jarvis.agent import _stuck_report

    steps = [{"tool": "browser_search", "ok": True}] + [
        {"tool": "browser_open", "ok": False, "error": "not_this_stage"} for _ in range(6)
    ]

    assert _stuck_report(steps) is None
