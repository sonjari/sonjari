"""생각 예산 뒤의 두 번째 호출 — 대화 틀이 생각 스위치를 앞머리에 그리는 모델이면 생각을 켠 채 부른다 (2026-10-09 새벽).

우리 숙제를 손자리에게 맡긴 판의 서버 기록: 운영 모델의 틀은 도구가 있으면 프롬프트 첫 줄에 생각 안내 문장을 그리고, 그 줄은
생각이 켜져 있을 때만 들어간다. 생각을 끄고 다시 부르면 첫 토큰부터 달라져 대화 전체(8~9만 토큰)를 다시 읽었다(한 번에 89~126초).
"""
from __future__ import annotations

from typing import Any

from alture_jarvis import ollama as module
from alture_jarvis.ollama import think_switch_is_drawn_before_the_messages
from test_thinking_budget import _ANSWERED, _Client, _Response, _client, _thinking_lines

_FRONT = (
    "{%- set note = '' %}{%- if enable_thinking is undefined or enable_thinking is true %}{%- set note = 'Think.' %}{%- endif %}"
    "{{- '<|im_start|>system\\n' + note }}{%- for message in messages %}{{ message.content }}{%- endfor %}"
    "{%- if add_generation_prompt %}{{- '<|im_start|>assistant\\n' }}{%- endif %}"
)
_TAIL_ONLY = (
    "{%- for message in messages %}{{ message.content }}{%- endfor %}"
    "{%- if add_generation_prompt %}{{- '<|im_start|>assistant\\n' }}"
    "{%- if enable_thinking is defined and enable_thinking is false %}{{- '<think>\\n\\n</think>\\n\\n' }}{%- endif %}{%- endif %}"
)


# ── 틀 읽기 ─────────────────────────────────────────────────────────────────────


def test_a_switch_read_before_the_conversation_moves_the_front() -> None:
    assert think_switch_is_drawn_before_the_messages(_FRONT) is True


def test_a_switch_used_only_where_the_answer_starts_does_not() -> None:
    assert think_switch_is_drawn_before_the_messages(_TAIL_ONLY) is False


def test_go_templates_are_read_the_same_way() -> None:
    front = "{{ if .IsThinkSet }}think{{ end }}{{ range .Messages }}{{ .Content }}{{ end }}"
    tail = "{{ range $i, $m := .Messages }}{{ $m.Content }}{{ end }}{{ if .Think }}<think>{{ end }}"
    assert think_switch_is_drawn_before_the_messages(front) is True
    assert think_switch_is_drawn_before_the_messages(tail) is False


def test_a_template_we_cannot_read_keeps_the_old_behaviour() -> None:
    for unknown in ("", "{{ .Prompt }}", "{%- for message in messages %}{{ message.content }}{%- endfor %}"):
        assert think_switch_is_drawn_before_the_messages(unknown) is False


