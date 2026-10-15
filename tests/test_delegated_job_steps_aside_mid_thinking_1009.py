"""맡긴 판은 모델이 **생각을 흘려보내는 도중에도** 사람에게 비켜 준다 (2026-10-09 저녁 · 대표 결정).

걸음 사이에서만 비키면 모델이 길게 생각하는 동안 사람이 기다린다 — 그날 실제 판에서 38초였다.
끊긴 생각은 버린다. 되살아난 판이 그 걸음을 다시 생각한다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStatus, JobStore, YieldToPerson
from alture_jarvis.models import ToolResult

_CHECK = "python -m pytest -q tests/test_value.py"
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

    def execute(self, name, arguments, *, job_id=""):  # noqa: ANN001, ANN201
        target = self.root / "value.py"
        if name == "local_write_file":
            target.write_text(str(arguments.get("content") or ""), encoding="utf-8")
            return ToolResult(True, name, result={"action": name, "path": str(target), "verified": True, "created": True})
        if name == "local_run_project_command":
            passed = target.is_file() and "fixed" in target.read_text(encoding="utf-8")
            return ToolResult(True, name, result={
                "action": name, "command": arguments.get("command"), "exit_code": 0 if passed else 1,
                "stdout": "1 passed" if passed else "1 failed", "verified": passed,
            })
        return ToolResult(True, name, result={"action": name, "text": "x"})


def _write(content: str) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "local_write_file", "arguments": {"path": "value.py", "content": content}}}]}


class _ThinksForALongTime:
    """첫 걸음은 바로 낸다. 둘째 걸음에서 오래 생각한다 — 그 사이 사람이 창에서 다른 일을 시킨다."""

    def __init__(self, store: JobStore, *, someone_asks: bool = True) -> None:
        self.store = store
        self.someone_asks = someone_asks
        self.calls = 0
        self.chunks_in_the_long_turn = 0
        self.person = ""

    def chat_messages_stream(self, messages, *, on_chunk=None, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if self.calls == 1:
            return _write("VALUE = 'broken'\n")
        if self.calls == 2:
            for index in range(40):
                if index == 3 and self.someone_asks:
                    self.person = self.store.create_job("chat", "사람이 시킨 일", {"prompt": "안녕", "origin": "workspace"})["id"]
                self.chunks_in_the_long_turn += 1
                on_chunk({"thinking": f"생각 {index} ", "content": "", "tool_calls": [], "done": False})
            return _write("VALUE = 'fixed'\n")
        if self.calls == 3 and not self.someone_asks:
            return {"role": "assistant", "content": "고쳤습니다."}
        if self.calls == 3:
            return _write("VALUE = 'fixed'\n")
        return {"role": "assistant", "content": "고쳤습니다."}


def _agent(tmp_path: Path, store: JobStore, model) -> BrowserAgent:  # noqa: ANN001
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=True,
    )
    browser = SimpleNamespace(status=lambda: {"started": True})
    return BrowserAgent(config, model, _Gateway(tmp_path), browser, _Tools(), store, EventBus())


def _run(agent: BrowserAgent, job_id: str, tmp_path: Path, **extra: Any):  # noqa: ANN201
    return agent.run(
        "value.py 의 값을 고쳐줘", job_id=job_id, origin="mcp", model_role="code", code_mode=True,
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True, **extra,
    )


@pytest.fixture(autouse=True)
def _look_at_the_line_on_every_chunk(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(agent_module, "_YIELD_POLL_SEC", 0.0)


def test_it_steps_aside_while_the_model_is_still_thinking(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    model = _ThinksForALongTime(store)
    agent = _agent(tmp_path, store, model)
    job = store.create_job("chat", "맡긴 일", {"prompt": "고쳐줘", "origin": "mcp"})
    store.claim_next()

    with pytest.raises(YieldToPerson):
        _run(agent, job["id"], tmp_path, declared_check=_CHECK)

    assert model.calls == 2
    assert model.chunks_in_the_long_turn <= 6, f"생각이 끝날 때까지 기다렸다({model.chunks_in_the_long_turn}조각) — 도중에 끊어야 한다"
    saved = store.get_agent_checkpoint(job["id"])
    assert saved and saved["steps"][-1]["tool"] == "local_write_file", "끝난 걸음까지가 저장된다"
    assert "broken" in (tmp_path / "value.py").read_text(encoding="utf-8"), "끊긴 걸음은 아무것도 바꾸지 않았다"
    audits = [row for row in getattr(store, "list_audit", lambda **_: [])(limit=20)] if hasattr(store, "list_audit") else []
    assert all(row.get("event") != "agent_yielded_to_person" or "mid_turn" in str(row) for row in audits)

    # 사람 것이 먼저 돌고, 그 뒤에 멈춘 자리에서 이어 간다.
    assert store.requeue_yielded(job["id"]) is True
    assert store.claim_next()["id"] == model.person
    store.set_status(model.person, JobStatus.COMPLETED, result={"answer": "안녕하세요"})
    assert store.claim_next()["id"] == job["id"]
    result = _run(agent, job["id"], tmp_path, declared_check=_CHECK)
    assert result.verification["declared_check"]["passed"] is True
    assert "fixed" in (tmp_path / "value.py").read_text(encoding="utf-8")


def test_with_no_one_waiting_the_long_thought_runs_to_its_end(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    model = _ThinksForALongTime(store, someone_asks=False)
    agent = _agent(tmp_path, store, model)
    job = store.create_job("chat", "맡긴 일", {"prompt": "고쳐줘", "origin": "mcp"})
    store.claim_next()

    result = _run(agent, job["id"], tmp_path, declared_check=_CHECK)

    assert model.chunks_in_the_long_turn == 40
    assert result.verification["declared_check"]["passed"] is True


def test_a_job_a_person_started_is_never_cut_mid_thought(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    model = _ThinksForALongTime(store)
    agent = _agent(tmp_path, store, model)
    job = store.create_job("chat", "사람이 시킨 코드 일", {"prompt": "고쳐줘", "origin": "workspace"})
    store.claim_next()

    _run(agent, job["id"], tmp_path)   # 확인 명령이 없는 판

    assert model.chunks_in_the_long_turn == 40, "사람의 판은 다른 사람의 일이 줄에 서도 끝까지 생각한다"
