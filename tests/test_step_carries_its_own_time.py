"""걸음이 **자기가 걸린 시간을 들고 다니는가.**

## 어제 반쪽만 고쳤다

2026-09-09 에 `took_ms` 를 처음으로 채웠다고 적었다. 실제로 채운 곳은 **관찰
보관소**였다. 그런데 보관소는 메모리에 살고 TTL 로 죽는다 — 판이 끝난 뒤 남는
것은 `agent_trace.steps` 뿐이다.

그래서 다음 날 사슬 벤치를 재 보니 **10판 2,495초가 전부 「도구 0초」** 였다.
도구가 느린지 모델이 느린지 여전히 못 갈랐다. 값을 만든 자리와 값을 읽는 자리가
다르면, 만든 쪽만 고치고 **고쳤다고 믿게 된다.**

이 검사가 없어서 그 반쪽이 통과했다. 그래서 읽는 쪽(걸음 기록)을 직접 붙든다.
"""
from __future__ import annotations

from typing import Any


def test_the_step_record_keeps_how_long_the_tool_took() -> None:
    from alture_jarvis.agent import BrowserAgent
    from alture_jarvis.events import EventBus

    agent = object.__new__(BrowserAgent)
    agent.events = EventBus()
    agent.attention = None
    steps: list[dict[str, Any]] = []

    agent._record_observation(
        job_id="job-1",
        name="browser_extract",
        arguments={"url": "https://example.com"},
        step_number=1,
        label="본문 읽기",
        observation={"ok": True, "status": "ok", "took_ms": 1234,
                     "payload": {"text": "본문"}},
        steps=steps,
        messages=[],
        evidence_urls=[],
        last_action_ids={},
        tool_numbers=set(),
        tool_numbers_body=set(),
    )

    assert steps, "걸음이 안 남았다"
    assert steps[0].get("took_ms") == 1234, (
        "걸음에 시간이 없다 — 보관소에만 적으면 판이 끝나는 순간 사라진다"
    )


def test_a_tool_that_never_reported_its_time_is_zero_not_missing() -> None:
    """값이 없을 때 **칸이 없는 것**과 **0인 것**은 다르다.

    칸 자체가 없으면 읽는 쪽이 `None` 을 더하다 터지거나, 조용히 건너뛰어
    분모에서 빠진다. 이 저장소가 분모로 여러 번 속았으므로 0 을 명시한다.
    """
    from alture_jarvis.agent import BrowserAgent
    from alture_jarvis.events import EventBus

    agent = object.__new__(BrowserAgent)
    agent.events = EventBus()
    agent.attention = None
    steps: list[dict[str, Any]] = []

    agent._record_observation(
        job_id="job-2",
        name="skill_read",
        arguments={},
        step_number=1,
        label="스킬 읽기",
        observation={"ok": True, "status": "ok"},
        steps=steps,
        messages=[],
        evidence_urls=[],
        last_action_ids={},
        tool_numbers=set(),
        tool_numbers_body=set(),
    )

    assert steps[0]["took_ms"] == 0
