"""가로채기가 **실제로 도구를 바꿔 부르는가**, 그리고 그 사실이 **기록에 남는가**.

`test_site_first_beats_search_engine.py` 는 판정(`site_first_target`)만 본다. 이쪽은
판을 통째로 돌려 **배선**을 본다. 둘 다 필요하다 — 판정이 맞아도 배선이 틀리면
아무 일도 안 일어나고, 그 고장은 조용하다.

## 왜 이 시험이 생겼나 (2026-08-14)

돌리는 코드를 넣고 라이브로 두 판을 돌렸더니 다나와가 깨끗하게 통과했다. 그런데
"정말 내 코드가 한 것인가"를 확인하려고 스텝을 뒤졌더니 **아무 흔적도 없었다.**
하마터면 "발동 안 했다 — 우연이었다"는 반대 결론을 낼 뻔했다.

진짜 원인은 **중첩 위치**였다. 설명을 `observation["instruction"]` 에 붙였는데,
모델이 보는 것도 스텝에 남는 것도 전부 `observation["result"]` 에서 나온다
(`_record_observation`). 그래서 설명이 **모델에게도 안 가고 기록에도 안 남았다.**
돌리기 자체는 멀쩡히 동작했으니 겉으로는 성공으로 보였다 — 조용히 반쪽만 일한 것이다.

첫 인자가 `https://danawa.com/`(www 없는 맨 도메인 + 슬래시)인 것으로 겨우 갈라냈다.
모델 자기 버릇은 `https://www.coupang.com` 이다. **그런 식으로 구별해야 하는 상태를
남기면 안 된다.**
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult


class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names = {"browser_search", "browser_open", "browser_site_search"}
    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": "browser_search",
                "description": "search",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


class _RecordingGateway:
    """무엇이 **실제로** 불렸는지 적어 둔다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name, arguments, *, job_id=""):
        self.calls.append((name, dict(arguments)))
        return ToolResult(
            True,
            name,
            result={
                "url": "https://danawa.com/",
                "title": "비교하고 잘 사는, 다나와",
                "action": "opened",
            },
        )


class _SearchesTheWebFirst:
    """지목받은 사이트를 두고 검색엔진부터 부르는 모델. 라이브에서 실제로 그랬다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "browser_search",
                            "arguments": {"query": "다나와 무선마우스"},
                        }
                    }
                ],
            }
        return {"role": "assistant", "content": "다나와에서 확인한 결과입니다."}


def _agent(tmp_path):
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _RecordingGateway()
    agent = BrowserAgent(
        config, _SearchesTheWebFirst(), gateway, _Browser(), _Tools(), store, EventBus()
    )
    # 다나와를 아는 상태로 만든다(서로 다른 2 장·단일 도메인 — 진짜 학습 조건).
    agent.atlas.learn("다나와", "https://prod.danawa.com/info/?pcode=1", "다나와 (가격비교)")
    agent.atlas.learn("다나와", "https://search.danawa.com/dsearch.php?query=x", "다나와 (가격비교)")
    return agent, store, gateway


def test_the_search_call_is_actually_swapped_for_the_site(tmp_path) -> None:
    agent, store, gateway = _agent(tmp_path)
    job = store.create_job("chat", "agent", {"prompt": "다나와에서 무선마우스 상위 3개 알려줘"})
    store.claim_next()

    agent.run("다나와에서 무선마우스 상위 3개 알려줘", job_id=job["id"], origin="chat")

    assert gateway.calls, "도구가 한 번도 안 불렸다"
    name, arguments = gateway.calls[0]
    assert name == "browser_open", f"검색엔진으로 그냥 나갔다: {name}"
    assert arguments.get("url") == "https://danawa.com/"


def test_the_redirect_leaves_a_trace(tmp_path) -> None:
    """돌렸다는 사실이 **기록에 남아야** 한다.

    안 남으면 나중에 "이게 우리 코드가 한 것인가"를 물을 수 없다. 실제로 그 상태로
    라이브 2판을 돌리고 발동 여부를 못 가려 반대 결론을 낼 뻔했다.
    """
    agent, store, _ = _agent(tmp_path)
    job = store.create_job("chat", "agent", {"prompt": "다나와에서 무선마우스 상위 3개 알려줘"})
    store.claim_next()

    result = agent.run("다나와에서 무선마우스 상위 3개 알려줘", job_id=job["id"], origin="chat")

    evidence = result.steps[0]["evidence"]
    assert evidence.get("site_first_redirect") is True, f"흔적이 없다: {evidence}"
    assert "다나와" in str(evidence.get("instruction") or ""), (
        "왜 여기로 왔는지 모델에게 안 알려 준다 — 결과에서 모델이 읽는 자리는 "
        f"result 안이다: {evidence}"
    )


class _OpensAnotherSiteFirst(_SearchesTheWebFirst):
    """검색을 거치지 않고 **다른 사이트를 곧장** 여는 모델 (2026-09-24 노트북 4B: 「사람인에서」에 잡코리아부터)."""

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "browser_open", "arguments": {"url": "https://www.enuri.com/"}}}],
            }
        return {"role": "assistant", "content": "다나와에서 확인한 결과입니다."}


def test_opening_another_site_directly_is_also_sent_to_the_named_site(tmp_path) -> None:
    agent, store, gateway = _agent(tmp_path)
    agent.ollama = _OpensAnotherSiteFirst()
    job = store.create_job("chat", "agent", {"prompt": "다나와에서 무선마우스 상위 3개 알려줘"})
    store.claim_next()

    agent.run("다나와에서 무선마우스 상위 3개 알려줘", job_id=job["id"], origin="chat")

    name, arguments = gateway.calls[0]
    assert (name, arguments.get("url")) == ("browser_open", "https://danawa.com/")
