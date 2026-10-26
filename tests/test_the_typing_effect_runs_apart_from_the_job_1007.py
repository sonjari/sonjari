"""본 창이 시킨 판의 답은 **판 밖에서** 칠한다 — 연출 때문에 판이 늦게 끝나지 않게 (2026-10-07).

확정된 답을 초당 90자로 칠하는 연출이 판을 도는 스레드에서 돌아, 칠하기가 끝나야 판이 끝났다(답 491~1,167자에서 3.1~5.4초).
그동안 뒤에 줄 선 판이 못 시작하고 결과 카드도 안 떴다. 연출의 속도는 그대로 두고 자리만 옮긴다.
"""
from __future__ import annotations

import inspect
import threading
import time

from alture_jarvis import agent, presentation


class _Events:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self._lock = threading.Lock()

    def publish(self, name: str, payload: dict) -> None:
        with self._lock:
            self.sent.append((name, dict(payload)))


def _wait_for_painter(job_id: str) -> None:
    for thread in threading.enumerate():
        if thread.name == f"paint-{job_id[:8]}":
            thread.join(timeout=10)


def test_the_caller_gets_control_back_before_the_answer_is_painted() -> None:
    events = _Events()
    answer = "두 군데를 고쳤습니다. " * 12          # 156자 — 예전에는 여기서 1.7초를 서 있었다

    started = time.monotonic()
    assert presentation.paint_answer_apart(events, "job-apart-1", answer) is True
    returned_after = time.monotonic() - started

    assert returned_after < 0.5, "부른 쪽(판을 도는 스레드)은 기다리지 않는다"
    assert events.sent[0] == ("agent_answer_reset", {"job_id": "job-apart-1", "apart": True}), (
        "화면에 「이 답은 판이 끝난 뒤에도 조각이 온다」고 먼저 알린다"
    )
    _wait_for_painter("job-apart-1")
    names = [name for name, _ in events.sent]
    assert names[-1] == "agent_answer_painted" and names.count("agent_answer_reset") == 1
    assert "".join(payload["delta"] for name, payload in events.sent if name == "agent_answer_delta") == answer


def test_the_pace_on_screen_is_unchanged(monkeypatch) -> None:
    """자리만 옮긴다 — 칸의 크기도 쉬는 길이도 판 안에서 칠할 때와 같다."""
    naps: list[float] = []
    monkeypatch.setattr(presentation.time, "sleep", lambda seconds: naps.append(seconds))
    apart, inline = _Events(), _Events()
    answer = "가나다라마바사아자차카타파하 " * 30

    presentation.paint_answer_apart(apart, "job-apart-2", answer)
    _wait_for_painter("job-apart-2")
    apart_naps = list(naps)
    naps.clear()
    presentation.paint_answer(inline, "job-apart-2", answer)

    assert apart_naps == naps and set(naps) == {presentation.PAINT_TICK_MS / 1000}
    deltas = lambda events: [payload["delta"] for name, payload in events.sent if name == "agent_answer_delta"]  # noqa: E731
    assert deltas(apart) == deltas(inline)


def test_the_screen_is_told_even_when_painting_fails() -> None:
    """화면은 「다 칠했다」를 기다린다 — 칠하다 터져도 그 사건은 간다."""
    class _Breaks(_Events):
        def publish(self, name: str, payload: dict) -> None:
            super().publish(name, payload)
            if name == "agent_answer_delta":
                raise RuntimeError("화면으로 가는 길이 끊겼다")

    events = _Breaks()
    presentation.paint_answer_apart(events, "job-apart-3", "답입니다. " * 5)
    _wait_for_painter("job-apart-3")

    assert events.sent[-1] == ("agent_answer_painted", {"job_id": "job-apart-3"})


def test_nothing_to_paint_starts_nothing() -> None:
    events = _Events()

    assert presentation.paint_answer_apart(events, "job-apart-4", "") is False
    assert presentation.paint_answer_apart(events, "", "답") is False
    assert events.sent == []


def test_only_jobs_asked_in_the_main_window_are_painted_apart() -> None:
    """맡긴 판은 쉬지 않고 한 번에(호스트가 기다린다), 음성·작은 창은 예전처럼 판 안에서 — 그쪽 화면은 이 약속을 모른다."""
    source = inspect.getsource(agent.BrowserAgent.run)
    branch = source.index('if origin == "workspace":\n            paint_answer_apart(self.events, job_id, painted)')
    other = source.index('paint_answer(self.events, job_id, painted, pace=origin != "mcp")')
    assert branch < other
