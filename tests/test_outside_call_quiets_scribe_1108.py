"""짝지은 맥이 PC 모델을 부르면 PC 의 노는 시간 일(서기 · 데우기)이 비켜야 한다 (2026-11-08).

양방향: 바깥 부르기가 오면 나가 있던 노는 일을 끊고 「방금 썼다」로 센다 / 아무도 안 부르면 조용함은 그대로.
"""

import time

from alture_jarvis.ollama import OllamaClient


class _Closable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _client() -> OllamaClient:
    client = OllamaClient.__new__(OllamaClient)
    client.__dict__["_last_send_at"] = 0.0
    return client


def test_outside_call_cancels_background_and_counts_as_recent_use() -> None:
    client = _client()
    running = _Closable()
    client.__dict__["_background_client"] = running
    client.note_outside_call()
    assert running.closed is True
    assert time.monotonic() - client.__dict__["_last_send_at"] < 1.0


def test_without_outside_calls_quiet_time_is_untouched() -> None:
    client = _client()
    assert client.__dict__["_last_send_at"] == 0.0
    assert client.cancel_background() is False
