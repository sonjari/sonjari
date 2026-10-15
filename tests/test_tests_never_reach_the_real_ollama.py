"""검사는 진짜 Ollama 에 닿지 않는다 — 회귀 한 번이 128K 모델을 올려 다른 앱의 러너를 빼앗았다(2026-09-28, conftest 참고)."""

from __future__ import annotations

import socket

import pytest


def test_connecting_to_ollama_is_refused_inside_tests() -> None:
    with pytest.raises(ConnectionRefusedError):
        with socket.create_connection(("127.0.0.1", 11434), timeout=1):
            pass
