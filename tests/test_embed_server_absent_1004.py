"""임베딩 서버가 없는 PC 에서 색인이 부를 때마다 2초를 버리지 않는다 (2026-10-04).

헤르메스 전수조사의 「첫 걸음까지 17초」를 다시 재다가 찾았다. 파일 3개짜리 폴더의 색인이 매번 2.3초였고 그중
2.05초가 `socket.connect` 한 줄이었다 — 기본 임베딩 주소(`127.0.0.1:11435`, 둘째 Ollama)에 아무것도 없으면
윈도우는 연결 거절에 약 2초를 쓴다. 의미 검색은 조용히 빈 결과로 넘어가므로 눈에 안 띄었다.
"""

from __future__ import annotations

import time

import httpx
import pytest

from alture_jarvis.code_index import CodeIndex


@pytest.fixture(autouse=True)
def _reset():
    CodeIndex._embed_down_until = 0.0
    yield
    CodeIndex._embed_down_until = 0.0


def test_after_one_failed_connect_the_server_is_not_knocked_on_again(monkeypatch) -> None:
    calls = []

    def refuse(*args, **kwargs):
        calls.append(kwargs.get("timeout"))
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", refuse)
    with pytest.raises(httpx.ConnectError):
        CodeIndex._embed(["query"])
    assert len(calls) == 1
    # 연결 대기는 짧게 건다 — 읽기 시간(큰 묶음 임베딩)은 그대로 길다.
    assert calls[0].connect <= 1.0 and calls[0].read >= 60
    with pytest.raises(ConnectionError):
        CodeIndex._embed(["query"])
    assert len(calls) == 1, "한 번 못 붙었으면 한동안 다시 두드리지 않는다"


def test_it_knocks_again_after_the_wait(monkeypatch) -> None:
    calls = []

    class Ok:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"embeddings": [[1.0, 0.0]]}

    def answer(*args, **kwargs):
        calls.append(1)
        return Ok()

    monkeypatch.setattr(httpx, "post", answer)
    CodeIndex._embed_down_until = time.monotonic() - 1  # 기다릴 시간이 지났다
    assert CodeIndex._embed(["query"]) == [[1.0, 0.0]] and calls == [1]


def test_a_server_error_is_not_mistaken_for_absence(monkeypatch) -> None:
    """붙기는 했는데 오류를 준 것(모델 없음 등)은 「서버가 없다」가 아니다 — 건너뛰기 표시를 세우지 않는다."""

    def broken(*args, **kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "post", broken)
    with pytest.raises(httpx.ReadTimeout):
        CodeIndex._embed(["query"])
    assert CodeIndex._embed_down_until == 0.0
