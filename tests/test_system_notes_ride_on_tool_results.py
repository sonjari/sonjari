"""판 도중 `[시스템]` 안내는 **바로 앞 도구 결과에 붙어** 모델에 간다 (2026-09-29 실측).

사용자 메시지로 따로 붙이면 Qwen 렌더러가 앞 걸음을 다르게 그려 캐시가 중간부터 깨졌다
(같은 요청 7,244/7,244 · 도구를 뒤에 붙임 7,243/7,298 · [시스템] 사용자 메시지 5,902/7,251).
"""

from alture_jarvis.transcript import attach_system_notes

TASK = {"role": "user", "content": "다나와에서 마우스 찾아줘"}
CALL = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_open", "arguments": {}}}]}
TOOL = {"role": "tool", "tool_name": "browser_open", "content": '{"ok": true}'}
NOTE = {"role": "user", "content": "[시스템] 남은 것: 가격 3개"}


def test_a_note_after_a_tool_result_rides_on_it() -> None:
    out = attach_system_notes([{"role": "system", "content": "s"}, TASK, CALL, TOOL, NOTE])
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool"]
    assert out[-1]["content"] == '{"ok": true}\n\n[시스템] 남은 것: 가격 3개'
    assert out[1] is TASK, "시킨 일은 그대로"


def test_the_rule_is_the_same_every_step_so_the_prefix_never_moves() -> None:
    """걸음 N 에서 붙인 모양이 걸음 N+1 의 앞부분과 **글자까지 같아야** 캐시가 산다."""
    step_n = attach_system_notes([TASK, CALL, TOOL, NOTE])
    step_n1 = attach_system_notes([TASK, CALL, TOOL, NOTE, CALL, TOOL])
    assert step_n1[: len(step_n)] == step_n


def test_what_stays_a_user_message() -> None:
    answer = {"role": "assistant", "content": "다 했습니다"}
    human = {"role": "user", "content": "아 그리고 가격순으로"}
    pushback = {"role": "user", "content": "[시스템] 아직 파일이 없다"}
    out = attach_system_notes([TASK, answer, pushback, CALL, TOOL, human])
    assert out[2] == pushback, "어시스턴트 답 뒤의 되받기는 사용자 메시지로 남는다"
    assert out[-1] == human, "사람이 덧붙인 말은 사람 말이다"


def test_many_notes_stack_in_order_and_the_original_is_untouched() -> None:
    second = {"role": "user", "content": "[시스템] 파일로 만들어라"}
    original = [TASK, CALL, dict(TOOL), NOTE, second]
    out = attach_system_notes(original)
    assert out[-1]["content"].endswith("[시스템] 남은 것: 가격 3개\n\n[시스템] 파일로 만들어라")
    assert original[2]["content"] == '{"ok": true}', "원래 전사를 고쳤다 — 여러 곳이 [시스템] 표시를 센다"
    assert len(original) == 5


def test_the_agent_sends_the_attached_copy() -> None:
    import inspect

    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent)
    assert "bounded = attach_system_notes(bounded)" in source
