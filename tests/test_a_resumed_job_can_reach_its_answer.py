"""체크포인트에서 이어받은 판이 **답을 내는 자리까지 간다** (2026-09-21, 노트북 4B 기준선에서 드러남).

## 어떻게 찾았나

노트북(Qwen 3.5 4B)으로 코딩 사다리 6과제를 돌렸더니 둘이 이렇게 죽었다:

    L1_hello_page   failed  cannot access local variable 'observe_pushbacks' where it is not associated with a value
    L4_add_feature  failed  (같은 오류)   ← **작업 결과는 정답이었는데** 잡이 이 예외로 실패 처리됐다

`observe_pushbacks` 는 **새 판 가지**에서만 0 으로 만들고, **체크포인트에서 이어받는 가지**에는 없었다.
그 변수는 `must_observe` 인 판이 **답을 내려는 순간** 읽는다 — 그래서 이어받은 판은 일을 다 해 놓고 마지막
한 걸음에서 죽는다. 같은 파일의 주석(5155행 근처)이 이미 「이어받기에서만 UnboundLocalError」를 경고하고 있었는데
이 변수만 빠졌다.

## 왜 큰 사고인가

기본 권한 모드가 `ask` 라 Code 모드에서 승인 카드가 한 번이라도 뜬 판은 **승인을 기다리는 동안 체크포인트로
멈췄다가, 승인 뒤 이어받기 가지로 재개된다.** 즉 승인 카드를 누른 Code 판은 전부 이 길을 탔다.
「새 판만 시험하면 안 보이는 고장이다」(주석 그대로) — 그래서 이어받은 판을 **실제로 돌려** 검증한다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult


class _Tools:
    names = {"local_read_text_file", "local_write_file", "local_run_project_command"}
    ollama_tools = [
        {"type": "function", "function": {"name": name, "description": name,
                                          "parameters": {"type": "object", "properties": {}}}}
        for name in sorted(names)
    ]

    def authorize_code_workspace(self, job_id, root):
        assert job_id and root


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):
        return ToolResult(True, name, result={"action": name, "verified": True, "path": "x.py", "text": "ok"})


class _Browser:
    def status(self):
        return {"started": True}


class _Model:
    """이어받은 판에서 곧바로 답을 낸다 — 답을 내는 순간이 문제의 자리다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        return {"role": "assistant", "content": "이어서 확인했고 끝냈습니다."}


def _resumed_agent(tmp_path: Path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, agent_stream_enabled=False)
    store = JobStore(tmp_path / "jarvis.db")
    model = _Model()
    agent = BrowserAgent(config, model, _Gateway(), _Browser(), _Tools(), store, EventBus())
    job = store.create_job("chat", "이어받기", {"prompt": "x.py 를 고쳐줘"})
    store.claim_next()
    # 승인을 기다리다 멈춘 판이 남기는 체크포인트의 최소 모양
    store.save_agent_checkpoint(job["id"], {
        "prompt": "x.py 를 고쳐줘", "origin": "chat",
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "x.py 를 고쳐줘"}],
        "steps": [{"step": 1, "tool": "local_write_file", "ok": True,
                   "arguments": {"path": "x.py"}, "evidence": {"verified": True}}],
        "fingerprints": {}, "evidence_urls": [], "last_action_ids": {},
        "elapsed_before_sec": 1.0, "thinking_chars": 0, "continuation_count": 0,
        "lease_sec": 180, "resume_reason": "approval_cleared",
    })
    return agent, model, job


def test_a_job_resumed_from_a_checkpoint_reaches_its_answer_under_must_observe(tmp_path) -> None:
    """`must_observe` 인 이어받은 판이 답을 내려는 순간 `UnboundLocalError` 로 죽으면 안 된다."""
    agent, model, job = _resumed_agent(tmp_path)

    result = agent.run(
        "x.py 를 고쳐줘", job_id=job["id"], origin="chat", model_role="code",
        must_observe=True, required_local_root=str(tmp_path), auto_continue_budget=True,
    )

    assert model.calls >= 1
    assert result.answer or result.steps, "이어받은 판이 아무것도 못 냈다"


def test_the_resume_branch_initializes_every_counter_the_fresh_branch_does() -> None:
    """같은 종류의 고장을 다시 못 만들게 한다 — 새 판 가지에서 0 으로 만드는 카운터는 이어받는 가지에도 있어야 한다.

    새 판만 시험하면 안 보이는 고장이라서, 두 가지의 초기화 목록을 **소스에서 직접 비교**한다.
    """
    import inspect
    import re

    source = inspect.getsource(BrowserAgent.run)
    resume = source[source.index("if checkpoint:"): source.index("        else:\n            # ★ 이어 붙인 뒤 뭉텅")]
    fresh_start = source.index("            steps = []\n            # 도구가 필드로 준 숫자")
    fresh = source[fresh_start: fresh_start + 2500]

    counters = re.findall(r"^\s+(\w*(?:pushbacks|nudges|count))\s*=\s*0\s*$", fresh, re.M)
    assert "observe_pushbacks" in counters and "nudges" in counters, counters
    missing = [name for name in counters if not re.search(rf"^\s+{name}\s*=", resume, re.M)]
    assert not missing, f"이어받는 가지에 초기화가 없다: {missing}"
