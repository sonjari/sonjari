"""판의 끝에서 예고가 답을 대신하지 못한다 — 실기에서 본 두 자리 (2026-10-07, 코드 서명 가격 판 c4b26962).

같은 과제를 고친 코드로 다시 맡기자 읽은 곳은 1 → 7 로 늘었는데, 끝은 또 예고였다:

    「정정하겠습니다. Sectigo EV 페이지는 열어두었으니 본문 가격을 바로 읽어 완성하겠습니다.」  · 상태 「완료」

1. 모델이 `browser_open` · `browser_extract` 를 한 턴에 불렀는데 **열기에서 걸음 상한이 차서 읽기가 잘렸다.**
   열어 놓고 안 읽은 페이지는 근거가 아니다 — 상한은 짝의 가운데가 아니라 짝이 끝난 자리에서 끊는다.
2. 장부와 어긋난 한 줄을 고치라고 한 「다시 쓰기」가 **예고를 돌려줬고, 그것이 앞 답을 통째로 갈아치웠다.**
   이 자리는 예고 검사보다 뒤라 「완료」로 찍혔다. 예고뿐인 다시 쓰기는 받지 않는다.
"""

from __future__ import annotations

from alture_jarvis.agent import _EXTRACT_TOOL, _OPEN_RESULT_TOOL, BrowserAgent, _read_completes_an_open
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

OPEN = "browser_open"


class _Browser:
    def status(self):
        return {"started": True}


# ── 1. 상한은 「연 페이지의 읽기」를 끊지 않는다 ─────────────────────────────


def test_a_read_right_after_a_successful_open_belongs_to_it() -> None:
    assert _read_completes_an_open([{"tool": OPEN, "ok": True}], _EXTRACT_TOOL) is True
    assert _read_completes_an_open([{"tool": _OPEN_RESULT_TOOL, "ok": True}], "browser_read") is True


def test_nothing_else_is_let_through() -> None:
    assert _read_completes_an_open([{"tool": OPEN, "ok": False}], _EXTRACT_TOOL) is False, "실패한 열기 뒤는 빈 화면이다"
    assert _read_completes_an_open([{"tool": _EXTRACT_TOOL, "ok": True}], _EXTRACT_TOOL) is False, "읽기 뒤의 읽기는 짝이 아니다"
    assert _read_completes_an_open([{"tool": OPEN, "ok": True}], OPEN) is False, "열기는 더 보내지 않는다"
    assert _read_completes_an_open([{"tool": OPEN, "ok": True}], "browser_click") is False
    assert _read_completes_an_open([], _EXTRACT_TOOL) is False


class _PageTools:
    names = {OPEN, _EXTRACT_TOOL}
    ollama_tools = [
        {"type": "function", "function": {"name": OPEN, "description": "open",
                                          "parameters": {"type": "object", "properties": {}}}},
    ]


class _PageGateway:
    def __init__(self) -> None:
        self.showing = ""
        self.calls: list[tuple[str, str]] = []

    def execute(self, name, arguments, *, job_id=""):
        if name == OPEN:
            self.showing = str(arguments.get("url") or "")
        self.calls.append((name, self.showing))
        body = f"{self.showing} 의 본문. " * 40 if name == _EXTRACT_TOOL else ""
        return ToolResult(True, name, result={"url": self.showing, "title": self.showing, "text": body})


class _TwoPairsInOneTurn:
    """열기·읽기 두 짝을 한 턴에 부른다 — 걸음 상한 3 이면 둘째 열기에서 찬다."""

    def __init__(self) -> None:
        self.turns = 0

    def chat_messages(self, messages, **kwargs):
        self.turns += 1
        if self.turns == 1:
            return {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": OPEN, "arguments": {"url": "https://example.com/a"}}},
                {"function": {"name": _EXTRACT_TOOL, "arguments": {"max_chars": 6000}}},
                {"function": {"name": OPEN, "arguments": {"url": "https://example.com/b"}}},
                {"function": {"name": _EXTRACT_TOOL, "arguments": {"max_chars": 6000}}},
                {"function": {"name": OPEN, "arguments": {"url": "https://example.com/c"}}},
            ]}
        return {"role": "assistant", "content": "두 곳을 읽었습니다."}


def test_the_step_cap_does_not_cut_between_an_open_and_its_read(tmp_path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60, ollama_max_tool_steps=3)
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _PageGateway()
    agent = BrowserAgent(config, _TwoPairsInOneTurn(), gateway, _Browser(), _PageTools(), store, EventBus())
    prompt = "이 주소들의 내용을 알려줘"
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()

    agent.run(prompt, job_id=job["id"], origin="chat")

    assert gateway.calls == [
        (OPEN, "https://example.com/a"), (_EXTRACT_TOOL, "https://example.com/a"),
        (OPEN, "https://example.com/b"), (_EXTRACT_TOOL, "https://example.com/b"),
    ], "셋째 걸음(둘째 열기)에서 상한이 찼다 — 그 읽기까지만 가고, 셋째 열기는 가지 않는다"


# ── 2. 예고뿐인 「다시 쓰기」는 앞 답을 갈아치우지 못한다 ────────────────────


class _ReadTools:
    names = {"browser_read"}
    ollama_tools = [
        {"type": "function", "function": {"name": "browser_read", "description": "read",
                                          "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}},
    ]


class _ReadGateway:
    def execute(self, name, arguments, *, job_id=""):
        index = int(str(arguments["url"]).rsplit("/", 1)[-1])
        return ToolResult(True, name, result={
            "action": "read", "url": f"https://www.saramin.co.kr/jobs/{index}", "title": f"정규직 공고 {index}",
            "char_count": 12000 + index, "text": f"정규직 공고 {index} 본문",
        })


DRAFT = "2개를 확인했습니다. 세 번째 상세 정보 추출에 실패했습니다."
PROMISE = "정정하겠습니다. 세 번째 공고 페이지는 열어두었으니 본문을 바로 읽어 완성하겠습니다."


class _DraftThenPromise:
    """셋을 다 읽고도 「세 번째 추출 실패」라고 쓴 초안 → 고치라고 하자 예고로 답한다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **_kwargs):
        self.calls += 1
        if self.calls <= 3:
            return {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "browser_read",
                              "arguments": {"url": f"https://www.saramin.co.kr/jobs/{self.calls}"}}}]}
        if self.calls == 4:
            return {"role": "assistant", "content": DRAFT}
        return {"role": "assistant", "content": PROMISE}


def test_a_rewrite_that_only_promises_does_not_replace_the_answer(tmp_path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    agent = BrowserAgent(config, _DraftThenPromise(), _ReadGateway(), _Browser(), _ReadTools(), store, events)
    prompt = "사람인 정규직 공고 3개를 찾아줘"
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()

    result = agent.run(prompt, job_id=job["id"], origin="chat")

    assert "완성하겠습니다" not in result.answer, "예고가 답이 됐다"
    assert result.answer.startswith(DRAFT[:12]), "앞 답을 그대로 둔다"
    assert result.verification["answer_reconciled"] is False
    assert result.verification["completion_state"] != "complete", "어긋난 채로 남은 답은 완료가 아니다"
    names = [event.event for event in events.get_since(0)]
    assert names.count("agent_reconciliation_promise_rejected") == 1
