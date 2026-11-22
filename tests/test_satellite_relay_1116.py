"""위성(맥) ↔ 집 PC 넘기는 길이 처리 고리를 막지 않는다 · 위성 연결 확인이 한 번 늦어도 「연결 안 됨」으로 뒤집히지 않는다 (2026-11-16).

11-16 02:40 실측(PC 안): `127.0.0.1:8092/v1/pair/hello` 가 약 30초마다 4~8초 멈췄고 같은 순간 8091 은 0.03초.
py-spy 로 멈춘 순간 세 번을 잡았더니 셋 다 짝짓기 문 스레드가 `_relay` → `httpx.AsyncClient()` → 인증서 묶음 읽기에 있었다.
요청마다 인증서 설정을 새로 만들지 않아야 한다 — 시험은 「요청 중에 공유 설정 없이 만든 인증서 설정의 수」를 센다(0 이어야 한다).
"""

from __future__ import annotations

import ssl
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from alture_jarvis import ollama as ollama_module
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

LAN = ("192.168.0.20", 51000)


@pytest.fixture()
def fresh_contexts(monkeypatch):
    """httpx 가 공유 설정 없이(`verify=True` 등) 인증서 설정을 새로 만든 횟수 — 요청마다 0.2~5초 드는 그 일."""
    from httpx._transports import default as transport_default

    made: list[object] = []
    real = transport_default.create_ssl_context

    def counting(verify=True, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not isinstance(verify, ssl.SSLContext):
            made.append(verify)
        return real(verify, *args, **kwargs)

    ollama_module.shared_verify()  # 앱이 미리 만들어 두는 공유 설정 — 이건 세지 않는다
    monkeypatch.setattr(transport_default, "create_ssl_context", counting)
    return made


def _mock_upstream(monkeypatch):
    """가짜 upstream 을 **진짜 연결부의 보내기 자리**에 끼운다.

    `transport=MockTransport(...)` 로 끼우면 httpx 가 진짜 연결부를 안 만들어 인증서 설정도 안 만든다 — 그 방식으로 처음 쓴
    이 시험은 고침을 빼도 통과했다(11-16 깨 보기). 연결부는 진짜로 만들게 두고 보내는 일만 가로챈다.
    """

    async def handle(self, request: httpx.Request) -> httpx.Response:  # type: ignore[no-untyped-def]
        body = {"models": []} if request.url.path.endswith(("tags", "ps")) else {"done": True}
        return httpx.Response(200, json=body, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)


def _config(tmp_path: Path, data: Path, **extra) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=data, output_dir=tmp_path / "outputs",
                        control_token="test-token", camera_enabled=False, vision_enabled=False,
                        voice_enabled=False, tts_enabled=False, profile_path=data / "JARVIS_PROFILE.md", **extra)


def test_home_pc_door_relay_builds_no_tls_context_per_request(tmp_path: Path, monkeypatch, fresh_contexts):
    """집 PC 쪽(`/v1/llm`) — 맥이 몇 번을 불러도 인증서 설정을 새로 만들지 않는다."""
    _mock_upstream(monkeypatch)
    data = tmp_path / "data"
    app = create_app(_config(tmp_path, data, ollama_base_url="http://127.0.0.1:11434", model_roles={"chat": "swift:27b"}),
                     start_services=False)
    with TestClient(app, client=LAN) as lan, TestClient(app) as home:
        asked = lan.post("/v1/pair/request", json={"name": "MAC", "device_id": "dev-1"}).json()
        code = home.get("/v1/pair/pending", headers={"X-JARVIS-TOKEN": "test-token"}).json()["requests"][0]["code"]
        token = lan.post("/v1/pair/confirm", json={"request_id": asked["request_id"], "code": code}).json()["token"]
        fresh_contexts.clear()
        for path in ("api/tags", "api/ps", "api/tags", "api/version"):
            assert lan.get(f"/v1/llm/{path}", headers={"X-Sonjari-Device": token}).status_code == 200
        assert lan.post("/v1/llm/api/chat", headers={"X-Sonjari-Device": token},
                        json={"model": "swift:27b", "messages": []}).status_code == 200
    assert fresh_contexts == []


