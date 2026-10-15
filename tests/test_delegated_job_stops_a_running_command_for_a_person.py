"""맡긴 판이 긴 명령을 돌리는 **도중에** 사람이 오면 그 명령을 끊고 비켜 준다 — 판 전체로 본다 (2026-10-10).

2026-10-09 밤의 실제 판에서 사람의 요청이 206초를 기다렸다(맡긴 판이 3분짜리 전체 시험을 돌리는 중). 명령을 끊는 쪽의
시험은 `test_commands_stop_for_a_person.py` 에 있다. 여기서는 그 끊김이 판의 대화를 깨지 않고 평소의 비켜 주기로
이어지는지, 돌아와서 그 명령을 다시 돌려 끝내는지를 본다.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from alture_jarvis import local_computer
from alture_jarvis.jobs import JobStatus, JobStore, YieldToPerson
from alture_jarvis.local_computer import run_captured
from alture_jarvis.models import ToolResult

from test_delegated_job_yields_to_a_person_1009 import _CHECK, _agent, _call, _delegated, _from_a_person, _run


class _SlowCheckGateway:
    """확인 명령이 **진짜 프로세스**로 오래 돈다. 도는 동안 사람이 창에서 다른 일을 시킨다."""

    def __init__(self, root: Path, store: JobStore) -> None:
        self.root = root
        self.store = store
        self.checks = 0
        self.person = ""

    def execute(self, name, arguments, *, job_id=""):  # noqa: ANN001, ANN201
        target = self.root / "value.py"
        if name == "local_write_file":
            target.write_text(str(arguments.get("content") or ""), encoding="utf-8")
            return ToolResult(True, name, result={"action": name, "path": str(target), "verified": True, "created": True})
        if name == "local_run_project_command":
            self.checks += 1
            if not self.person:
                self.person = _from_a_person(self.store)["id"]   # 명령이 막 돌기 시작한 때에 사람이 온다
                script = "import time; time.sleep(120); print('1 passed')"
            else:
                script = "print('1 passed')"
            code, out, _err, timed_out = run_captured(
                [sys.executable, "-c", script], cwd=str(self.root), env=None, timeout_sec=150,
            )
            passed = code == 0 and b"1 passed" in out
            return ToolResult(True, name, result={
                "action": name, "command": arguments.get("command"), "exit_code": code,
                "stdout": out.decode("utf-8", "replace"), "verified": passed, "timed_out": timed_out,
            })
        return ToolResult(True, name, result={"action": name, "text": "x"})


class _FixesThenAnswers:
    def __init__(self) -> None:
        self.calls = 0
        self.seen: list[list[dict]] = []

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        self.seen.append(list(messages))
        if self.calls == 1:
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
        return {"role": "assistant", "content": "고쳤습니다."}


def test_a_command_in_flight_is_stopped_and_the_job_comes_back_to_finish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_computer, "_STOP_POLL_SEC", 0.3)
    store = JobStore(tmp_path / "jarvis.db")
    model = _FixesThenAnswers()
    agent, _ = _agent(tmp_path, store, model)
    gateway = _SlowCheckGateway(tmp_path, store)
    agent.gateway = gateway
    job = _delegated(store)
    store.claim_next()

    started = time.monotonic()
    with pytest.raises(YieldToPerson):
        _run(agent, job["id"], tmp_path, declared_check=_CHECK)
    waited = time.monotonic() - started

    assert waited < 40, f"120초짜리 명령이 다 돌 때까지 사람을 기다리게 했다({waited:.0f}초)"
    assert gateway.checks == 1
    saved = store.get_agent_checkpoint(job["id"])
    last = saved["steps"][-1]
    assert last["tool"] == "local_run_project_command" and not last["ok"]
    assert last["error"] == "stopped_for_a_person", "실패나 시간 초과가 아니라 「끊었다」로 적힌다"
    # 대화는 호출과 결과의 짝이 맞은 채로 남는다 — 되살릴 때 결과 없는 호출이 있으면 대화 틀이 깨진다.
    tail = saved["messages"][-1]
    assert tail.get("role") == "tool" and "도는 중에 끊었다" in str(tail.get("content"))
    events = [row["event"] if isinstance(row, dict) else row for row in store.list_audit(job_id=job["id"])] if hasattr(store, "list_audit") else []
    assert not events or "agent_command_stopped_for_person" in events

    # 러너가 하는 일 그대로: 다시 줄에 세우고 → 사람 것이 먼저 → 그다음 이 판.
    assert store.requeue_yielded(job["id"]) is True
    assert store.claim_next()["id"] == gateway.person
    store.set_status(gateway.person, JobStatus.COMPLETED, result={"answer": "안녕하세요"})
    assert store.claim_next()["id"] == job["id"]

    result = _run(agent, job["id"], tmp_path, declared_check=_CHECK)

    assert any("도는 중에 끊었다" in str(m.get("content") or "") for m in model.seen[-1]), "되살아난 모델이 끊긴 까닭을 본다"
    assert gateway.checks == 2, "끊긴 확인을 다시 돌렸다"
    assert result.verification["declared_check"]["passed"] is True
    assert result.verification["completion_state"] == "complete"


def test_a_job_a_person_started_does_not_listen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """사람이 직접 시킨 판의 명령은 끊지 않는다 — 귀는 비켜 줄 판에만 달린다."""
    monkeypatch.setattr(local_computer, "_STOP_POLL_SEC", 0.2)
    store = JobStore(tmp_path / "jarvis.db")
    agent, _ = _agent(tmp_path, store, _FixesThenAnswers())
    heard: list[bool] = []

    class _Gateway:
        def execute(self, name, arguments, *, job_id=""):  # noqa: ANN001, ANN201
            heard.append(getattr(local_computer._STOP, "check", None) is not None)
            return ToolResult(True, name, result={"action": name, "path": "value.py", "verified": True, "created": True})

    agent.gateway = _Gateway()
    job = _from_a_person(store, "사람이 시킨 코드 일")
    store.claim_next()
    _from_a_person(store, "그 사이 또 시킨 일")
    _run(agent, job["id"], tmp_path)
    assert heard and not any(heard)
