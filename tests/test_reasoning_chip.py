"""입력창 「추론」 칩 — 자동·빠르게·보통·깊게 (2026-09-28 사장님 제안, 헤르메스 입력창의 Med 칩을 보고).

자동 = 싼 것부터 → 막히면 올림(전략안: 예측 라우팅 금지 · 실패하면 승급). 요청 문장으로 난이도를 맞히지 않는다.
"""

from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis.agent import _job_thinking_policy, _reasoning_escalated, _should_think
from alture_jarvis.api import ChatRequest

CONFIG = SimpleNamespace(agent_thinking_enabled=True, agent_thinking_policy="always")
GOOD = [{"tool": "browser_open", "ok": True}, {"tool": "browser_extract", "ok": True}]


def test_each_choice_maps_to_a_policy() -> None:
    assert _job_thinking_policy(CONFIG, "fast", escalated=False) == "off"
    assert _job_thinking_policy(CONFIG, "normal", escalated=False) == "adaptive"
    assert _job_thinking_policy(CONFIG, "deep", escalated=False) == "always"
    assert _job_thinking_policy(CONFIG, "", escalated=False) == "always", "비면 설정을 따른다"


def test_auto_starts_cheap_and_climbs_when_stuck() -> None:
    assert _job_thinking_policy(CONFIG, "auto", escalated=False) == "adaptive"
    assert _job_thinking_policy(CONFIG, "auto", escalated=True) == "always"


def test_auto_does_not_think_on_a_smooth_middle_step_but_does_once_stuck() -> None:
    calm = _job_thinking_policy(CONFIG, "auto", escalated=_reasoning_escalated(GOOD, 0))
    assert not _should_think(CONFIG, GOOD, policy=calm)

    stuck = _job_thinking_policy(CONFIG, "auto", escalated=_reasoning_escalated(GOOD, 1))
    assert _should_think(CONFIG, GOOD, policy=stuck)


def test_two_failures_also_climb() -> None:
    steps = [{"tool": "a", "ok": False}, {"tool": "b", "ok": True}, {"tool": "c", "ok": False}]
    assert _reasoning_escalated(steps, 0)


def test_the_request_carries_the_choice() -> None:
    assert ChatRequest(prompt="x", reasoning="auto").model_dump()["reasoning"] == "auto"
    assert ChatRequest(prompt="x").model_dump()["reasoning"] == ""
