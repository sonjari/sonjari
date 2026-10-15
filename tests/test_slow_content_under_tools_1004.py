"""도구 목록이 붙은 호출에서 답 글이 길어지며 속도가 무너지면, 끊고 도구 없이 다시 받는다 (2026-10-04 실측).

Ollama 0.32.14 · hf.co GGUF(`peg-native` 형식)에서 서버가 토큰마다 지금까지 쓴 답 글 전체를 도구 문법으로 다시 훑는다.
같은 목록 글(약 3,500토큰)을 운영 모델로 쟀다:

    도구 0개 답 글 24초(135 tok/s 일정)      도구 151개 도구 인자 43초(110 일정)
    도구 40개 답 글 101초(109→19)            도구 80개 답 글 100초(93→13)            도구 151개 답 글 382초(78→5)

운영 판 둘이 여기서 섰다 — 10-03 22시 예약 판(18분), 10-04 허깅페이스 판(12분에 취소).
도구 목록을 늘 떼면 프롬프트 캐시가 깨지므로(09-28), 무너지는 것을 **재고 나서** 그 턴만 다시 받는다.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from alture_jarvis import ollama as module
from alture_jarvis.config import JarvisConfig

_TOOLS = [{
    "type": "function",
    "function": {"name": "local_write_file", "description": "write", "parameters": {"type": "object", "properties": {}}},
}]
_DONE = json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop", "eval_count": 3000})
_AGAIN = json.dumps(
    {"message": {"content": "도구 없이 다시 받은 답"}, "done": True, "done_reason": "stop", "eval_count": 900},
    ensure_ascii=False,
)


class _Response:
    """줄을 내줄 때마다 가짜 시계를 `delay(몇 번째)` 만큼 돌린다 — 서버의 생성 속도를 흉내 낸다."""

    def __init__(self, lines: list[str], clock: dict[str, float], delay: Callable[[int], float]) -> None:
        self.status_code = 200
        self._lines = lines
        self._clock = clock
        self._delay = delay
        self.text = ""
        self.read_lines = 0

    def read(self) -> bytes:  # pragma: no cover — 400 일 때만 쓴다
        return b""

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self):
        for index, line in enumerate(self._lines):
            self._clock["t"] += self._delay(index)
            self.read_lines += 1
            yield line


class _Client:
    plan: list[_Response] = []
    bodies: list[dict[str, Any]] = []

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def stream(self, _method: str, _url: str, **kwargs: Any) -> _Response:
        type(self).bodies.append(kwargs.get("json") or {})
        return type(self).plan[len(type(self).bodies) - 1]


def _pieces(count: int) -> list[str]:
    return [json.dumps({"message": {"content": f"{index}번 줄. "}}, ensure_ascii=False) for index in range(count)] + [_DONE]


def _steady(_index: int) -> float:
    return 1 / 110  # 110 tok/s 일정 — 도구 인자를 쓸 때의 속도


def _collapsing(index: int) -> float:
    return 1 / 135 + index * 35e-6  # 실측 꼴: 1,000토큰마다 토큰당 35ms 씩 는다(도구 151개)


def _setup(monkeypatch: Any, plans: list[tuple[list[str], Callable[[int], float]]]) -> tuple[Any, list[_Response]]:
    clock = {"t": 1000.0}
    responses = [_Response(lines, clock, delay) for lines, delay in plans]
    _Client.plan, _Client.bodies = responses, []
    monkeypatch.setattr(module.httpx, "Client", _Client)
    monkeypatch.setattr(module, "_clock", lambda: clock["t"])
    client = module.OllamaClient(JarvisConfig())
    for name in ("_make_room_for", "_wait_out_transient_404"):
        monkeypatch.setattr(type(client), name, lambda self, _x: None, raising=False)
    return client, responses


def _ask(client: Any, tools: Any) -> dict[str, Any]:
    return client.chat_messages_stream([{"role": "user", "content": "길게 정리해줘"}], tools=tools, think=False)


def test_an_answer_that_collapses_under_tools_is_asked_again_without_them(monkeypatch: Any) -> None:
    client, responses = _setup(monkeypatch, [(_pieces(3000), _collapsing), ([_AGAIN], _steady)])

    message = _ask(client, _TOOLS)

    assert responses[0].read_lines < 1500, "3,000조각을 다 기다리지 않고 닫아야 한다"
    assert len(_Client.bodies) == 2
    assert "tools" in _Client.bodies[0] and "tools" not in _Client.bodies[1], "두 번째는 도구 목록 없이"
    assert _Client.bodies[0]["messages"][-1] == _Client.bodies[1]["messages"][-1], "같은 대화 — 안내문을 끼우지 않는다"
    assert message["content"] == "도구 없이 다시 받은 답"
    assert message["tool_calls"] == []
    seen = message["_slow_content"]
    assert seen["hit"] is True and seen["rate"] < seen["base_rate"] * 0.4
    assert seen["second_pass"]["used_partial"] is False


def test_a_steady_answer_under_tools_is_never_touched(monkeypatch: Any) -> None:
    client, responses = _setup(monkeypatch, [(_pieces(3000), _steady)])

    message = _ask(client, _TOOLS)

    assert len(_Client.bodies) == 1 and responses[0].read_lines == 3001
    assert "_slow_content" not in message


def test_without_tools_there_is_nothing_to_drop(monkeypatch: Any) -> None:
    """도구가 없는 호출이 느려지는 것은 이 병이 아니다(다른 앱이 GPU 를 쓰는 것) — 다시 불러도 같다."""
    client, responses = _setup(monkeypatch, [(_pieces(3000), _collapsing)])

    message = _ask(client, None)

    assert len(_Client.bodies) == 1 and responses[0].read_lines == 3001
    assert "_slow_content" not in message


def test_one_slow_stretch_is_let_through(monkeypatch: Any) -> None:
    """한 묶음만 출렁인 것(다른 앱이 GPU 를 잠깐 씀)은 넘긴다 — 연달아 두 묶음이어야 한다."""
    def blip(index: int) -> float:
        return 1 / 20 if 900 <= index < 1050 else 1 / 110

    client, responses = _setup(monkeypatch, [(_pieces(3000), blip)])

    _ask(client, _TOOLS)

    assert len(_Client.bodies) == 1 and responses[0].read_lines == 3001


def test_a_short_answer_is_left_alone_even_if_it_slows(monkeypatch: Any) -> None:
    client, responses = _setup(monkeypatch, [(_pieces(550), lambda index: 1 / 135 + index * 200e-6)])

    _ask(client, _TOOLS)

    assert len(_Client.bodies) == 1 and responses[0].read_lines == 551


def test_a_turn_that_already_called_a_tool_is_left_alone(monkeypatch: Any) -> None:
    call = json.dumps({"message": {"tool_calls": [{"function": {"name": "local_write_file", "arguments": {}}}]}})
    client, responses = _setup(monkeypatch, [([call] + _pieces(3000), _collapsing)])

    message = _ask(client, _TOOLS)

    assert len(_Client.bodies) == 1 and responses[0].read_lines == 3002
    assert message["tool_calls"]


def test_chunks_that_arrive_all_at_once_are_not_judged(monkeypatch: Any) -> None:
    """시간이 안 흐른 묶음은 생성 속도가 아니다(몰아 받은 것) — 기준도 판정도 세우지 않는다."""
    def burst_then_slow(index: int) -> float:
        return 0.0 if index < 450 else 1 / 20

    client, responses = _setup(monkeypatch, [(_pieces(3000), burst_then_slow)])

    _ask(client, _TOOLS)

    assert len(_Client.bodies) == 1 and responses[0].read_lines == 3001


def test_an_empty_second_answer_falls_back_to_what_was_already_written(monkeypatch: Any) -> None:
    empty = json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop", "eval_count": 1})
    client, _ = _setup(monkeypatch, [(_pieces(3000), _collapsing), ([empty], _steady)])

    message = _ask(client, _TOOLS)

    assert message["content"].startswith("0번 줄. 1번 줄.")
    assert message["_slow_content"]["second_pass"]["used_partial"] is True


def test_the_thresholds_are_ratios_not_this_pcs_numbers() -> None:
    """기준은 그 스트림 자신의 초반 속도 대비 비율이다 — 느린 PC(초당 20토큰)에서도 같은 규칙이 선다."""
    assert 0 < module._SLOW_CONTENT_SHARE < 1
    assert module._SLOW_CONTENT_HITS >= 2
    assert module._SLOW_CONTENT_MIN_CHUNKS >= module._SLOW_CONTENT_BASE_CHUNKS
