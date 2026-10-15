"""예고 되받기는 **일이 나아가는 동안** 되풀이한다 (2026-10-02 밤 레딧 기록 예약 6ac6e043).

예전엔 한 판에 한 번만 되받았다. 예약 판이 게시물 9개 중 4개를 읽고 「나머지(5~9)도 계속 읽겠습니다」라고 두 번째 예고를 하자
그게 답이 됐다 — 걸음·시간이 남았고, 「이어서」를 눌러 줄 사람이 없는 예약 판이었다(엑셀도 안 씀).
원칙: 지난 되받기 뒤에 도구를 한 번이라도 더 썼으면 다시 되받는다. 예고만 되풀이하면 두 번째에서 멈춘다.
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

from test_agent import FakeBrowser

PROMPT = "내 레딧 프로필에서 올린 글 5개를 전부 열어 읽고 제목을 정리해줘"
PUSHBACK = "방금 말은 다음 걸음 예고라"
PROMISE = "나머지 게시물도 계속 읽겠습니다."
ANSWER = "정리: 글 5개를 모두 읽었습니다 — post/1 · post/2 · post/3 · post/4 · post/5."


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


def _read(url: str) -> dict[str, Any]:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_read", "arguments": {"url": url}}}]}


class _ReadsInBatches:
    """둘 읽고 예고 → 되받으면 둘 더 읽고 예고 → 되받으면 하나 더 읽고 답한다(실제 판처럼 일하면서 중간중간 예고)."""

    PLAN = [["https://reddit.example/post/1", "https://reddit.example/post/2"],
            ["https://reddit.example/post/3", "https://reddit.example/post/4"],
            ["https://reddit.example/post/5"]]

    def __init__(self, *, stubborn: bool = False) -> None:
        self.stubborn = stubborn
        self.done = 0

    def chat_messages(self, messages, **kwargs) -> dict[str, Any]:
        pushbacks = sum(str(m.get("content") or "").count(PUSHBACK) for m in messages)
        batch = 0 if self.stubborn else min(pushbacks, len(self.PLAN) - 1)
        if self.done < sum(len(b) for b in self.PLAN[: batch + 1]):
            url = [u for b in self.PLAN for u in b][self.done]
            self.done += 1
            return _read(url)
        if batch == len(self.PLAN) - 1:
            return {"role": "assistant", "content": ANSWER}
        return {"role": "assistant", "content": PROMISE}


def _run(tmp_path, model):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _ReadGateway()
    agent = BrowserAgent(config, model, gateway, FakeBrowser(), _ReadTools(), store, EventBus())
    job = store.create_job("chat", "agent", {"prompt": PROMPT})
    store.claim_next()
    return gateway, agent.run(PROMPT, job_id=job["id"], origin="chat")


def test_a_run_that_keeps_working_between_promises_is_pushed_back_each_time(tmp_path) -> None:
    gateway, result = _run(tmp_path, _ReadsInBatches())
    assert len(gateway.reads) == 5, gateway.reads
    assert result.answer.startswith("정리:"), result.answer
    assert "예고만 하고 멈췄습니다" not in result.answer


def test_a_run_that_only_repeats_the_promise_stops_at_the_second(tmp_path) -> None:
    gateway, result = _run(tmp_path, _ReadsInBatches(stubborn=True))
    assert len(gateway.reads) == 2, "되받은 뒤 아무것도 안 했으니 더 되받지 않는다"
    assert "예고만 하고 멈췄습니다" in result.answer
