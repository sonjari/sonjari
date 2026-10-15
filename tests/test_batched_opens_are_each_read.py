"""한 턴에 묶어 보낸 열기들은 **각자 읽힌다** — 앞 페이지가 덮여 사라지지 않는다 (2026-10-06).

실사용(코드 서명 가격 조사): 모델이 한 턴에 열기 넷 → 읽기 넷을 불렀다. 열기는 같은 탭을 덮으므로 읽기 넷이 전부
마지막 페이지를 읽었고(본문 지문이 넷 다 같았다), 걸음 상한 12 를 77초에 다 쓴 뒤 「세 페이지를 다시 읽겠습니다」로 끝났다.

운영 14일(브라우저 판 432): 같은 묶음에서 덮인 열기 38판 · 98쪽, 그중 66쪽은 그 판에서 끝내 안 읽혔다.
모양은 둘이었다 — `browser_open` 연달아(51) · `browser_open_result` 연달아(45, 융합한 읽기가 묶음 맨 끝에 붙어서).
"""

from __future__ import annotations

from alture_jarvis.agent import (
    _EXTRACT_TOOL,
    _OPEN_RESULT_TOOL,
    _call_position,
    _fused_read_call,
    _reads_beside_their_opens,
)

OPEN = "browser_open"
TOOLS = {OPEN, _OPEN_RESULT_TOOL, _EXTRACT_TOOL, "browser_read", "browser_snapshot"}


def _call(name: str, **arguments) -> dict:
    return {"function": {"name": name, "arguments": dict(arguments)}}


def _name_of(call: dict) -> str:
    return str((call.get("function") or {}).get("name") or "")


def _run(calls: list[dict], *, enabled: bool = True) -> list[tuple[str, str]]:
    """묶음을 실제 루프처럼 돈다 — (도구, 그때 떠 있던 페이지). 읽기는 떠 있는 페이지를 읽는다."""
    calls = _reads_beside_their_opens(calls, _name_of)
    showing = ""
    ran: list[tuple[str, str]] = []
    for call in calls:
        assert len(ran) < 40, "끝나지 않는다"
        name = _name_of(call)
        if name in {OPEN, _OPEN_RESULT_TOOL}:
            showing = str(call["function"]["arguments"].get("url") or call["function"]["arguments"].get("rank"))
        ran.append((name, showing))
        if _fused_read_call(name, {"ok": True}, calls, call, enabled=enabled, available=TOOLS, next_name=_name_of):
            calls.insert(_call_position(calls, call) + 1 or len(calls), _call(_EXTRACT_TOOL))
    return ran


def _read_pages(ran: list[tuple[str, str]]) -> list[str]:
    return [page for name, page in ran if name in {_EXTRACT_TOOL, "browser_read"}]


def test_four_opens_then_four_reads_reads_all_four_pages() -> None:
    """실제로 본 모양 그대로 — 전에는 넷 다 D 를 읽었다."""
    calls = [_call(OPEN, url=u) for u in "ABCD"] + [_call(_EXTRACT_TOOL, max_chars=6000) for _ in range(4)]

    ran = _run(calls)

    assert _read_pages(ran) == ["A", "B", "C", "D"]
    assert len(ran) == 8, "모델이 부른 여덟 걸음 그대로 — 더 붙지도 빠지지도 않는다"


def test_the_calls_are_moved_not_rewritten() -> None:
    opens = [_call(OPEN, url=u) for u in "AB"]
    reads = [_call(_EXTRACT_TOOL, max_chars=6000), _call("browser_read")]

    paired = _reads_beside_their_opens(opens + reads, _name_of)

    assert [id(c) for c in paired] == [id(opens[0]), id(reads[0]), id(opens[1]), id(reads[1])]


def test_three_opens_and_one_read_still_reads_all_three() -> None:
    """읽기가 모자라면 마지막 열기가 읽기를 갖고, 앞의 둘은 덮이기 전에 읽힌다."""
    calls = [_call(OPEN, url=u) for u in "ABC"] + [_call(_EXTRACT_TOOL)]

    assert _read_pages(_run(calls)) == ["A", "B", "C"]


def test_opens_with_no_read_at_all_are_read_before_they_are_buried() -> None:
    """`browser_open_result` 셋 — 전에는 읽기 하나가 맨 끝에 붙어 셋째만 읽혔다."""
    calls = [_call(_OPEN_RESULT_TOOL, rank=r) for r in (1, 2, 3)]

    assert _read_pages(_run(calls)) == ["1", "2", "3"]


def test_plain_opens_are_read_before_they_are_buried_even_with_fusing_off() -> None:
    """덮이는 것은 최적화 설정과 무관하다 — 읽을 수 있는 마지막 순간이다. 마지막 열기는 모델이 정한다."""
    calls = [_call(OPEN, url=u) for u in "AB"]

    assert _read_pages(_run(calls, enabled=False)) == ["A"]


