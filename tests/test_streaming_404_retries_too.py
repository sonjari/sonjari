"""**404 재시도가 한쪽 길에만 있었다.**

## 실제로 일어난 일 (2026-09-11)

사슬 벤치의 한 판이 큐에서 238초 기다린 끝에 **4.7초 만에 걸음 0 으로** 죽었다.
고장은 이것 하나였다:

    Client error '404 Not Found' for url 'http://127.0.0.1:11434/api/chat'

그때 모델은 `/api/ps` 에 15.5GB 로 **올라와 있었다.** 최근 기록에 같은 죽음이
네 번 더 있다.

`_post_chat`(비스트리밍)에는 2026-09-09 에 붙인 재시도가 있었다. 그런데 **판이
실제로 타는 길은 스트리밍**이고 그쪽에는 없었다. 판단이 두 벌이면 한 벌만 고치고
고쳤다고 믿게 된다 — 바로 전날 `took_ms` 로 겪은 것과 같은 병이다.

되돌리기가 안전한 이유: 상태 검사는 헤더 직후, **한 조각도 읽기 전**이다.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest


class _Response:
    def __init__(self, status: int, lines: list[str], text: str = "") -> None:
        self.status_code = status
        self._lines = lines
        self.text = text

    def read(self) -> bytes:
        return self.text.encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Client error '{self.status_code}'",
                request=httpx.Request("POST", "http://x/api/chat"),
                response=httpx.Response(self.status_code),
            )

    def iter_lines(self):
        return iter(self._lines)


class _Client:
    """열 때마다 미리 정해 둔 응답을 하나씩 돌려준다."""

    plan: list[_Response] = []
    opened = 0

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def stream(self, _method: str, _url: str, **_kwargs: Any) -> _Response:
        response = type(self).plan[type(self).opened]
        type(self).opened += 1
        return response


DONE = '{"message":{"content":"답"},"done":true,"done_reason":"stop"}'


def _client(monkeypatch, plan: list[_Response], *, installed: bool) -> Any:
    from alture_jarvis import ollama as module

    _Client.plan, _Client.opened = plan, 0
    monkeypatch.setattr(module.httpx, "Client", _Client)
    from alture_jarvis.config import JarvisConfig

    client = module.OllamaClient(JarvisConfig())
    monkeypatch.setattr(type(client), "_model_is_installed",
                        lambda self, model: installed, raising=False)
    monkeypatch.setattr(type(client), "_make_room_for",
                        lambda self, model: None, raising=False)
    monkeypatch.setattr(type(client), "_wait_out_transient_404",
                        lambda self, body: None, raising=False)
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    return client, module


def test_a_404_on_the_stream_is_asked_once_more(monkeypatch: Any) -> None:
    """설치돼 있는 모델의 404 는 **일시적**이다 — 한 번 더 물어본다."""
    plan = [_Response(404, []), _Response(200, [DONE])]
    client, module = _client(monkeypatch, plan, installed=True)

    result = client.chat_messages_stream([{"role": "user", "content": "안녕"}])

    assert _Client.opened == 2, "스트리밍이 다시 열리지 않았다"
    assert "답" in str(result.get("content") or ""), result


def test_a_missing_model_404_is_not_retried(monkeypatch: Any) -> None:
    """진짜 없는 모델이면 그 404 는 **사실**이다. 다시 물어도 소용없다.

    무한 재시도는 진짜 고장을 침묵으로 바꾼다.
    """
    plan = [_Response(404, []), _Response(200, [DONE])]
    client, _module = _client(monkeypatch, plan, installed=False)

    with pytest.raises(httpx.HTTPStatusError):
        client.chat_messages_stream([{"role": "user", "content": "안녕"}])
    assert _Client.opened == 1, "없는 모델인데 또 물어봤다"


def test_a_second_404_gives_up(monkeypatch: Any) -> None:
    """상한을 넘으면 원래 오류가 올라간다 — 조용히 넘어가지 않는다.

    ★ 재시도가 처음엔 한 번(2초)이었는데 **그걸로 모자랐다.** 재시도를 붙인 뒤에도
      같은 404 로 판이 두 번 죽었다(2026-09-11). 러너가 다시 서는 창이 2초보다
      길다는 뜻이라 둘로 늘리고 간격을 2초·5초로 벌렸다.

      무한은 안 된다. 무한 재시도는 진짜 고장을 침묵으로 바꾼다.
    """
    from alture_jarvis.ollama import _STREAM_404_RETRIES

    tries = _STREAM_404_RETRIES + 1
    plan = [_Response(404, []) for _ in range(tries)]
    client, _module = _client(monkeypatch, plan, installed=True)

    with pytest.raises((httpx.HTTPStatusError, RuntimeError)):
        client.chat_messages_stream([{"role": "user", "content": "안녕"}])
    assert _Client.opened == tries, "상한만큼만 열어야 한다"


def test_the_failure_carries_what_ollama_said(monkeypatch: Any) -> None:
    """상태 코드만 남기면 **무엇이 없다는 것인지** 모른 채 추측만 는다.

    Ollama 는 404 에 `{"error":"model 'x' not found"}` 같은 본문을 실어 준다.
    그걸 버리고 있었다 — 이미 손에 쥔 답을 버린 것이다(정찰기 성적표와 같은 자리).
    """
    from alture_jarvis.ollama import _STREAM_404_RETRIES

    said = "{\"error\":\"model 'plopfit-gemma4-qat' not found\"}"
    plan = [_Response(404, [], text=said) for _ in range(_STREAM_404_RETRIES + 1)]
    client, _module = _client(monkeypatch, plan, installed=True)

    with pytest.raises(RuntimeError) as caught:
        client.chat_messages_stream([{"role": "user", "content": "안녕"}])
    assert "not found" in str(caught.value), caught.value


def test_a_healthy_call_opens_the_stream_once(monkeypatch: Any) -> None:
    """멀쩡한 판이 두 번 열리면 토큰을 두 배로 태운다."""
    plan = [_Response(200, [DONE])]
    client, _module = _client(monkeypatch, plan, installed=True)

    client.chat_messages_stream([{"role": "user", "content": "안녕"}])
    assert _Client.opened == 1
