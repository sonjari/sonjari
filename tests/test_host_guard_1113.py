"""주소 이름(Host) 거름 — DNS 리바인딩 막기 (2026-11-13 · r/Python 댓글이 짚음).

지키는 것: 공격자가 DNS 를 쥘 수 있는 이름(evil.example · 127.0.0.1.nip.io)으로 온 요청은 HTTP · 소켓 · 짝짓기 문 어디서든 403.
우리가 실제로 쓰는 이름(127.0.0.1 · localhost · tauri 화면 · 같은 와이파이 IP · 테일넷 100.x · *.ts.net · 맥 *.local · PC 이름)은 그대로 지나간다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from alture_jarvis import host_guard, pair_door
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

GOOD = [
    "", "127.0.0.1:8091", "127.0.0.1", "localhost:8091", "LOCALHOST", "localhost.", "[::1]:8091", "::1",
    "tauri.localhost", "192.168.0.20:8092", "100.64.0.20:8091", "desktop-a1b2c3", "testserver",
    "desktop-a1b2c3.tail1234.ts.net", "Mac-mini.local:8092", "pc.lan", "nas.home.arpa",
]
BAD = [
    "evil.example", "evil.example:8091", "127.0.0.1.nip.io", "localhost.evil.com", "attacker.com.",
    "ts.net.evil.com", "local.evil.com", "my-localhost.com", "[evil", "0x7f.1",
]


@pytest.mark.parametrize("header", GOOD)
def test_names_we_use_pass(header):
    assert host_guard.host_ok(header), header


@pytest.mark.parametrize("header", BAD)
def test_names_an_attacker_can_own_are_refused(header):
    assert not host_guard.host_ok(header), header


def test_extra_names_from_settings():
    assert not host_guard.host_ok("sonjari.mycorp.com")
    assert host_guard.host_ok("sonjari.mycorp.com", ["sonjari.mycorp.com"])
    assert host_guard.host_ok("a.mycorp.com:8091", [".mycorp.com"])
    assert not host_guard.host_ok("mycorp.com.evil.io", [".mycorp.com"])


@pytest.fixture()
def app(tmp_path: Path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md")
    return create_app(config, start_services=False)


def test_rebound_page_cannot_read_token_free_routes(app):
    with TestClient(app) as client:
        for path in ("/", "/health"):
            assert client.get(path, headers={"Host": "127.0.0.1:8091"}).status_code == 200
            refused = client.get(path, headers={"Host": "evil.example:8091"})
            assert refused.status_code == 403, path
            assert refused.json() == {"detail": "host_not_allowed"}


def test_refused_before_the_token_is_even_looked_at(app):
    with TestClient(app) as client:
        good = client.get("/v1/config", headers={"Host": "127.0.0.1", "X-JARVIS-TOKEN": "test-token"})
        bad = client.get("/v1/config", headers={"Host": "evil.example", "X-JARVIS-TOKEN": "test-token"})
    assert good.status_code == 200
    assert bad.status_code == 403


def test_websocket_is_guarded_too(app):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/ws", headers={"Host": "evil.example"},
                                          subprotocols=["jarvis", "test-token"]) as ws:
                ws.receive_json()
        with client.websocket_connect("/v1/ws", headers={"Host": "127.0.0.1:8091"},
                                      subprotocols=["jarvis", "test-token"]) as ws:
            assert ws.receive_json()["event"] == "connected"


def test_pair_door_keeps_the_guard(app):
    door = pair_door.door_app(app)
    with TestClient(door, client=("192.168.0.20", 51000)) as client:
        assert client.get("/v1/pair/hello", headers={"Host": "192.168.0.5:8092"}).status_code != 403
        assert client.get("/v1/pair/hello", headers={"Host": "evil.example:8092"}).status_code == 403
