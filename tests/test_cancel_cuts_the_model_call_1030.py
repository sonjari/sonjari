"""취소된 판은 모델 부르기 **도중에** 끊는다 (2026-10-30 16GB 출시 문 시험).

넘친 카드(그래픽카드 몫 0.71)에서 한 걸음 생각이 7,106토큰 · 약 19분 걸렸다. 10분에 취소했지만 그 부르기는 14:54:10 까지
돌며 일꾼을 쥐었고, 다음 판(grep)은 시작도 못 했다. 걸음 사이에서만 취소를 보던 것이 뿌리.
사람이 시킨 판이든 맡긴 판이든 똑같이 끊는다 — 취소는 사람이 누른 것이다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import AgentCancelled, BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStatus, JobStore
from alture_jarvis.models import ToolResult

_TOOL_NAMES = {"local_read_text_file", "local_grep", "local_write_file", "local_apply_edit", "local_run_project_command"}


class _Tools:
    names = set(_TOOL_NAMES)
    ollama_tools = [
        {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}}}
        for name in sorted(_TOOL_NAMES)
    ]

    def authorize_code_workspace(self, job_id, root):  # noqa: ANN001, ANN201
        assert job_id and root


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):  # noqa: ANN001, ANN201
        return ToolResult(True, name, result={"action": name, "text": "x"})


class _ThinksAndGetsCancelled:
    """첫 걸음에서 길게 생각한다. 다섯째 조각에서 누군가 이 판을 취소한다."""

    def __init__(self, store: JobStore, job_id: str, *, cancel: bool = True) -> None:
        self.store, self.job_id, self.cancel = store, job_id, cancel
        self.chunks = 0
        self.calls = 0

    def chat_messages_stream(self, messages, *, on_chunk=None, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if self.calls > 1:
            return {"role": "assistant", "content": "다 봤습니다."}
        for index in range(60):
            if index == 5 and self.cancel:
                self.store.set_status(self.job_id, JobStatus.CANCELLED)
            self.chunks += 1
            on_chunk({"thinking": f"생각 {index} ", "content": "", "tool_calls": [], "done": False})
        return {"role": "assistant", "content": "다 봤습니다."}


def _agent(tmp_path: Path, store: JobStore, model) -> BrowserAgent:  # noqa: ANN001
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=True,
    )
    return BrowserAgent(config, model, _Gateway(), SimpleNamespace(status=lambda: {"started": True}), _Tools(), store, EventBus())


@pytest.fixture(autouse=True)
def _look_at_every_chunk(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(agent_module, "_YIELD_POLL_SEC", 0.0)


@pytest.mark.parametrize("origin", ["workspace", "mcp"])
def test_cancel_cuts_a_long_thought_in_the_middle(tmp_path: Path, origin: str) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    job = store.create_job("chat", "코드 일", {"prompt": "봐 줘", "origin": origin})
    store.claim_next()
    model = _ThinksAndGetsCancelled(store, job["id"])

    with pytest.raises(AgentCancelled):
        _agent(tmp_path, store, model).run(
            "value.py 를 봐 줘", job_id=job["id"], origin=origin, model_role="code", code_mode=True,
            require_sandbox=True, required_local_root=str(tmp_path),
        )

    assert model.chunks <= 7, f"취소 뒤에도 생각을 {model.chunks}조각까지 받았다 — 도중에 끊어야 일꾼이 풀린다"


def test_without_cancel_the_long_thought_runs_to_its_end(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    job = store.create_job("chat", "코드 일", {"prompt": "봐 줘", "origin": "workspace"})
    store.claim_next()
    model = _ThinksAndGetsCancelled(store, job["id"], cancel=False)

    _agent(tmp_path, store, model).run(
        "value.py 를 봐 줘", job_id=job["id"], origin="workspace", model_role="code", code_mode=True,
        require_sandbox=True, required_local_root=str(tmp_path),
    )

    assert model.chunks == 60
