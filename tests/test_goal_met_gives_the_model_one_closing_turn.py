"""바닥선(계획)을 채우면 **모델에게 마무리를 한 번** 맡긴다 — 끝은 모델이 정하고 하네스는 상한만 쥔다 (2026-10-02 운영 판 657fdd09).

「Ornith 가 아파치 모델을 튜닝하는지 조사」 판: 계획은 「근거 1개 읽기」뿐이라 11번째 걸음에서 채워졌고, 덧붙인 말(오니스 → Ornith)대로
Ornith 사이트를 막 연 순간 걸음 상한에서 「목표 달성」으로 닫혔다. 글로만 쓰는 정리에서 모델은 「본문과 GitHub를 읽어 실체를
확인하겠습니다」라고 답했다. 운영 156판 중 정리 답이 예고였던 건 8판(5%) — 늘 더 주지 않고, 정리를 모델의 답 한 번으로 바꾼다.
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.agent import _GOAL_MET_CLOSING_STEPS, BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

from test_agent import FakeBrowser

PROMPT = "Ornith가 오픈소스 아파치 라이선스 모델들을 잘 튜닝한다는데 그게 맞는지 조사해주라"
CLOSING = "시킨 것의 최소 요구는 다 채웠다"
SYNTHESIS = "계획에서 확인 가능한 목표를 모두 채웠다"
ANSWER = "확인 결과: Ornith 1.5 는 Qwen 기반 Apache-2.0 모델을 튜닝해 공개했습니다(ornith.ai · GitHub 확인)."


class _ReadTools:
    names = {"browser_read"}
    ollama_tools = [{"type": "function", "function": {
        "name": "browser_read", "description": "read",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}}]


class _ReadGateway:
    def __init__(self) -> None:
        self.reads: list[str] = []

    def execute(self, name, arguments, *, job_id=""):
        url = str(arguments["url"])
        self.reads.append(url)
        return ToolResult(True, name, result={"action": "read", "url": url, "title": url.rsplit("/", 1)[-1],
                                              "char_count": 3000, "text": f"{url} 본문 " * 40})


class _KeepsCheckingUntilTold:
    """요구를 채운 뒤에도 덧붙인 말대로 계속 확인한다. 마무리 안내를 받으면 한 번 더 읽고 답한다.
    글만 쓰는 정리 단계로 끌려가면 운영 판처럼 「확인하겠습니다」 예고만 한다."""

    def __init__(self) -> None:
        self.calls = 0
        self.after_closing = 0

    def chat_messages(self, messages, **kwargs) -> dict[str, Any]:
        self.calls += 1
        # 하네스 안내는 바로 앞 도구 결과 끝에 이어 붙어 온다(`transcript.attach_system_notes`) — 어느 메시지든 본다.
        told = any(CLOSING in str(m.get("content") or "") for m in messages)
        recent = " ".join(str(m.get("content") or "") for m in messages[-3:])
        if SYNTHESIS in recent or "방금 말은 다음 걸음 예고" in recent:
            return {"role": "assistant", "content": "Ornith AI 공식 사이트가 열렸습니다. 본문과 GitHub를 읽어 실체를 확인하겠습니다."}
        if told:
            self.after_closing += 1
            if self.after_closing == 1:
                return self._read("https://github.com/ornith-ai/ornith")
            return {"role": "assistant", "content": ANSWER}
        return self._read(f"https://example.com/page/{self.calls}")

    @staticmethod
    def _read(url: str) -> dict[str, Any]:
        return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_read", "arguments": {"url": url}}}]}


def _run(tmp_path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    model, gateway = _KeepsCheckingUntilTold(), _ReadGateway()
    agent = BrowserAgent(config, model, gateway, FakeBrowser(), _ReadTools(), store, EventBus())
    job = store.create_job("chat", "agent", {"prompt": PROMPT})
    store.claim_next()
    return model, gateway, agent.run(PROMPT, job_id=job["id"], origin="chat", must_observe=True,
                                     observe_reasons=frozenset({"web"}))


def test_the_model_finishes_its_check_and_answers(tmp_path) -> None:
    model, gateway, result = _run(tmp_path)
    assert model.after_closing >= 1, "목표를 채운 경계에서 모델에게 마무리를 맡겼다"
    assert "https://github.com/ornith-ai/ornith" in gateway.reads, "꼭 마칠 확인 한 걸음을 했다"
    assert result.answer.startswith("확인 결과"), result.answer
    assert "예고만 하고 멈췄습니다" not in result.answer


def test_the_closing_turn_is_bounded(tmp_path) -> None:
    _model, gateway, _result = _run(tmp_path)
    after = gateway.reads[gateway.reads.index("https://github.com/ornith-ai/ornith"):]
    assert len(after) <= _GOAL_MET_CLOSING_STEPS
