"""모델 실행기가 **잠깐 응답하지 않을 때**도 한 번 다시 묻는다 (2026-10-15).

2026-10-15 00:05 6GB 노트북(4B 3비트 · 글만 읽기 · 48K): 실행기 프로세스는 살아 있었는데(같은 번호로 그 뒤 두 시간 넘게 돌았다)
Ollama 가 실행기의 tokenize 주소에 붙지 못해 500 을 돌려줬다:

    Post "http://127.0.0.1:60347/tokenize": dial tcp 127.0.0.1:60347: connectex: A connection attempt failed because
    the connected party did not properly respond after a period of time, ...

10-14 에 넣은 「실행기가 꺼지면 한 번 더 묻기」(`runner_stopped`)는 「꺼졌다」는 문구만 알아서 이 글을 몰랐다. 그 판은 바로
실패로 끝났고 과제 하나를 잃었다. 1초 뒤 같은 모델은 멀쩡히 대답했다.

지키는 약속:
- Ollama 가 **자기 실행기(127.0.0.1 의 어느 포트)에 붙지 못했다**는 500 도 「꺼졌다」와 같이 한 번 다시 묻는다.
  윈도우의 connectex 문구와 「connection refused」 둘 다.
- 두 번째도 그러면 `model_runner_stopped` 로 올린다(10-14 약속 그대로).
- 실행기와 상관없는 500(템플릿 오류 · 빈 글)은 그대로 둔다.
"""
from __future__ import annotations

from typing import Any

from test_streaming_404_retries_too import DONE, _Client, _client, _Response

UNRESPONSIVE = (
    '{"error":"Post \\"http://127.0.0.1:60347/tokenize\\": dial tcp 127.0.0.1:60347: connectex: A connection attempt '
    'failed because the connected party did not properly respond after a period of time, or established connection '
    'failed because connected host has failed to respond."}'
)
REFUSED = '{"error":"Post \\"http://127.0.0.1:51123/completion\\": dial tcp 127.0.0.1:51123: connect: connection refused"}'


def test_an_unreachable_runner_is_recognised() -> None:
    from alture_jarvis.ollama import runner_stopped

    assert runner_stopped(UNRESPONSIVE)
    assert runner_stopped(REFUSED)
    assert not runner_stopped('{"error":"Jinja Exception: System message must be at the beginning."}')
    assert not runner_stopped('{"error":"model \\"nope\\" not found, try pulling it first"}')
    assert not runner_stopped("")


def test_an_unresponsive_runner_is_asked_once_more(monkeypatch: Any) -> None:
    plan = [_Response(500, [], UNRESPONSIVE), _Response(200, [DONE])]
    client, _module = _client(monkeypatch, plan, installed=True)

    result = client.chat_messages_stream([{"role": "user", "content": "안녕"}])

    assert _Client.opened == 2, "다시 묻지 않았다"
    assert "답" in str(result.get("content") or ""), result
