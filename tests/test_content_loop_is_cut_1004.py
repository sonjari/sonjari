"""답 글이 같은 토막을 되풀이하면 상한까지 기다리지 않고 끊는다 (2026-10-04 허깅페이스 판 56247177).

모델이 「Qwen3-32B-A3B-Instruct가 아니라 Qwen3-32B-A3B-Instruct…」를 답 글로 끝없이 되풀이했다. **생각**의 되풀이는
09-18 부터 일찍 끊었는데 **답 글**은 상한(8,192토큰 — 한 턴 80초쯤)까지 그대로 흘렸고, 그런 턴이 연달아 나와 판이
20걸음에서 10분 동안 서 있었다. GPU 는 100% 였다 — 일하는 것처럼 보이는 멈춤이다.
"""
from __future__ import annotations

import json
from typing import Any

from alture_jarvis import ollama as module
from alture_jarvis.config import JarvisConfig

_LOOP = "정확한 모델명은 Qwen3-32B-A3B-Instruct가 아니라 Qwen3-32B-A3B-Instruct입니다. "
_HEAD = "허깅페이스에서 찾아본 결과입니다.\n\n| 모델 | 크기 |\n|---|---|\n| A | 1 |\n\n"
_DONE = json.dumps({"message": {"content": ""}, "done": True, "done_reason": "length", "eval_count": 8192})


class _Response:
    def __init__(self, lines: list[str]) -> None:
        self.status_code = 200
        self._lines = lines
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
        for line in self._lines:
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


def _content_lines(pieces: list[str]) -> list[str]:
    return [json.dumps({"message": {"content": piece}}, ensure_ascii=False) for piece in pieces] + [_DONE]


def _client(monkeypatch: Any, plan: list[_Response]) -> Any:
    _Client.plan, _Client.bodies = plan, []
    monkeypatch.setattr(module.httpx, "Client", _Client)
    client = module.OllamaClient(JarvisConfig())
    for name in ("_make_room_for", "_wait_out_transient_404"):
        monkeypatch.setattr(type(client), name, lambda self, _x: None, raising=False)
    return client


# --- 스트림 ------------------------------------------------------------------

def test_a_looping_answer_is_cut_long_before_the_cap(monkeypatch: Any) -> None:
    response = _Response(_content_lines([_HEAD] + [_LOOP] * 400))
    client = _client(monkeypatch, [response])

    message = client.chat_messages_stream([{"role": "user", "content": "모델 찾아줘"}], think=False)

    assert response.read_lines < 60, "400조각을 다 읽지 않고 일찍 닫아야 한다"
    assert len(_Client.bodies) == 1, "두 번째 호출은 하지 않는다 — 되풀이 앞까지는 멀쩡한 답이다"
    assert message["content"].count("Qwen3-32B-A3B-Instruct입니다") == 1, "한 바퀴만 남긴다"
    assert message["content"].startswith("허깅페이스에서 찾아본 결과입니다.\n\n| 모델 | 크기 |\n|---|---|")
    assert message["_metrics"]["done_reason"] == "content_loop_cut"


def test_a_long_answer_that_does_not_repeat_runs_to_the_end(monkeypatch: Any) -> None:
    pieces = [f"{index}번째 문장은 저마다 다른 내용을 담고 있습니다(번호 {index * 7}). " for index in range(300)]
    response = _Response(_content_lines(pieces))
    client = _client(monkeypatch, [response])

    message = client.chat_messages_stream([{"role": "user", "content": "길게 써줘"}], think=False)

    assert response.read_lines == len(pieces) + 1
    assert message["content"] == "".join(pieces).strip()
    assert message["_metrics"]["done_reason"] == "length"


def test_a_turn_that_already_called_a_tool_is_left_alone(monkeypatch: Any) -> None:
    """도구 호출이 나온 턴은 건드리지 않는다 — 인자를 잃으면 그 걸음이 통째로 사라진다."""
    call = json.dumps({"message": {"tool_calls": [{"function": {"name": "browser_open", "arguments": {"url": "https://a.b"}}}]}})
    lines = [call] + _content_lines([_LOOP] * 100)
    response = _Response(lines)
    client = _client(monkeypatch, [response])

    message = client.chat_messages_stream([{"role": "user", "content": "열어줘"}], think=False)

    assert response.read_lines == len(lines)
    assert message["tool_calls"] and message["tool_calls"][0]["function"]["name"] == "browser_open"


# --- 판정 --------------------------------------------------------------------

def test_a_phrase_that_keeps_coming_back_is_a_loop() -> None:
    assert module.content_is_looping(_HEAD + _LOOP * 40) is True


def test_short_text_and_text_said_twice_are_not_loops() -> None:
    assert module.content_is_looping(_LOOP * 5) is False  # 아직 짧다 — 판정하지 않는다
    paragraph = "같은 문단이 요약과 본문에 한 번씩 나오는 멀쩡한 답입니다. 가나다라마바사 0123456789 abcdefghij. " * 4
    filler = " ".join(f"사이에 낀 {index}번째 다른 문장입니다." for index in range(60))
    assert module.content_is_looping(paragraph + filler + paragraph) is False  # 두 번은 되풀이가 아니다


def test_rows_of_empty_cells_are_not_judged() -> None:
    """빈 칸뿐인 표 줄은 글자 종류가 적다 — 채울 서식을 만들어 달라는 과제에서 멀쩡한 답이다."""
    assert module.content_is_looping(_HEAD + "\n".join("| | | | |" for _ in range(400))) is False


def test_the_cut_keeps_line_breaks_and_one_round() -> None:
    kept = module._cut_content_loop(_HEAD + _LOOP * 40)

    assert kept.startswith(_HEAD)
    assert kept.count("Qwen3-32B-A3B-Instruct입니다") == 1
    assert len(kept) < len(_HEAD) + len(_LOOP) * 2
