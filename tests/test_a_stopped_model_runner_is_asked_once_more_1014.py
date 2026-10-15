"""모델 실행기가 꺼지면 한 번 다시 묻고, 또 꺼지면 「꺼졌다」고 적는다 (2026-10-14).

2026-10-13 밤 6GB 노트북(메모리 24GB): 모델 실행기가 일반 메모리를 12GB 까지 쓰다 죽었고 그 요청은 500 으로 돌아왔다.
Ollama 는 그 500 의 글에 **55초 전의 다른 오류**를 같이 실어 보냈다:

    model runner has unexpectedly stopped, this may be due to resource limitations or an internal error, …
    Error: Jinja Exception: System message must be at the beginning.

우리는 뒤쪽 낱말만 보고 「이미 접어 보낸 모델인데 또 템플릿 오류」로 읽어 그 글을 그대로 판의 실패 까닭으로 적었다.
판은 걸음 12개를 하고도 통째로 실패했고, 기록의 이름표는 원인(메모리)을 가리키지 않았다.

지키는 약속:
- 실행기가 꺼졌다는 500 은 한 번 다시 묻는다(Ollama 가 다음 요청에서 실행기를 다시 올린다).
- 또 꺼지면 `model_runner_stopped` 로 올린다 — 옛 오류 글을 이름표로 쓰지 않는다.
- 그 글에 템플릿 낱말이 같이 실려 와도 「꺼졌다」가 먼저다.
"""
from __future__ import annotations

from typing import Any

import pytest

from test_streaming_404_retries_too import DONE, _Client, _client, _Response

STOPPED = ('{"error":"model runner has unexpectedly stopped, this may be due to resource limitations or an internal error, '
           'check ollama server logs for details: Error: Jinja Exception: System message must be at the beginning."}')


def test_the_words_of_a_stopped_runner_are_recognised() -> None:
    from alture_jarvis.ollama import runner_stopped

    assert runner_stopped(STOPPED)
    assert not runner_stopped('{"error":"Jinja Exception: System message must be at the beginning."}'), "템플릿 오류만으로는 아니다"
    assert not runner_stopped("")


def test_a_stopped_runner_is_asked_once_more(monkeypatch: Any) -> None:
    plan = [_Response(500, [], STOPPED), _Response(200, [DONE])]
    client, _module = _client(monkeypatch, plan, installed=True)

    result = client.chat_messages_stream([{"role": "user", "content": "안녕"}])

    assert _Client.opened == 2, "다시 묻지 않았다"
    assert "답" in str(result.get("content") or ""), result
    assert client.__dict__.get("_runner_restarts") == 1, "몇 번 꺼졌는지 센다"


def test_a_runner_that_stops_twice_is_named_for_what_it_is(monkeypatch: Any) -> None:
    plan = [_Response(500, [], STOPPED), _Response(500, [], STOPPED), _Response(200, [DONE])]
    client, _module = _client(monkeypatch, plan, installed=True)

    with pytest.raises(RuntimeError) as caught:
        client.chat_messages_stream([{"role": "user", "content": "안녕"}])

    assert _Client.opened == 2, "끝없이 다시 묻지 않는다"
    assert str(caught.value).startswith("model_runner_stopped"), str(caught.value)
    assert "System message" not in str(caught.value), "옛 오류 글을 이름표로 쓰지 않는다"


def test_a_model_already_folded_is_not_mistaken_for_a_template_error(monkeypatch: Any) -> None:
    """그날의 모양 그대로 — 이미 「시스템은 맨 앞만」으로 기억한 모델에서 실행기가 꺼졌다."""
    plan = [_Response(500, [], STOPPED), _Response(200, [DONE])]
    client, module = _client(monkeypatch, plan, installed=True)
    model = client.config.model_for("chat")
    monkeypatch.setattr(module, "_SYSTEM_FIRST_ONLY", {model})

    result = client.chat_messages_stream([{"role": "user", "content": "안녕"}])

    assert "답" in str(result.get("content") or "")
