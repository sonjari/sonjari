"""짝짓기 전용 문(8092 · pair_door.py) — 그 문으로는 짝짓기 세 길과 /v1/llm/ 만 지나간다 (2026-11-04).

지키는 것(양방향):
- 같은 와이파이 주소로 와도, 테일스케일 serve 처럼 127.0.0.1 로 와도(「이 PC 안」으로 보이는 요청) 허락한 길 밖은 전부 404.
  특히 「이 PC 에서만」 길(/v1/home-llm · /v1/browser/show · /v1/outputs/open)과 웹소켓.
- 허락한 길은 본 앱 그대로 답한다: hello 200 · request 짝 요청 · /v1/llm 은 기기 열쇠 없으면 401.
- 옛 기억(8091)은 8092 로 읽힌다 · 문은 윈도우 집 PC 에서만 연다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from alture_jarvis import pair_door, pairing
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

AUTH = {"X-JARVIS-TOKEN": "test-token"}


@pytest.fixture()
def apps(tmp_path: Path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md")
    main = create_app(config, start_services=False)
    return main, pair_door.door_app(main)


@pytest.mark.parametrize("client", [("192.168.0.20", 51000), ("127.0.0.1", 51000)], ids=["same_wifi", "via_tailscale_serve"])
def test_only_pairing_and_llm_pass_the_door(apps, client):
    main, door = apps
    leaked = []
    with TestClient(door, client=client) as c:
        for route in main.routes:
            if not isinstance(route, APIRoute):
                continue
            path = "/".join("x" if part.startswith("{") else part for part in route.path.split("/"))
            for method in sorted(route.methods - {"HEAD"}):
                status = c.request(method, path, headers=AUTH, json={}).status_code
                if not pair_door.allowed(path) and status != 404:
                    leaked.append(f"{method} {route.path} → {status}")
        assert leaked == [], leaked
        # 허락한 길은 본 앱 그대로
        assert c.get("/v1/pair/hello").json()["service"] == "sonjari"
        assert c.get("/v1/llm/api/tags").status_code == 401           # 기기 열쇠 없음
        assert c.get("/v1/home-llm/api/tags").status_code == 404      # 이 PC 에서만 — 문으로는 못 간다
        assert c.post("/v1/browser/show", headers=AUTH).status_code == 404


def test_the_door_closes_websockets(apps):
    _main, door = apps
    with TestClient(door, client=("127.0.0.1", 1)) as c:
        with pytest.raises(WebSocketDisconnect) as closed:
            with c.websocket_connect("/v1/ws", subprotocols=["jarvis", "test-token"]) as ws:
                ws.receive_json()
        assert closed.value.code == 4404


def test_a_mac_finds_the_home_pc_on_the_door_port_and_old_memories_move_there(tmp_path):
    assert pairing.PAIR_PORT == pair_door.DOOR_PORT == 8092
    pairing.save_home(tmp_path, {"address": "192.0.2.10:8091", "name": "HOME-PC"})
    assert pairing.read_home(tmp_path)["address"] == "192.0.2.10:8092"
    pairing.save_home(tmp_path, {"address": "192.0.2.10:8092", "name": "HOME-PC"})
    assert pairing.read_home(tmp_path)["address"] == "192.0.2.10:8092"


def test_the_door_opens_only_on_a_windows_home_pc(monkeypatch):
    on = JarvisConfig(pair_door="1")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert pair_door.should_open(on) is False
    monkeypatch.setattr(sys, "platform", "win32")
    assert pair_door.should_open(on) is True
    assert pair_door.should_open(JarvisConfig(pair_door="0")) is False


def test_the_door_really_listens_in_its_own_thread(apps):
    """실제 소켓으로: 따로 된 스레드에서 뜨고, hello 는 답하고 설정은 404, 멈추면 닫힌다."""
    import socket
    import time

    import httpx

    main, _door = apps
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    door = pair_door.PairDoor(main, host="127.0.0.1", port=port)
    door.start()
    try:
        for _ in range(100):
            if door.started:
                break
            time.sleep(0.05)
        assert door.started, door.error
        assert httpx.get(f"http://127.0.0.1:{port}/v1/pair/hello", timeout=5).json()["service"] == "sonjari"
        assert httpx.get(f"http://127.0.0.1:{port}/v1/config", headers=AUTH, timeout=5).status_code == 404
    finally:
        door.stop()
