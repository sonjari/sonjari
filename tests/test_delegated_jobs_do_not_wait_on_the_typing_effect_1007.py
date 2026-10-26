"""바깥 AI 가 맡긴 판은 답을 「스르륵」 칠하느라 끝을 늦추지 않는다 (2026-10-07 코딩 사다리).

판마다 마지막 모델 호출 뒤 3~5초가 더 붙었다. 스택을 0.35초마다 찍어 보니 그 구간 18번 중 17번이
`presentation.paint_answer` 의 쉼이었다 — 확정된 답을 초당 90자로 나눠 내보내는 연출이 판을 도는 스레드에서 돈다.
화면 앞의 사람에게는 정해 둔 속도지만, MCP 로 맡긴 판을 기다리는 것은 호스트(클로드·코덱스)다.
"""
from __future__ import annotations

import inspect

from alture_jarvis import agent, presentation


class _Events:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def publish(self, name: str, payload: dict) -> None:
        self.sent.append((name, payload))


ANSWER = "두 군데를 고쳤습니다. " * 40          # 520자 — 예전 속도로는 쉼만 4초가 넘는다


def _slept(monkeypatch) -> list[float]:
    naps: list[float] = []
    monkeypatch.setattr(presentation.time, "sleep", lambda seconds: naps.append(seconds))
    return naps


def test_a_delegated_answer_goes_out_without_pauses(monkeypatch) -> None:
    naps = _slept(monkeypatch)
    events = _Events()

    assert presentation.paint_answer(events, "job-1", ANSWER, pace=False) is True

    assert naps == []
    deltas = [payload["delta"] for name, payload in events.sent if name == "agent_answer_delta"]
    assert "".join(deltas) == ANSWER
    assert len(deltas) > 50, "칸으로 나눠 보내는 것은 그대로다 — 화면이 따라 내려가는 것은 칸마다 돈다"
    assert events.sent[0] == ("agent_answer_reset", {"job_id": "job-1"})


def test_an_answer_asked_on_screen_keeps_its_pace(monkeypatch) -> None:
    naps = _slept(monkeypatch)
    paced, unpaced = _Events(), _Events()

    presentation.paint_answer(paced, "job-1", ANSWER)
    presentation.paint_answer(unpaced, "job-1", ANSWER, pace=False)

    assert len(naps) > 50 and set(naps) == {presentation.PAINT_TICK_MS / 1000}
    assert paced.sent == unpaced.sent, "보내는 칸은 같다 — 쉬는지만 다르다"
    assert 4.0 <= sum(naps) <= presentation.PAINT_MS_MAX / 1000


def test_the_agent_drops_the_pace_only_for_jobs_another_ai_handed_over() -> None:
    source = inspect.getsource(agent.BrowserAgent.run)
    assert 'paint_answer(self.events, job_id, painted, pace=origin != "mcp")' in source
