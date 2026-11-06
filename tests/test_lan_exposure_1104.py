"""같은 와이파이에서 이 PC 손자리(:8091)에 닿는 길 전수 점검 (2026-11-04 보안 점검).

이 PC 백엔드는 0.0.0.0 에 열려 있고(같은 와이파이 · 테일넷), 바깥 요청은 문지기(peer_guard)가 거른다. 짝짓기를 넣으며
같은 와이파이에 **짝짓기 길만** 열었다. 지키는 것(양방향):
- 같은 와이파이(192.168.x)에서는 모든 HTTP 길이 403 — 짝짓기(hello · request · confirm)와 기기 열쇠로 여는 /v1/llm/ 만 예외.
  웹소켓(/v1/ws)도 닫힌다(HTTP 미들웨어는 소켓을 안 보므로 따로 막는다).
- 열쇠(제어 토큰) 없이 답하는 길은 아래 목록뿐이다 — 새 길이 열쇠 없이 생기면 이 시험이 잡는다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

LAN = ("192.168.0.20", 51000)
AUTH = {"X-JARVIS-TOKEN": "test-token"}
PAIRING_OPEN = {"/v1/pair/hello", "/v1/pair/request", "/v1/pair/confirm", "/v1/pair/outside"}

#: 열쇠 없이 답하는 길(루프백 · 테일넷에서만 닿는다). 늘리려면 까닭을 적고 여기에 더한다.
TOKENLESS_OK = {
    "/",                        # 이름 · 판
    "/health",                  # 상태 확인(화면 · 트레이 · 설치 점검)
    "/v1/pair/hello",           # 짝짓기 찾기(같은 와이파이)
    "/v1/pair/request",         # 짝 청하기 — 코드는 돌려주지 않는다
    "/v1/pair/confirm",         # 집 PC 화면의 숫자 6개로만
    "/v1/pair/outside",         # 밖에서도 쓰기 진행 맞춰 보기 — 기기 열쇠(X-Sonjari-Device) 없으면 401(11-04)
    "/v1/llm/{path:path}",      # 기기 열쇠(X-Sonjari-Device)로 연다
    "/v1/home-llm/{path:path}", # 이 기기 안(루프백)에서만
    "/v1/jobs/{job_id}",        # 열쇠 없이 읽으면 정제한 답만(outbound_job_view)
    "/v1/slides/fonts/{rel:path}",  # 공개 글꼴 파일(OFL) — 미리보기 칸의 CSS 가 머리글 없이 부른다
    "/v1/tools",                # 도구 이름 · 설명뿐 — 떠 있는 옛 클로드 연결 프로세스가 열쇠 없이 읽는다(11-04)
}


@pytest.fixture()
def app(tmp_path: Path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md")
    return create_app(config, start_services=False)


def _concrete(path: str) -> str:
    out = []
    for part in path.split("/"):
        out.append("x" if part.startswith("{") else part)
    return "/".join(out)


def test_from_the_same_wifi_only_the_pairing_paths_answer(app):
    seen, leaked = 0, []
    with TestClient(app, client=LAN) as lan:
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in sorted(route.methods - {"HEAD"}):
                path = _concrete(route.path)
                status = lan.request(method, path, headers=AUTH, json={}).status_code
                seen += 1
                is_open = route.path in PAIRING_OPEN or route.path.startswith("/v1/llm/")
                if not is_open and status != 403:
                    leaked.append(f"{method} {route.path} → {status}")
    assert seen > 200, seen  # 정말로 전부 두드렸나(표본 수를 직접 센다)
    assert leaked == [], leaked


def test_the_event_socket_is_closed_to_the_same_wifi(app):
    with TestClient(app, client=LAN) as lan:
        with pytest.raises(WebSocketDisconnect) as closed:
            with lan.websocket_connect("/v1/ws", subprotocols=["jarvis", "test-token"]) as ws:
                ws.receive_json()
        assert closed.value.code == 4403


def test_only_the_listed_paths_answer_without_the_key(app):
    """열쇠 검사가 없는 길 = require_token 의존이 없고, 손으로 열쇠를 보는 매개변수(x_jarvis_token)도 없는 길."""
    tokenless = set()
    for route in app.routes:
        if isinstance(route, APIWebSocketRoute) or not isinstance(route, APIRoute):
            continue
        deps = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        params = set(inspect.signature(route.endpoint).parameters)
        if "require_token" not in deps and "x_jarvis_token" not in params:
            tokenless.add(route.path)
    # 반대 방향도 센다: 목록에 있는데 사라진 길이 있으면 목록을 고친다.
    assert tokenless - TOKENLESS_OK == set(), sorted(tokenless - TOKENLESS_OK)


def test_the_tokenless_event_log_never_carries_a_pairing_code(app):
    """사건 기록은 열쇠 없이 읽힌다 — 짝 코드가 거기 실리면 이 PC 안의 다른 프로그램 · 테일넷 기기가 코드를 본다(11-04)."""
    with TestClient(app, client=LAN) as lan, TestClient(app) as here:
        assert lan.post("/v1/pair/request", json={"name": "guest", "device_id": "g"}).json()["ok"]
        code = here.get("/v1/pair/pending", headers=AUTH).json()["requests"][0]["code"]
        log = here.get("/v1/events", params={"after": 0, "limit": 500}).text
        assert code not in log


LOCKED_READS = ["/v1/config", "/v1/state", "/v1/presentation/policy", "/v1/events", "/v1/jobs", "/v1/vision/status",
                "/v1/browser/status", "/v1/browser/frame.jpg", "/v1/vision/snapshot.jpg", "/v1/capabilities"]


def test_reads_that_used_to_be_open_now_need_the_key_even_from_this_pc(app):
    """11-04 대표 「전부 해 주라」: 이 PC 안의 다른 프로그램 · 테일넷 기기가 브라우저 화면 · 카메라 그림까지 열쇠 없이 읽었다."""
    with TestClient(app) as here:
        for path in LOCKED_READS:
            assert here.get(path).status_code == 401, path
            assert here.get(path, headers=AUTH).status_code != 401, path   # 반대 방향: 열쇠가 있으면 열린다
        assert here.get("/health").status_code == 200                       # 상태 확인은 그대로



def test_the_outside_check_needs_the_device_key_even_from_the_same_wifi(app):
    """/v1/pair/outside 는 같은 와이파이에 열려 있지만, 짝지을 때 받은 기기 열쇠가 없으면 아무것도 말하지 않는다."""
    with TestClient(app, client=LAN) as lan:
        answer = lan.post("/v1/pair/outside", json={"me": {"installed": True, "state": "Running"}})
        assert answer.status_code == 401
        assert "tailnet" not in answer.text
        assert lan.post("/v1/pair/outside", headers={"X-Sonjari-Device": "guess"}, json={}).status_code == 401
