"""「글로만 답하라」는 곁가지 부름도 **직전 걸음의 도구 목록**을 그대로 보낸다.

★ 2026-09-28 확인 판 947a1d65: 빈 답 채우기를 `tools=None` 으로 불러 목록이 비었다가(시스템 지시 뒤부터 다시 읽음) 다음 걸음에
돌아왔다(또 다시 읽음) — 계측기에 09:24:28·09:24:39 두 줄로 찍혔다. 같은 목록을 보내고, 모델이 도구만 부르고 글이 없을 때만
목록 없이 한 번 더 부른다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent

TOOLS = [{"type": "function", "function": {"name": "browser_open", "parameters": {"type": "object"}}}]


class _Recorder:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = replies
        self.seen: list[object] = []

    def __call__(self, messages, *, job_id, tools, think, model_role="chat", inference_profile=None, allowed_code_tools=None):
        self.seen.append(tools)
        return self.replies.pop(0), 0


def _agent(replies: list[dict]) -> tuple[BrowserAgent, _Recorder]:
    agent = BrowserAgent.__new__(BrowserAgent)
    recorder = _Recorder(replies)
    agent._model_message = recorder  # type: ignore[method-assign]
    agent._offered_tools = {"j": (TOOLS, None)}
    return agent, recorder


def test_a_text_answer_is_taken_with_the_same_list() -> None:
    agent, recorder = _agent([{"role": "assistant", "content": "답입니다.", "tool_calls": [{"function": {"name": "browser_open"}}]}])

    message, _ = agent._text_only_message([], job_id="j", think=False)

    assert recorder.seen == [TOOLS], "곁가지 부름이 목록을 바꿨다 — 캐시가 깨진다"
    assert message["content"] == "답입니다." and "tool_calls" not in message


def test_only_a_tool_call_retries_without_the_list() -> None:
    agent, recorder = _agent([
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_open"}}]},
        {"role": "assistant", "content": "글로 쓴 답"},
    ])

    message, _ = agent._text_only_message([], job_id="j", think=False)

    assert recorder.seen == [TOOLS, None]
    assert message["content"] == "글로 쓴 답"


def test_without_a_previous_list_it_calls_without_tools() -> None:
    agent, recorder = _agent([{"role": "assistant", "content": "답"}])
    agent._offered_tools = {}

    agent._text_only_message([], job_id="j", think=False)

    assert recorder.seen == [None]