def test_satellite_relay_builds_no_tls_context_per_request(tmp_path: Path, monkeypatch, fresh_contexts):
    """맥 쪽(`/v1/home-llm`) — 같은 코드라 같은 병이었다. 와이파이 길이 안 닿아 테일넷으로 넘어가도 새로 만들지 않는다."""
    from alture_jarvis import pairing
    from alture_jarvis.messaging import credentials

    _mock_upstream(monkeypatch)

    class Store:
        def read(self, target):  # type: ignore[no-untyped-def]
            return "device-token"

    monkeypatch.setattr(credentials, "default_store", lambda: Store())
    data = tmp_path / "data"
    data.mkdir()
    pairing.save_home(data, {"name": "HOME-PC", "address": "192.0.2.10:8092", "tailnet_address": "home.tail.ts.net:8092"})
    app = create_app(_config(tmp_path, data), start_services=False)
    fresh_contexts.clear()
    with TestClient(app) as here:
        for _ in range(3):
            assert here.get("/v1/home-llm/api/tags").status_code == 200
        assert here.post("/v1/home-llm/api/chat", json={"model": "swift:27b", "messages": []}).status_code == 200
    assert fresh_contexts == []


# ── 위성 연결 확인 ─────────────────────────────────────────────────────────────────────────────────────


def _timeout_client(monkeypatch):
    real = httpx.Client

    def mocked(*args, **kwargs):  # type: ignore[no-untyped-def]
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        kwargs["transport"] = httpx.MockTransport(boom)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", mocked)


def _client(base: str) -> ollama_module.OllamaClient:
    return ollama_module.OllamaClient(JarvisConfig(ollama_base_url=base, model_roles={"chat": "swift:27b"}))


SATELLITE = "http://127.0.0.1:8091/v1/home-llm"


def test_satellite_probe_late_right_after_a_reply_stays_connected(monkeypatch):
    """모델이 방금 답했는데 확인(목록 · 상태)이 3초를 넘겼다 — 「연결 안 됨」이 아니라 「연결됨 · 확인이 늦음」."""
    _timeout_client(monkeypatch)
    client = _client(SATELLITE)
    client.__dict__["_last_ok_at"] = time.time() - 5
    status = client.health()
    assert status["ok"] is True
    assert status["probe_late"] is True
    assert "timed out" in status["probe_error"]
    assert status["model"] == "swift:27b"


def test_satellite_keeps_last_good_details_while_probe_is_late(monkeypatch):
    """마지막으로 통과한 확인의 내용(올라간 모델 · 창 크기)을 그대로 보여 준다 — 빈 칸으로 깜빡이지 않게."""
    client = _client(SATELLITE)
    good = {"ok": True, "model": "swift:27b", "resident": True, "context_length": 131072}
    client.__dict__["_last_health_ok"] = (time.time() - 30, good)
    _timeout_client(monkeypatch)
    status = client.health()
    assert status["ok"] is True and status["resident"] is True and status["context_length"] == 131072
    assert status["last_alive_age_sec"] >= 29


def test_satellite_long_silent_home_still_says_disconnected(monkeypatch):
    """2분 넘게 아무 답도 없었으면 정말 안 닿는 것이다 — 그대로 실패를 알린다."""
    _timeout_client(monkeypatch)
    client = _client(SATELLITE)
    client.__dict__["_last_ok_at"] = time.time() - 600
    assert client.health()["ok"] is False
    assert _client(SATELLITE).health()["ok"] is False  # 한 번도 닿은 적 없음


def test_this_pc_ollama_failure_is_never_masked(monkeypatch):
    """이 PC 의 Ollama 는 유예하지 않는다 — 워치독 · 켜기 지킴이가 이 실패를 보고 살린다."""
    _timeout_client(monkeypatch)
    client = _client("http://127.0.0.1:11434")
    client.__dict__["_last_ok_at"] = time.time() - 5
    assert client.health()["ok"] is False
    assert client.brain_is_remote() is False
    assert _client("http://192.168.0.5:11434").brain_is_remote() is True
    assert _client(SATELLITE).brain_is_remote() is True
