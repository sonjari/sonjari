"""도구를 부를 글은 **화면에 뜬 적이 없어야** 한다.

## 사용자님이 보고 말한 것 (2026-08-15)

    "MCP 작업 다 하기 전에 답변이 나오고, 그다음에 답변이 나왔다가 사라지고"

프론트도 젬마도 아니었다. `agent._model_message` 가 글자를 받는 족족 화면에 흘려
보내고, 스트림이 끝나 `tool_calls` 가 있는 걸 알면 그때 `agent_answer_reset` 으로
지우고 있었다. 젬마는 도구 호출을 메시지 **끝**에 붙이므로 순서가 이렇게 된다:

    "이제 검색하겠습니다" 가 다 타이핑됨 → 사라짐 → 그제서야 도구가 돌음

도구를 여러 개 태우는 판에서는 이 깜빡임이 **매 걸음** 반복된다.

## 왜 예전 수정이 이걸 못 막았나

2026-08-10 에 같은 증상을 고쳤는데(`runtime._held_stream_callback`), 그건 **라우터**
경로에만 들어갔다. 정작 도구가 도는 곳은 에이전트 루프였고 거기는 옛 방식 그대로였다.
그래서 "고쳤는데 또 그러네"가 됐다.

지우는 시점을 앞당길 방법은 없다 — 끝까지 안 보면 도구를 부를지 모른다.
그러면 **애초에 내보내지 않으면 된다.**
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore


class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names: set[str] = set()
    ollama_tools: list = []


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):
        raise AssertionError("이 시험은 도구를 실행하지 않는다")


class _StreamsThenCallsATool:
    """말을 먼저 흘리고 **마지막에** 도구를 붙이는 모델. 젬마가 실제로 그렇게 한다."""

    def __init__(self, *, with_tool_call: bool) -> None:
        self.with_tool_call = with_tool_call

    def chat_messages_stream(self, messages, *, tools=None, temperature=0.1, think=False, on_chunk=None):
        for piece in ("이제 ", "다나와에서 ", "검색하겠습니다."):
            on_chunk({"content": piece})
        message = {"role": "assistant", "content": "이제 다나와에서 검색하겠습니다."}
        if self.with_tool_call:
            message["tool_calls"] = [
                {"function": {"name": "browser_search", "arguments": {"query": "무선마우스"}}}
            ]
        return message


def _agent(tmp_path, *, with_tool_call: bool):
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
    )
    events = EventBus()
    agent = BrowserAgent(
        config,
        _StreamsThenCallsATool(with_tool_call=with_tool_call),
        _Gateway(),
        _Browser(),
        _Tools(),
        JobStore(tmp_path / "j.db"),
        events,
    )
    return agent, events


def _answer_events(events: EventBus) -> list[str]:
    return [e.event for e in events.get_since(0) if e.event.startswith("agent_answer")]


def test_nothing_reaches_the_screen_when_a_tool_is_coming(tmp_path) -> None:
    """이 시험이 이 버그의 전부다.

    `agent_answer_delta` 가 하나라도 나가면 화면에 글이 떴다는 뜻이고, 그러면
    반드시 지워야 하고, 그 지우기가 사용자가 본 깜빡임이다.
    """
    agent, events = _agent(tmp_path, with_tool_call=True)

    agent._model_message([], job_id="job-1", tools=[{"x": 1}], think=False)

    assert _answer_events(events) == [], (
        f"도구를 부를 글이 화면에 나갔다: {_answer_events(events)} — "
        "나갔으면 지워야 하고, 그 지우기가 '나왔다 사라짐'이다"
    )


def test_the_model_turn_never_paints_by_itself(tmp_path) -> None:
    """도구를 **안** 부를 때도 이 층은 안 칠한다.

    ★ 이게 두 번째 수정이다(2026-08-15). 처음엔 "도구가 있으면 안 칠한다"로 고쳤는데
    실측(위시켓)에서 이 순서가 그대로 남았다:

        도구 8개 → 답 칠해짐 → 도구 5개 더 → 다른 답

    도구를 안 부른 것은 맞았다. 그런데 **부르는 쪽이 그 답을 안 받아들였다** —
    계획 대조가 "시킨 것이 남았다"고 되받아쳐 계속 시켰다(`plan_pushback`).
    답을 쓸지 아는 것은 부르는 쪽뿐이므로, 칠하기도 부르는 쪽이 한다.
    """
    agent, events = _agent(tmp_path, with_tool_call=False)

    agent._model_message([], job_id="job-2", tools=None, think=False)

    assert _answer_events(events) == [], (
        f"모델 한 번 부른 것만으로 화면에 답이 나갔다: {_answer_events(events)} — "
        "그 답이 되받히면 사라진다"
    )


def test_paint_answer_reveals_in_pieces_not_one_lump() -> None:
    """확정된 답은 **스르륵** 나와야 한다.

    한 덩어리로 내보내면 화면 따라 내려가기가 같이 죽는다(2026-08-10 실측) —
    따라가기는 delta 가 올 때마다 도는 것이라 delta 가 한 번이면 한 번만 돈다.
    """
    from alture_jarvis.presentation import paint_answer

    events = EventBus()
    text = "확인한 근거를 바탕으로 정리한 최종 답변입니다." * 3

    assert paint_answer(events, "job-3", text) is True

    kinds = [e.event for e in events.get_since(0)]
    assert kinds[0] == "agent_answer_reset", "칠하기 전에 화면을 안 비웠다"
    deltas = [e for e in events.get_since(0) if e.event == "agent_answer_delta"]
    assert len(deltas) >= 2, f"통째로 한 번에 튀어나왔다(delta {len(deltas)}건)"
    assert "".join(str(e.payload["delta"]) for e in deltas) == text


def test_paint_answer_stays_quiet_when_there_is_nothing_to_say() -> None:
    """빈 답에 reset 만 쏘면 **화면이 이유 없이 비워진다.**"""
    events = EventBus()
    from alture_jarvis.presentation import paint_answer

    assert paint_answer(events, "job-4", "") is False
    assert [e.event for e in events.get_since(0)] == []
