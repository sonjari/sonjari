"""글만 쓰라고 했는데 도구 부르는 글만 쓴 판 (2026-11-02 · 판 28168caf · 3.6 2비트).

13걸음 동안 Opus 4.8 · 5 페이지를 다 읽고 마무리 답에서: 도구 목록을 준 부름 → 도구만 부름(글 0자) · 목록 뺀 부름 →
`<tool_call>` 글 104자. 그 글을 걷어 내자 빈 답이라 답이 「(모델이 도구를 부르는 글만 적고 끝냈습니다)」였다.
"""
from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent, _TEXT_ONLY_RETRY_NOTE, _only_leaked_tool_call

LEAKED = "<tool_call>\n<function=browser_open>\n<parameter=url>\nhttps://artificialanalysis.ai/models/comparisons/x\n</parameter>\n</function>\n</tool_call>"


def _agent(replies: list[dict[str, Any]]) -> tuple[BrowserAgent, list[dict[str, Any]]]:
    agent = object.__new__(BrowserAgent)
    agent._offered_tools = {"j": ([{"type": "function", "function": {"name": "browser_open"}}], set())}
    calls: list[dict[str, Any]] = []

    def fake(messages, *, job_id, tools, think, model_role="chat", inference_profile=None, allowed_code_tools=None):
        calls.append({"tools": tools, "last": messages[-1]["content"]})
        return replies[len(calls) - 1], 1

    agent._model_message = fake  # type: ignore[method-assign]
    return agent, calls


def test_a_leaked_call_is_asked_once_more_with_a_note() -> None:
    agent, calls = _agent([{"content": "", "tool_calls": [{"function": {"name": "browser_open"}}]},
                           {"content": LEAKED},
                           {"content": "Opus 5 는 Opus 4.8 보다 지능 지수가 높습니다(읽은 페이지 기준)."}])
    message, used = agent._text_only_message_inner([{"role": "user", "content": "알아봐 줘"}], job_id="j", think=False,
                                                   model_role="chat", inference_profile=None)
    assert message["content"].startswith("Opus 5")
    assert len(calls) == 3 and calls[2]["tools"] is None and calls[2]["last"] == _TEXT_ONLY_RETRY_NOTE
    assert used == 3


def test_a_normal_answer_is_not_asked_again() -> None:
    agent, calls = _agent([{"content": "", "tool_calls": [{"function": {"name": "browser_open"}}]},
                           {"content": "답 본문입니다."}])
    message, _ = agent._text_only_message_inner([{"role": "user", "content": "q"}], job_id="j", think=False,
                                                model_role="chat", inference_profile=None)
    assert message["content"] == "답 본문입니다." and len(calls) == 2


def test_if_the_retry_also_leaks_the_old_reply_stays() -> None:
    agent, calls = _agent([{"content": "", "tool_calls": [{"function": {"name": "x"}}]}, {"content": LEAKED}, {"content": LEAKED}])
    message, _ = agent._text_only_message_inner([{"role": "user", "content": "q"}], job_id="j", think=False,
                                                model_role="chat", inference_profile=None)
    assert message["content"] == LEAKED and len(calls) == 3   # 한 번만 더 — 끝없이 부르지 않는다


def test_what_counts_as_only_a_leaked_call() -> None:
    assert _only_leaked_tool_call(LEAKED)
    assert not _only_leaked_tool_call("결론: Opus 5 가 앞선다.\n" + LEAKED)     # 답 본문이 있으면 그대로
    assert not _only_leaked_tool_call("```\n" + LEAKED + "\n```")              # 코드 칸 안의 형식 설명은 답의 내용
    assert not _only_leaked_tool_call("평범한 답")