def test_asking_the_server_fails_safe_and_is_asked_once(monkeypatch: Any) -> None:
    client = _client(monkeypatch, [])
    asked: list[str] = []

    def post(url: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        asked.append(str((kwargs.get("json") or {}).get("model")))
        raise OSError("서버에 못 닿는다")

    monkeypatch.setattr(module.httpx, "post", post)
    assert client.think_moves_the_front("some-model") is False
    assert client.think_moves_the_front("some-model") is False
    assert asked == ["some-model"]


def test_the_server_answer_is_read_through_the_template(monkeypatch: Any) -> None:
    client = _client(monkeypatch, [])

    class _Shown:
        def json(self) -> dict[str, Any]:
            return {"template": _FRONT}

    monkeypatch.setattr(module.httpx, "post", lambda url, **kwargs: _Shown())
    assert client.think_moves_the_front("front-model") is True


# ── 두 번째 호출 ────────────────────────────────────────────────────────────────


def _front_client(monkeypatch: Any, plan: list[_Response]) -> Any:
    """장치를 **켠** 클라이언트. 기본은 끔이다(아래 `test_the_mechanism_is_off_by_default`)."""
    client = _client(monkeypatch, plan)
    monkeypatch.setattr(type(client), "think_moves_the_front", lambda self, _model: True)
    monkeypatch.setattr(type(client), "_KEEP_THINKING_ON_SECOND_PASS", True)
    return client


def test_the_mechanism_is_off_by_default(monkeypatch: Any) -> None:
    """실제 판에서 다섯 번 중 다섯 번이 또 예산을 넘겨 떨어졌다(숙제 3 넷 · 사람인 하나) — 시간만 더 썼다. 기본은 예전 방식이다."""
    assert module.OllamaClient._KEEP_THINKING_ON_SECOND_PASS is False
    client = _client(monkeypatch, [_Response(_thinking_lines(30_000)), _Response([_ANSWERED])])
    monkeypatch.setattr(type(client), "think_moves_the_front", lambda self, _model: True)
    client.chat_messages_stream([{"role": "user", "content": "긴 일"}], think=True)
    assert [body["think"] for body in _Client.bodies] == [True, False]


def test_the_second_call_keeps_thinking_on_when_the_switch_sits_at_the_front(monkeypatch: Any) -> None:
    client = _front_client(monkeypatch, [_Response(_thinking_lines(30_000)), _Response([_ANSWERED])])
    message = client.chat_messages_stream([{"role": "user", "content": "긴 일"}], think=True)

    first, second = _Client.bodies
    assert first["think"] is True and second["think"] is True, "생각을 끄면 프롬프트 앞머리가 달라진다"
    assert second["messages"][:-1] == first["messages"], "앞 대화는 글자 그대로여야 캐시가 산다"
    nudge = second["messages"][-1]
    assert nudge["role"] == "user" and "지금 바로" in nudge["content"]
    assert message["content"] == "바로 답"
    kept = message["_thinking_budget"]["second_pass"]
    assert kept["kept_thinking"] is True and kept["fell_back"] is False
    assert len(message["thinking"]) >= 8000, "장부에는 첫 생각이 남는다"


def test_a_second_call_that_runs_away_again_falls_back_to_the_old_way(monkeypatch: Any) -> None:
    client = _front_client(monkeypatch, [
        _Response(_thinking_lines(30_000)), _Response(_thinking_lines(30_000)), _Response([_ANSWERED]),
    ])
    message = client.chat_messages_stream([{"role": "user", "content": "긴 일"}], think=True)

    assert [body["think"] for body in _Client.bodies] == [True, True, False], "두 번째도 넘기면 그때만 생각을 끈다"
    assert _Client.bodies[2]["messages"] == _Client.bodies[1]["messages"], "안내는 한 번만 실린다"
    assert message["content"] == "바로 답"
    second = message["_thinking_budget"]["second_pass"]
    assert second["kept_thinking"] is True and second["fell_back"] is True


def test_the_second_call_is_cut_much_sooner_than_the_first(monkeypatch: Any) -> None:
    """「더 생각하지 말라」는 안내를 받은 호출은 짧은 예산으로 본다 — 3,000자를 생각하면 끊긴다(첫 예산 8,000자 아래)."""
    client = _front_client(monkeypatch, [
        _Response(_thinking_lines(30_000)), _Response(_thinking_lines(3_000)), _Response([_ANSWERED]),
    ])
    client.chat_messages_stream([{"role": "user", "content": "긴 일"}], think=True)
    assert len(_Client.bodies) == 3
    assert module.OllamaClient._SECOND_PASS_THINKING_CHARS < 3_000


def test_other_models_stop_thinking_on_the_second_call_as_before(monkeypatch: Any) -> None:
    client = _client(monkeypatch, [_Response(_thinking_lines(30_000)), _Response([_ANSWERED])])
    monkeypatch.setattr(type(client), "think_moves_the_front", lambda self, _model: False)
    message = client.chat_messages_stream([{"role": "user", "content": "긴 일"}], think=True)

    assert _Client.bodies[1]["think"] is False
    second = message["_thinking_budget"]["second_pass"]
    assert second["kept_thinking"] is False and second["fell_back"] is False