def test_more_reads_than_opens_keeps_the_spare_reads_at_the_end() -> None:
    calls = [_call(OPEN, url=u) for u in "AB"] + [_call(_EXTRACT_TOOL) for _ in range(3)]

    assert _read_pages(_run(calls)) == ["A", "B", "B"]


def test_an_ordinary_turn_is_handed_back_untouched() -> None:
    """바꿀 것이 없으면 **받은 목록 그대로** — 대화에 남는 호출 순서를 괜히 건드리지 않는다."""
    for calls in (
        [_call(OPEN, url="A"), _call(_EXTRACT_TOOL)],
        [_call(OPEN, url="A")],
        [_call("browser_snapshot"), _call(_EXTRACT_TOOL)],
        [_call(OPEN, url="A"), _call(OPEN, url="B")],
        [_call(OPEN, url="A"), _call(OPEN, url="B"), _call(OPEN, url="C"), _call(_EXTRACT_TOOL)],
        [],
    ):
        assert _reads_beside_their_opens(calls, _name_of) is calls


def test_something_between_the_opens_and_the_reads_is_left_alone() -> None:
    """열기와 읽기 사이에 다른 손이 끼면 뜻을 짐작하지 않는다."""
    calls = [_call(OPEN, url="A"), _call(OPEN, url="B"), _call("browser_snapshot"),
             _call(_EXTRACT_TOOL), _call(_EXTRACT_TOOL)]

    assert _reads_beside_their_opens(calls, _name_of) is calls


def test_two_batches_in_one_turn_are_each_paired() -> None:
    calls = ([_call(OPEN, url=u) for u in "AB"] + [_call(_EXTRACT_TOOL) for _ in range(2)]
             + [_call("browser_snapshot")]
             + [_call(_OPEN_RESULT_TOOL, rank=r) for r in (1, 2)] + [_call(_EXTRACT_TOOL) for _ in range(2)])

    assert _read_pages(_run(calls)) == ["A", "B", "1", "2"]


def test_position_is_found_by_identity_not_by_value() -> None:
    """인자가 똑같은 읽기 넷 — 값으로 찾으면 넷 다 첫 자리다."""
    calls = [_call(_EXTRACT_TOOL) for _ in range(4)]

    assert [_call_position(calls, call) for call in calls] == [0, 1, 2, 3]
    assert _call_position(calls, _call(_EXTRACT_TOOL)) == -1


def test_a_failed_open_is_not_read_even_when_the_next_call_is_an_open() -> None:
    first, second = _call(OPEN, url="A"), _call(OPEN, url="B")

    assert _fused_read_call(OPEN, {"ok": False}, [first, second], first,
                            enabled=True, available=TOOLS, next_name=_name_of) is False


# ── 실제 루프에서 ─────────────────────────────────────────────────────────────


class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names = {OPEN, _EXTRACT_TOOL}
    ollama_tools = [
        {"type": "function", "function": {"name": OPEN, "description": "open",
                                          "parameters": {"type": "object", "properties": {}}}},
    ]


class _PageGateway:
    """열기는 떠 있는 페이지를 바꾸고, 읽기는 떠 있는 페이지의 글을 돌려준다 — 실제 브라우저와 같은 성질."""

    def __init__(self) -> None:
        self.showing = ""
        self.calls: list[tuple[str, str]] = []

    def execute(self, name, arguments, *, job_id=""):
        from alture_jarvis.models import ToolResult

        if name == OPEN:
            self.showing = str(arguments.get("url") or "")
        self.calls.append((name, self.showing))
        body = f"{self.showing} 의 본문. " * 40 if name == _EXTRACT_TOOL else ""
        return ToolResult(True, name, result={"url": self.showing, "title": self.showing, "text": body})


class _OpensFourThenReadsFour:
    def __init__(self) -> None:
        self.turns = 0
        self.seen: list[list[dict]] = []

    def chat_messages(self, messages, **kwargs):
        self.turns += 1
        self.seen.append(list(messages))
        if self.turns == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": (
                    [{"function": {"name": OPEN, "arguments": {"url": f"https://example.com/{page}"}}} for page in "abcd"]
                    + [{"function": {"name": _EXTRACT_TOOL, "arguments": {"max_chars": 6000}}} for _ in range(4)]
                ),
            }
        return {"role": "assistant", "content": "네 곳을 읽었습니다."}


def test_the_real_loop_reads_each_page_it_opened(tmp_path) -> None:
    from alture_jarvis.agent import BrowserAgent
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    gateway, model = _PageGateway(), _OpensFourThenReadsFour()
    agent = BrowserAgent(config, model, gateway, _Browser(), _Tools(), store, EventBus())
    prompt = "이 네 주소의 내용을 알려줘"
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()

    agent.run(prompt, job_id=job["id"], origin="chat")

    read = [page for name, page in gateway.calls if name == _EXTRACT_TOOL]
    assert read == [f"https://example.com/{page}" for page in "abcd"], gateway.calls
    assert len(gateway.calls) == 8, "모델이 부른 여덟 번 그대로다"
