"""빈 채로 멈추면 **판 안에서 한 번 정리시킨다.**

## 왜 (2026-09-12 n=3 벤치)

두 판이 이렇게 끝났다 — 공고를 다 읽고, 걸음도 남고(11/18 · 12/20), 파일만 없다.
장부에 남은 것은 이것뿐이었다:

    artifact_fallback = answer_too_short:0/200 · 되받기 0회

되받기 때문이 아니었다. **모델이 판 안에서 글자를 한 번도 안 냈다.** 표는 판이
끝난 뒤 「정리」 단계가 썼다. 안전망은 판 안에 살고 답은 판 밖에서 태어나므로,
안전망은 평생 빈 문자열만 보고 물러났다.

젬마 4 는 thinking 모델이라 근거가 길면 예산(`num_predict`)을 내부 추론에 다 쓰고
`content` 가 빈다. 판 **밖에는** 이미 그 대비가 있었는데(「정리가 비어서 다시
씁니다」) 판 **안에는** 없었다.
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

from test_agent import FakeBrowser

PROMPT = "사람인에서 여수 회계 공고 2개를 조사해서 문서로 정리해줘"

TABLE = """# 여수 회계 채용 공고 조사 결과

| 회사명 | 고용형태 |
| :--- | :--- |
| 공고 1 | 정규직 |
| 공고 2 | 정규직 |
"""


class _ReadTools:
    names = {"browser_read"}
    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": "browser_read",
                "description": "read",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                },
            },
        }
    ]


class _ReadGateway:
    def execute(self, name, arguments, *, job_id=""):
        index = int(str(arguments["url"]).rsplit("/", 1)[-1])
        return ToolResult(
            True,
            name,
            result={
                "action": "read",
                "url": f"https://www.saramin.co.kr/jobs/{index}",
                "title": f"정규직 공고 {index}",
                "char_count": 12000 + index,
                "text": f"정규직 공고 {index} 본문",
            },
        )


class _ReadsThenGoesSilent:
    """두 곳을 읽고 **빈 메시지**로 멈춘다. 생각을 끄고 물으면 표를 쓴다."""

    def __init__(self) -> None:
        self.calls = 0
        self.thinking_off_calls = 0
        self.last_turn_before_synthesis: dict[str, Any] = {}

    def chat_messages(self, messages, **kwargs) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= 2:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "browser_read",
                            "arguments": {
                                "url": f"https://www.saramin.co.kr/jobs/{self.calls}"
                            },
                        }
                    }
                ],
            }
        if kwargs.get("think") is False:
            self.thinking_off_calls += 1
            if not self.last_turn_before_synthesis:
                self.last_turn_before_synthesis = dict(messages[-1])
            return {"role": "assistant", "content": TABLE}
        # 생각이 켜져 있으면 예산을 추론에 다 써서 빈 답이 온다(실제 젬마의 모습).
        return {"role": "assistant", "content": ""}


def _run(tmp_path):
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    model = _ReadsThenGoesSilent()
    agent = BrowserAgent(
        config, model, _ReadGateway(), FakeBrowser(), _ReadTools(), store, EventBus()
    )
    job = store.create_job("chat", "agent", {"prompt": PROMPT})
    store.claim_next()
    result = agent.run(PROMPT, job_id=job["id"], origin="chat")
    return model, result


def test_a_silent_model_is_asked_once_more_with_thinking_off(tmp_path) -> None:
    model, result = _run(tmp_path)
    assert model.thinking_off_calls >= 1
    # 정리시킨 답이 판 안으로 들어와야 안전망이 볼 것이 생긴다.
    assert "공고 1" in result.answer


def test_the_ledger_no_longer_says_the_answer_was_too_short(tmp_path) -> None:
    """`answer_too_short:0/200` 은 「모델이 안 냈다」가 아니라 「우리가 안 물었다」였다."""
    _model, result = _run(tmp_path)
    assert result.verification.get("artifact_fallback") != "answer_too_short:0/200"

def test_the_silent_model_is_given_an_instruction_not_its_own_empty_reply(tmp_path) -> None:
    """첫 판에서는 모델의 **빈 메시지**를 붙여 불러서 셋 중 셋이 또 비었다.

    마지막 차례가 자기의 빈 답이면 모델은 할 말이 끝난 대화로 읽는다. 판 밖 정리는
    처음부터 지시를 붙여 불렀고 그쪽은 나왔다 — 같은 방식이어야 한다.
    """
    model, _result = _run(tmp_path)
    last = model.last_turn_before_synthesis
    # 2026-09-29: `[시스템]` 지시는 바로 앞 도구 결과에 붙어 간다(transcript.attach_system_notes — 캐시).
    #   지켜야 할 것은 역할 이름이 아니라 「마지막 차례가 모델 자신의 빈 답이 아니라 지시다」.
    assert last.get("role") in {"user", "tool"}
    assert "최종 답" in str(last.get("content"))
