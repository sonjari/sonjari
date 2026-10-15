"""작업 도중에 덧붙인 말 (2026-09-26, 사용자: 「클로드 코드 데스크톱처럼 하는 도중에 얘기해도 보고 방향을 조정」)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.runtime import JarvisRuntime


class _Events:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        self.sent.append((kind, payload))


def _agent() -> BrowserAgent:
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.events = _Events()
    agent._steer_inbox, agent._steer_lock = {}, __import__("threading").Lock()
    agent._steer_applied = {}
    return agent


def test_a_note_reaches_the_model_before_the_next_step_exactly_once() -> None:
    agent = _agent()
    assert agent.steer("job", "  기차 말고   자동차로 봐 줘 ")
    messages: list[dict[str, Any]] = []
    assert agent._apply_steer("job", messages, 4) == 1
    assert messages[-1]["role"] == "user" and "기차 말고 자동차로 봐 줘" in messages[-1]["content"]
    assert "버리지 말고" in messages[-1]["content"], "지금까지 찾은 것을 버리라는 뜻이 아니다"
    assert agent.events.sent == [("agent_steer_applied", {"job_id": "job", "text": "기차 말고 자동차로 봐 줘", "step": 4})]
    assert agent._apply_steer("job", messages, 5) == 0, "한 번 전한 말을 또 넣지 않는다"


def test_notes_do_not_leak_between_jobs_and_leftovers_come_back() -> None:
    agent = _agent()
    agent.steer("a", "첫째")
    agent.steer("b", "둘째")
    assert agent._apply_steer("a", [], 1) == 1
    assert agent.take_leftover_steer("b") == ["둘째"]
    assert agent.take_leftover_steer("b") == []


def test_empty_notes_and_floods_are_refused() -> None:
    agent = _agent()
    assert not agent.steer("job", "   ")
    for _ in range(BrowserAgent._STEER_MAX):
        assert agent.steer("job", "더")
    assert not agent.steer("job", "넘침")


def test_the_loop_reads_notes_right_after_the_cancel_check() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    loop = source.index("while (auto_continue_budget or len(steps) < step_limit) and not finish_now:")
    assert source.index("self._apply_steer(job_id, messages, len(steps))", loop) - loop < 400


class _Store:
    def __init__(self, job: dict[str, Any] | None) -> None:
        self.job = job

    def get_job(self, _job_id: str) -> dict[str, Any] | None:
        return self.job


def _runtime(job: dict[str, Any] | None) -> JarvisRuntime:
    runtime = JarvisRuntime.__new__(JarvisRuntime)
    runtime.store = _Store(job)
    runtime.agent = _agent()
    runtime.events = _Events()
    return runtime


def test_only_a_running_chat_job_takes_a_note() -> None:
    for job in (None, {"kind": "chat", "status": "completed"}, {"kind": "chat", "status": "queued"},
                {"kind": "transcribe_command", "status": "running"}):
        assert _runtime(job).steer_job("j", "더")["ok"] is False, job
    running = _runtime({"kind": "chat", "status": "running"})
    assert running.steer_job("j", "자동차로")["ok"] is True
    assert running.events.sent[0][0] == "agent_steer_received"


def test_a_finished_job_hands_back_notes_it_never_read() -> None:
    runtime = _runtime({"kind": "chat", "status": "running"})
    runtime.steer_job("j", "그리고 요금도")
    runtime._guard_job(lambda job: {"answer": "끝"}, {"id": "j", "kind": "chat"})
    assert ("agent_steer_leftover", {"job_id": "j", "texts": ["그리고 요금도"]}) in runtime.events.sent
