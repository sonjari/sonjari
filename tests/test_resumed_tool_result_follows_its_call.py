"""재개한 도구의 결과는 **그 호출 바로 뒤에** 온다 (2026-09-30 촬영 판).

질문 카드에 답했는데 Gemma 4 가 「아직 선택하지 않으셨습니다」라며 같은 질문을 세 번 띄웠다. DB 에는 답이 있었다.
재개 때 설정 단계가 임무 요약(`[MISSION CHECKPOINT]`)과 코드 도구 안내를 다시 붙여 **호출과 결과 사이에** 끼었기 때문이다.
실제 판 대화로 재생: 끼어든 순서 3/3 되물음 → 결과를 바로 뒤로 옮긴 순서 0/3. 승인 뒤 재개(문서 쓰기 등)도 같은 자리를 지난다.
"""

from __future__ import annotations

import inspect

from alture_jarvis.agent import BrowserAgent, hold_notes_after_last_call

CALL = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "ask_user", "arguments": {}}}]}
MISSION = {"role": "system", "content": "[MISSION CHECKPOINT]\n원래 목표: 메모 앱"}
PROFILE = {"role": "user", "content": "[system context] Code tool profile=core+preview."}


def test_notes_between_the_call_and_its_result_are_held_back() -> None:
    messages = [{"role": "user", "content": "메모 앱 만들어"}, CALL, MISSION, PROFILE]

    held = hold_notes_after_last_call(messages)
    messages.append({"role": "tool", "tool_name": "ask_user", "content": '{"answer": "파이썬"}'})
    messages.extend(held)

    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "system", "user"]
    assert held == [MISSION, PROFILE], "안내를 버렸다 — 옮기기만 해야 한다"


def test_an_earlier_parallel_result_stays_in_place() -> None:
    first = {"role": "tool", "tool_name": "local_read_file", "content": "{}"}
    messages = [CALL, first, MISSION]

    held = hold_notes_after_last_call(messages)

    assert messages == [CALL, first]
    assert held == [MISSION]


def test_nothing_to_do_without_a_call() -> None:
    messages = [{"role": "user", "content": "안녕"}, MISSION]

    assert hold_notes_after_last_call(messages) == []
    assert len(messages) == 2


def test_the_resume_path_uses_it_and_puts_the_notes_back() -> None:
    source = inspect.getsource(BrowserAgent.run)
    replay = source[source.index("if pending_tool_call:"):]
    replay = replay[: replay.index("resumed_evidence =")]

    assert "held_notes = hold_notes_after_last_call(messages)" in replay
    assert replay.count("messages.extend(held_notes)") == 2, "결과 뒤 · 다시 승인 대기로 저장할 때 둘 다 돌려놔야 한다"


def test_the_code_profile_note_is_added_once() -> None:
    source = inspect.getsource(BrowserAgent.run)

    assert 'if not any(item.get("content") == profile_note for item in messages):' in source
