"""짝짓기 · 모델 빌려 주기 — HTTP 로 끝까지 (설계_짝짓기_모델자리_2026-11-03 §4-1 · §4-2 · §5).

같은 네트워크(192.168.x)의 맥이: 찾기 → 짝 청하기 → (집 PC 화면의 코드) → 코드 넣기 → 기기 토큰 → 모델 목록 빌리기.
막혀야 하는 것: 같은 네트워크에서 제어 API · 코드 목록 · 이 기기 전용 넘김 길 · 받기(pull) · 토큰 없는 빌리기 · 끊은 뒤 빌리기.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

AUTH = {"X-JARVIS-TOKEN": "test-token"}
LAN = ("192.168.0.20", 51000)


@pytest.fixture()
def parent(tmp_path: Path, monkeypatch):
    seen: list[str] = []

    def fake_ollama(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "swift:27b", "size": 14_000_000_000, "details": {}}]})
        return httpx.Response(200, json={"message": {"content": "4"}, "done": True})

    real = httpx.AsyncClient

    def mocked(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = httpx.MockTransport(fake_ollama)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mocked)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md",
                          ollama_base_url="http://127.0.0.1:11434", model_roles={"chat": "swift:27b"})
    app = create_app(config, start_services=False)
    return app, seen


def test_lan_pairs_with_the_code_and_borrows_only_through_the_token(parent):
    app, seen = parent
    with TestClient(app, client=LAN) as lan, TestClient(app) as home:
        hello = lan.get("/v1/pair/hello").json()
        assert hello["service"] == "sonjari" and hello["accepting"] is True and "model" not in hello
        asked = lan.post("/v1/pair/request", json={"name": "mac-mini", "device_id": "dev-1"}).json()
        assert asked["ok"] and "code" not in asked
        # 코드는 집 PC 화면(루프백 · 제어 토큰)에서만 보인다
        assert lan.get("/v1/pair/pending", headers=AUTH).status_code == 403
        code = home.get("/v1/pair/pending", headers=AUTH).json()["requests"][0]["code"]
        wrong = "000000" if code != "000000" else "111111"
        assert lan.post("/v1/pair/confirm", json={"request_id": asked["request_id"], "code": wrong}).json()["error"] == "wrong_code"
        done = lan.post("/v1/pair/confirm", json={"request_id": asked["request_id"], "code": code}).json()
        assert done["ok"] and done["home_model"] == "swift:27b"
        token = done["token"]

        # 토큰으로만 빌린다
        assert lan.get("/v1/llm/api/tags").status_code == 401
        assert lan.get("/v1/llm/api/tags", headers={"X-Sonjari-Device": "nope"}).status_code == 401
        tags = lan.get("/v1/llm/api/tags", headers={"X-Sonjari-Device": token})
        assert tags.status_code == 200 and tags.json()["models"][0]["name"] == "swift:27b"
        chat = lan.post("/v1/llm/api/chat", headers={"X-Sonjari-Device": token}, json={"model": "swift:27b", "messages": []})
        assert chat.status_code == 200 and chat.json()["message"]["content"] == "4"
        # 받기 · 지우기는 빌려 주지 않는다
        assert lan.post("/v1/llm/api/pull", headers={"X-Sonjari-Device": token}, json={"name": "x"}).status_code == 403
        assert lan.post("/v1/llm/api/delete", headers={"X-Sonjari-Device": token}, json={"name": "x"}).status_code == 403
        assert seen == ["/api/tags", "/api/chat"]

        # 끊으면 그 토큰은 끝
        device_id = home.get("/v1/pair/devices", headers=AUTH).json()["devices"][0]["device_id"]
        assert home.post("/v1/pair/revoke", headers=AUTH, json={"device_id": device_id}).json()["ok"]
        assert lan.get("/v1/llm/api/tags", headers={"X-Sonjari-Device": token}).status_code == 401


def test_the_lan_cannot_reach_the_control_api_or_the_local_relay(parent):
    app, _seen = parent
    with TestClient(app, client=LAN) as lan:
        assert lan.get("/v1/config").status_code == 403
        assert lan.post("/v1/chat", headers=AUTH, json={"prompt": "x"}).status_code == 403
        assert lan.get("/v1/pair/devices", headers=AUTH).status_code == 403
        assert lan.get("/v1/home-llm/api/tags").status_code == 403
    with TestClient(app, client=("8.8.8.8", 1)) as outside:
        assert outside.get("/v1/pair/hello").status_code == 403


def test_local_relay_without_pairing_says_so(parent):
    app, _seen = parent
    with TestClient(app) as home:
        assert home.get("/v1/home-llm/api/tags").status_code == 409


def test_relay_to_home_announces_only_real_model_calls(tmp_path: Path, monkeypatch):
    """11-04 대표: 연결 띠의 구슬은 실제로 부를 때만 간다 — 대화 부르기는 start · end 를 알리고 목록 묻기는 알리지 않는다."""
    from alture_jarvis import pairing
    from alture_jarvis.messaging import credentials

    real = httpx.AsyncClient

    def mocked(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"models": []} if request.url.path.endswith("tags") else {"done": True}))
        return real(*args, **kwargs)

    class Store:
        def read(self, target):  # type: ignore[no-untyped-def]
            return "device-token"

    monkeypatch.setattr(httpx, "AsyncClient", mocked)
    monkeypatch.setattr(credentials, "default_store", lambda: Store())
    data = tmp_path / "data"
    data.mkdir()
    pairing.save_home(data, {"name": "HOME-PC", "address": "192.0.2.10:8091", "gpu": "RTX 3090 24GB"})
    config = JarvisConfig(runtime_root=tmp_path, data_dir=data, output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=data / "JARVIS_PROFILE.md")
    app = create_app(config, start_services=False)
    events = app.state.jarvis.events
    with TestClient(app) as here:
        assert here.get("/v1/home-llm/api/tags").status_code == 200
        assert here.post("/v1/home-llm/api/chat", json={"model": "swift:27b", "messages": []}).status_code == 200
    calls = [e.payload for e in list(events._events) if e.event == "home_llm_call"]
    assert calls == [{"phase": "start"}, {"phase": "end", "ok": True}]
