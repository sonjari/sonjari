"""출처 도장 (2026-09-30) — 찾아보지 않은 답은 답이 무슨 말을 하든 「기억으로 답함」이 찍힌다.

09-30 새벽 코워크: 「헤르메스 레딧에서 전부 확인해 줘」에 도구 0회·33초로 「레딧·GitHub·공식 문서까지
확인했습니다」라고 답했다. 낱말표로 막지 않는다 — 판에서 성공한 도구 걸음 수라는 구조적 사실에 건다.
"""
from __future__ import annotations

import pytest

from alture_jarvis.agent import AgentRunResult
from alture_jarvis.api import create_app
from alture_jarvis.runtime import answer_grounding

from test_api import _config


def _runtime(tmp_path):
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    runtime._learn_facts = lambda *_args, **_kwargs: None
    return runtime


def _chat(runtime, prompt: str, **extra):
    payload = {"prompt": prompt, "session_id": "stamp", "origin": "workspace", "delivery": "screen",
               "agent_mode": "auto", **extra}
    job = runtime.enqueue("chat", prompt[:40], payload)
    return runtime._chat_job(runtime.store.get_job(job["id"]))


def test_a_claimed_check_without_tools_is_stamped_memory(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime._general_route = lambda *_a, **_k: ("answer", "네, 레딧·GitHub 까지 확인했습니다.", None)
    runtime.agent.run = lambda *_a, **_k: pytest.fail("답 경로인데 에이전트로 감")

    result = _chat(runtime, "헤르메스 한번 확인한번 해주라 레딧이나 이런데 전부다")

    assert result["grounding"] == {"basis": "memory", "observed_steps": 0}
    stored = runtime.memory.recent("stamp", limit=2)[-1]
    assert stored["role"] == "assistant"
    assert stored["metadata"]["grounding"]["basis"] == "memory"


def test_the_observe_button_skips_the_router_and_demands_a_real_step(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime._general_route = lambda *_a, **_k: pytest.fail("버튼으로 온 요청이 갈래 추측을 탔다")
    captured: dict = {}

    def fake_run(prompt: str, **kwargs):
        captured.update(kwargs)
        return AgentRunResult(
            answer="레딧 글을 열어 읽었습니다.",
            steps=[{"tool": "browser_open_result", "ok": True}],
            verification={"completion_state": "complete"}, plan={},
            contract={"version": "task-contract-shadow-v1", "clauses": []},
        )

    runtime.agent.run = fake_run
    result = _chat(runtime, "헤르메스 한번 깊게 파줘", observe=True)

    assert captured["must_observe"] is True
    assert result["grounding"] == {"basis": "observed", "observed_steps": 1}


def test_failed_steps_are_not_evidence() -> None:
    trace = {"steps": [{"tool": "browser_open", "ok": False}, {"tool": "browser_search", "ok": False}]}
    assert answer_grounding(trace, None, attached=False)["basis"] == "memory"


@pytest.mark.parametrize(
    ("observation", "attached", "basis"),
    [
        (None, True, "attachment"),
        ({"takeover": {"kind": "continue"}}, False, "takeover"),
        ({"frame": "camera"}, False, "camera"),
        ({}, False, "memory"),
    ],
)
def test_what_the_answer_looked_at_decides_the_stamp(observation, attached, basis) -> None:
    assert answer_grounding(None, observation, attached=attached)["basis"] == basis
