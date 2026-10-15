"""코드 판의 읽기 관문은 횟수가 아니라 「같은 것을 또 보는가」로 건다 · 손을 좁혀도 보내는 목록은 그대로 (2026-10-09 새벽).

우리 숙제(큰 저장소에 기능 하나 넣기)를 손자리에게 맡긴 판에서: 모델은 서로 다른 곳 37군데를 읽었고 되풀이는 0번이었다.
그런데 「열 번 보기만 했으면 고쳐라」 관문이 세 번 걸려 쓰는 손만 남겼고, 읽지 못한 채 고치려다 세 번 실패했다. 그 사이
도구 목록이 여섯 번 뒤집혀 대화 전체를 다시 읽었다(다시 읽기 841초 가운데 264초). 생각 예산 표는 운영 모델 이름을 못 알아봐
기본값으로 돌고 있었다.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import (
    BrowserAgent,
    _LOOKS_BACKSTOP,
    _RELOOKS_LIMIT,
    code_tools_after_look_pushback,
    looking_in_circles,
    offered_code_tools,
    stalled_looks,
)
from alture_jarvis.code_runtime import refusal_for_tool_not_this_turn
from alture_jarvis.config import DEFAULT_THINKING_BUDGETS
from alture_jarvis.ollama import OllamaClient

_TOOLS = frozenset({"local_read_text_file", "local_grep", "local_apply_edit", "local_write_file", "local_run_project_command", "ask_user"})


def _read(path: str, start: int, end: int, ok: bool = True) -> dict:
    return {"tool": "local_read_text_file", "ok": ok, "arguments": {"path": path, "line_start": start, "line_end": end}}


def _grep(pattern: str) -> dict:
    return {"tool": "local_grep", "ok": True, "arguments": {"path": "src", "pattern": pattern, "context": 2, "max_results": 20}}


def _exploring(count: int) -> list[dict]:
    """서로 다른 곳을 `count` 번 — 큰 파일을 범위로 나눠 읽고, 서로 다른 것을 찾는다."""
    return [(_read("src/pkg/big.py", index * 80 + 1, index * 80 + 80) if index % 2 else _grep(f"symbol_{index}")) for index in range(count)]


# ── 판정: 같은 것을 또 보는가 ───────────────────────────────────────────────────


def test_reading_many_new_places_is_exploring_not_stalling() -> None:
    steps = _exploring(_LOOKS_BACKSTOP - 1)
    assert stalled_looks(steps) == (0, _LOOKS_BACKSTOP - 1)
    assert not looking_in_circles(steps)
    assert code_tools_after_look_pushback(_TOOLS, steps, 2) == _TOOLS


def test_looking_at_the_same_things_again_is_stalling() -> None:
    once = [_read("src/pkg/big.py", 1, 80), _grep("needle")]
    steps = once * 4                                   # 2번 새로 · 6번 다시
    assert stalled_looks(steps) == (6, 8)
    assert looking_in_circles(steps)
    assert code_tools_after_look_pushback(_TOOLS, steps, 2) == frozenset({"local_apply_edit", "local_write_file", "ask_user"})


def test_just_under_the_limit_is_left_alone() -> None:
    steps = [_grep("needle")] * _RELOOKS_LIMIT             # 1번 새로 · (한도-1)번 다시
    assert stalled_looks(steps)[0] == _RELOOKS_LIMIT - 1
    assert not looking_in_circles(steps)


def test_a_different_range_of_the_same_file_is_a_new_look() -> None:
    steps = [_read("src/pkg/big.py", start, start + 99) for start in range(1, 2001, 100)]
    assert stalled_looks(steps) == (0, 20)


def test_only_looking_for_very_long_is_still_pushed_once() -> None:
    assert looking_in_circles(_exploring(_LOOKS_BACKSTOP))


def test_a_successful_write_starts_the_count_over_but_remembers_what_was_seen() -> None:
    seen_before = [_grep("needle"), _read("src/pkg/big.py", 1, 80)]
    steps = seen_before + [{"tool": "local_apply_edit", "ok": True, "arguments": {"path": "src/pkg/big.py"}}] + seen_before
    assert stalled_looks(steps) == (2, 2)              # 고친 뒤 다시 본 것은 「다시 본 것」이지만 두 번이라 한도 아래


def test_a_failed_edit_frees_the_hands_again() -> None:
    steps = [_grep("needle")] * 8
    assert looking_in_circles(steps, since_attempt=True)
    steps.append({"tool": "local_apply_edit", "ok": False, "arguments": {"path": "src/pkg/big.py"}})
    assert stalled_looks(steps, since_attempt=True) == (0, 0)
    assert code_tools_after_look_pushback(_TOOLS, steps, 2) == _TOOLS
    assert stalled_looks(steps)[1] == 8                # 성공한 쓰기만 보는 쪽(되받기)은 그대로 센다


def test_the_gate_is_wired_into_the_loop() -> None:
    source = inspect.getsource(BrowserAgent.run)
    assert "and looking_in_circles(steps)" in source
    assert "looks_without_write(steps) >= _LOOKS_WITHOUT_WRITE_LIMIT" not in source
    assert "looking_in_circles(steps, since_attempt=True)" in inspect.getsource(code_tools_after_look_pushback)


# ── 보내는 목록은 그대로 ────────────────────────────────────────────────────────

_WRITE_ONLY = frozenset({"local_apply_edit", "local_write_file", "ask_user"})


def test_the_model_keeps_seeing_the_whole_list_while_the_hands_are_narrowed() -> None:
    assert offered_code_tools(_TOOLS, _WRITE_ONLY, [_grep("needle")]) == _TOOLS


def test_ignoring_the_refusal_twice_in_a_row_narrows_the_list() -> None:
    refused = {"tool": "local_grep", "ok": False, "error": "code_tool_not_in_active_profile"}
    assert offered_code_tools(_TOOLS, _WRITE_ONLY, [refused]) == _TOOLS
    assert offered_code_tools(_TOOLS, _WRITE_ONLY, [refused, refused]) == _WRITE_ONLY
    # 사이에 받아들여진 걸음이 끼면 다시 전체를 보여 준다.
    assert offered_code_tools(_TOOLS, _WRITE_ONLY, [refused, refused, {"tool": "local_apply_edit", "ok": False}]) == _TOOLS


def test_nothing_changes_when_the_hands_are_not_narrowed_or_there_is_no_profile() -> None:
    assert offered_code_tools(_TOOLS, _TOOLS, []) == _TOOLS
    assert offered_code_tools(None, None, []) is None
    assert offered_code_tools(None, _WRITE_ONLY, []) == _WRITE_ONLY


def test_the_refusal_names_what_is_accepted_and_how_it_lifts() -> None:
    refusal = refusal_for_tool_not_this_turn("local_grep", _WRITE_ONLY, profile="code")
    assert refusal["ok"] is False and refusal["error"] == "code_tool_not_in_active_profile"
    text = refusal["instruction"]
    assert "지금 차례가 아니다" in text and "열려 있지 않다" not in text
    assert all(f"`{name}`" in text for name in _WRITE_ONLY)
    assert "실패해도" in text


def test_the_offered_list_and_the_enforced_hands_are_wired_separately() -> None:
    source = inspect.getsource(BrowserAgent.run)
    assert "offered_code_tools(" in source
    # 검증 관문이 더 좁힌 걸음은 예전 그대로 좁힌 목록을 보낸다(말로만 답하는 판 — 좁힌 목록이 신호다).
    assert "if active_code_tools == hands_after_look_gate" in source
    assert "allowed_code_tools=shown_code_tools" in source          # 모델에게 보내는 목록
    assert "self._offered_tools = {job_id: (model_tools, shown_code_tools)}" in source
    assert "name not in active_code_tools" in source                 # 받는 손은 디스패치가 가른다
    assert "set(active_code_tools)" in source                        # 글로 온 호출을 되살릴 때도 받는 손 기준
    assert "refusal_for_tool_not_this_turn(name, frozenset(active_code_tools)" in source
    assert "if name in (shown_code_tools or ())" in source           # 보이는데 안 받는 손에만 「지금 차례가 아니다」


# ── 생각 예산: 파생 모델은 가족의 값을 따른다 ──────────────────────────────────


def _budget(model: str, table: dict[str, int] | None = None, default: int = 8000) -> int:
    client = SimpleNamespace(config=SimpleNamespace(
        ollama_thinking_char_budget=default,
        ollama_thinking_budget_by_model=dict(DEFAULT_THINKING_BUDGETS if table is None else table),
        agent_thinking_policy="always",
    ))
    return OllamaClient._thinking_budget_for(client, model)  # type: ignore[arg-type]


def test_a_model_built_on_a_family_takes_the_family_budget() -> None:
    derived = "hf.co/someone/Swift-1.5-Qwen3.8-27B-GGUF:Swift-1.5-Qwen3.8-27B-IQ3_S-mtp.gguf"
    assert _budget(derived) == DEFAULT_THINKING_BUDGETS["qwen3.8"]


def test_the_leading_name_still_wins_and_unknown_models_keep_the_default() -> None:
    assert _budget("qwen3.6:35b") == DEFAULT_THINKING_BUDGETS["qwen3.6"]
    assert _budget("hf.co/someone/Ornith-1.5-35B-GGUF:Q4_K_M") == DEFAULT_THINKING_BUDGETS["ornith"]
    assert _budget("gemma4:26b") == 8000
    assert _budget("hf.co/someone/Totally-New-9B-GGUF:Q4") == 8000


def test_the_longer_family_name_is_tried_first_inside_a_name() -> None:
    table = {"qwen3": 1000, "qwen3.8": 16000}
    assert _budget("hf.co/someone/Swift-Qwen3.8-27B:Q3", table) == 16000


def test_the_module_keeps_the_old_diagnostic_count() -> None:
    """진단값(`looks_without_write`)은 그대로 둔다 — 사건 기록과 화면이 읽는다."""
    assert agent_module.looks_without_write(_exploring(12)) == 12
