"""맡긴 코드 판은 사람의 요청에 자리를 비켜 준다 (2026-10-09).

맡긴 코드 판은 시간 제한 없이 끝까지 간다. 손자리는 한 번에 한 판이라, 그동안 사람이 창에서 시킨 일은 줄에서 기다린다 —
30분도 기다린다. 그래서 둘을 같이 넣는다: ① 줄에서는 사람 것이 먼저 나가고 ② 돌고 있는 맡긴 판은 걸음 사이에서 멈춘
자리를 저장하고 나갔다가, 사람 것이 끝나면 그 자리에서 이어 간다. 사람이 다시 시킬 필요가 없다.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.agent import BrowserAgent, _YIELD_CHECKPOINT_TTL_SEC
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobRunner, JobStatus, JobStore, YieldToPerson
from alture_jarvis.models import ToolResult

_CHECK = "python -m pytest -q tests/test_value.py"


def _delegated(store: JobStore, title: str = "맡긴 일") -> dict:
    return store.create_job("chat", title, {"prompt": "value.py 의 값을 고쳐줘", "origin": "mcp"})


def _from_a_person(store: JobStore, title: str = "사람이 시킨 일") -> dict:
    return store.create_job("chat", title, {"prompt": "안녕", "origin": "workspace"})


# ── 줄 ───────────────────────────────────────────────────────────────────────


def test_a_person_goes_before_a_delegated_job_that_was_queued_earlier(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    first = _delegated(store)
    time.sleep(0.01)
    person = _from_a_person(store)

    assert store.claim_next()["id"] == person["id"], "사람 것이 먼저 나간다"
    assert store.claim_next()["id"] == first["id"]
    assert store.claim_next() is None


def test_jobs_from_the_same_side_keep_their_order(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    made = []
    for build in (_delegated, _delegated, _from_a_person, _from_a_person):
        made.append(build(store)["id"])
        time.sleep(0.01)
    assert [store.claim_next()["id"] for _ in range(4)] == [made[2], made[3], made[0], made[1]]


def test_a_job_that_does_not_say_where_it_came_from_counts_as_a_persons(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    assert store.person_is_waiting() is False
    _delegated(store)
    assert store.person_is_waiting() is False, "맡긴 일끼리는 비켜 주지 않는다"
    store.create_job("chat", "출처 없음", {"prompt": "안녕"})
    assert store.person_is_waiting() is True


def test_only_a_running_job_is_put_back_in_line(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    job = _delegated(store)
    assert store.requeue_yielded(job["id"]) is False, "줄에 서 있는 것은 그대로다"
    store.claim_next()
    assert store.requeue_yielded(job["id"]) is True
    assert store.get_job(job["id"])["status"] == JobStatus.QUEUED.value
    store.claim_next()
    store.cancel(job["id"])
    assert store.requeue_yielded(job["id"]) is False, "그 사이 사람이 멈춘 판을 되살리지 않는다"


def test_the_runner_puts_the_yielding_job_back_and_runs_the_person_first(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    runner = JobRunner(store, EventBus(), poll_sec=0.02)
    order: list[str] = []
    delegated = _delegated(store)
    state = {"person": ""}

    def handler(job: dict[str, Any]) -> dict[str, Any]:
        order.append(str(job["title"]))
        if job["id"] == delegated["id"] and not state["person"]:
            state["person"] = _from_a_person(store)["id"]   # 맡긴 판이 도는 중에 사람이 시킨다
            raise YieldToPerson(job["id"])
        return {"answer": "끝"}

    runner.register("chat", handler)
    runner.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and store.get_job(delegated["id"])["status"] != JobStatus.COMPLETED.value:
            time.sleep(0.02)
    finally:
        runner.stop()

    assert order == ["맡긴 일", "사람이 시킨 일", "맡긴 일"]
    assert store.get_job(state["person"])["status"] == JobStatus.COMPLETED.value
    assert store.get_job(delegated["id"])["status"] == JobStatus.COMPLETED.value, "실패로 남지 않는다"
    assert not store.get_job(delegated["id"])["error"]


# ── 실제 판 ───────────────────────────────────────────────────────────────────

_TOOL_NAMES = {"local_read_text_file", "local_grep", "local_write_file", "local_apply_edit", "local_delete_file", "local_run_project_command"}


class _Tools:
    names = set(_TOOL_NAMES)
    ollama_tools = [
        {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}}}
        for name in sorted(_TOOL_NAMES)
    ]

    def authorize_code_workspace(self, job_id, root):  # noqa: ANN001, ANN201
        assert job_id and root


class _Gateway:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.checks = 0

    def execute(self, name, arguments, *, job_id=""):  # noqa: ANN001, ANN201
        target = self.root / "value.py"
        if name == "local_write_file":
            target.write_text(str(arguments.get("content") or ""), encoding="utf-8")
            return ToolResult(True, name, result={"action": name, "path": str(target), "verified": True, "created": True})
        if name == "local_run_project_command":
            self.checks += 1
            passed = target.is_file() and "fixed" in target.read_text(encoding="utf-8")
            return ToolResult(True, name, result={
                "action": name, "command": arguments.get("command"), "exit_code": 0 if passed else 1,
                "stdout": "1 passed" if passed else "1 failed", "verified": passed,
            })
        return ToolResult(True, name, result={"action": name, "text": "x"})


def _call(name: str, **arguments: Any) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class _AskedMidway:
    """첫 걸음을 하는 동안 사람이 창에서 다른 일을 시킨다. 되살아난 뒤에 고친다."""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.calls = 0
        self.person = ""
        self.seen_on_resume: list[dict] = []

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if self.calls == 1:
            self.person = _from_a_person(self.store)["id"]
            return _call("local_write_file", path="value.py", content="VALUE = 'broken'\n")
        if self.calls == 2:
            self.seen_on_resume = list(messages)
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
        return {"role": "assistant", "content": "고쳤습니다."}


def _agent(tmp_path: Path, store: JobStore, model) -> tuple[BrowserAgent, _Gateway]:  # noqa: ANN001
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False,
    )
    gateway = _Gateway(tmp_path)
    browser = SimpleNamespace(status=lambda: {"started": True})
    return BrowserAgent(config, model, gateway, browser, _Tools(), store, EventBus()), gateway


def _run(agent: BrowserAgent, job_id: str, tmp_path: Path, **extra: Any):  # noqa: ANN201
    return agent.run(
        "value.py 의 값을 고쳐줘", job_id=job_id, origin="mcp", model_role="code", code_mode=True,
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True, **extra,
    )


def test_a_delegated_job_steps_aside_between_steps_and_picks_up_where_it_stopped(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    model = _AskedMidway(store)
    agent, gateway = _agent(tmp_path, store, model)
    job = _delegated(store)
    store.claim_next()

    with pytest.raises(YieldToPerson):
        _run(agent, job["id"], tmp_path, declared_check=_CHECK)

    assert model.calls == 1, "걸음 하나를 마친 자리에서 나갔다 — 모델을 한 번 더 부르지 않는다"
    saved = store.get_agent_checkpoint(job["id"])
    assert saved and saved["steps"][-1]["tool"] == "local_write_file"
    done_before = [step["tool"] for step in saved["steps"]]
    assert saved["mission"].get("requirements") in ([], None), "과제 글에서 요구를 뽑지 않는 판이다 — 되살릴 때도 같다"
    assert gateway.checks == 0

    # 러너가 하는 일 그대로: 다시 줄에 세우고 → 사람 것이 먼저 → 그다음 이 판.
    assert store.requeue_yielded(job["id"]) is True
    assert store.claim_next()["id"] == model.person
    store.set_status(model.person, JobStatus.COMPLETED, result={"answer": "안녕하세요"})
    assert store.claim_next()["id"] == job["id"]

    result = _run(agent, job["id"], tmp_path, declared_check=_CHECK)

    tools = [step["tool"] for step in result.steps]
    assert tools[:len(done_before)] == done_before, "앞 걸음을 이어받았다 — 처음부터 다시 돌지 않는다"
    assert tools.count("local_write_file") == 2
    assert any("broken" in str(message.get("content") or "") or message.get("tool_calls") for message in model.seen_on_resume)
    assert result.verification["declared_check"]["passed"] is True
    assert result.verification["completion_state"] == "complete"
    assert "fixed" in (tmp_path / "value.py").read_text(encoding="utf-8")


def test_it_does_not_step_aside_before_it_has_done_anything_this_turn(tmp_path: Path) -> None:
    """방금 줄에서 나온 판이 한 걸음도 안 가고 다시 비키면 둘이 서로 양보만 한다."""
    store = JobStore(tmp_path / "jarvis.db")

    class _Fixes:
        calls = 0

        def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
            self.calls += 1
            if self.calls == 1:
                return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
            return {"role": "assistant", "content": "고쳤습니다."}

    model = _Fixes()
    agent, _ = _agent(tmp_path, store, model)
    job = _delegated(store)
    store.claim_next()
    _from_a_person(store)   # 시작하기 전부터 사람 것이 서 있다

    with pytest.raises(YieldToPerson):
        _run(agent, job["id"], tmp_path, declared_check=_CHECK)
    assert model.calls == 1, "한 걸음은 가고 비킨다"


def test_a_job_a_person_started_never_steps_aside(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    model = _AskedMidway(store)
    agent, _ = _agent(tmp_path, store, model)
    job = _from_a_person(store, "사람이 시킨 코드 일")
    store.claim_next()

    result = _run(agent, job["id"], tmp_path)   # 확인 명령이 없는 판

    assert model.calls >= 2 and result is not None
    assert store.get_agent_checkpoint(job["id"]) is None


def test_the_saved_place_outlives_a_long_job_of_the_person() -> None:
    assert _YIELD_CHECKPOINT_TTL_SEC >= 2 * 3600, "기본 30분이면 사람의 긴 일 하나에 사라져 처음부터 다시 돈다"
