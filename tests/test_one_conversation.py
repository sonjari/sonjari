"""자비스는 하나여야 한다 — 화면이 둘이어도.

2026-08-06 실측: 작은 HUD 에 물어본 것은 `office-main`(메시지 94개)에, 전체화면에
물어본 것은 `jarvis-*`(14개)에 쌓이고 있었다. 같은 모델·같은 프롬프트인데 기억이
갈라져 있으니 사용자님 눈에는 **다른 자비스 둘**이다 — 방금 한 얘기를 저쪽 창에 물으면
모른다. 원인은 화면마다 자기 기본 대화 이름을 들고 있던 것(backend.ts 의
`sessionId = "office-main"`).

기본값을 없앴다. 아무 말 없이 보내면 **사용자님이 보고 있는 대화**로 간다.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig


def _app(tmp_path: Path):
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )
    return create_app(config, start_services=False)


def _chat(client: TestClient, body: dict) -> dict:
    response = client.post("/v1/chat", json=body, headers={"X-JARVIS-TOKEN": "test-token"})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_chat_with_no_session_lands_where_the_screen_is_looking(tmp_path: Path) -> None:
    app = _app(tmp_path)
    client = TestClient(app)
    client.post("/v1/ui/presence", json={"session_id": "jarvis-live"}, headers={"X-JARVIS-TOKEN": "test-token"})

    job = _chat(client, {"prompt": "지금 몇 시야"})

    assert app.state.jarvis.store.get_job(job["id"])["payload"]["session_id"] == "jarvis-live"


def test_without_a_live_screen_it_falls_back_to_the_default(tmp_path: Path) -> None:
    """워크스페이스를 안 켰을 때도 답이 갈 곳은 있어야 한다."""
    app = _app(tmp_path)
    client = TestClient(app)

    job = _chat(client, {"prompt": "안녕"})

    assert app.state.jarvis.store.get_job(job["id"])["payload"]["session_id"] == "office-main"


def test_a_screen_that_names_its_conversation_still_wins(tmp_path: Path) -> None:
    """워크스페이스는 어느 대화인지 정말로 안다. 그 값을 덮으면 안 된다."""
    app = _app(tmp_path)
    client = TestClient(app)
    client.post("/v1/ui/presence", json={"session_id": "jarvis-live"}, headers={"X-JARVIS-TOKEN": "test-token"})

    job = _chat(client, {"prompt": "이건 다른 대화로", "session_id": "jarvis-other"})

    assert app.state.jarvis.store.get_job(job["id"])["payload"]["session_id"] == "jarvis-other"


def test_the_session_is_fixed_at_send_time_not_at_run_time(tmp_path: Path) -> None:
    """작업이 도는 사이 사용자님이 다른 대화로 옮기면, 나중에 정하는 방식은 답을
    엉뚱한 곳에 넣는다."""
    app = _app(tmp_path)
    client = TestClient(app)
    client.post("/v1/ui/presence", json={"session_id": "jarvis-first"}, headers={"X-JARVIS-TOKEN": "test-token"})
    job = _chat(client, {"prompt": "질문"})

    client.post("/v1/ui/presence", json={"session_id": "jarvis-second"}, headers={"X-JARVIS-TOKEN": "test-token"})

    assert app.state.jarvis.store.get_job(job["id"])["payload"]["session_id"] == "jarvis-first"


def test_the_screen_can_recognise_a_job_it_did_not_start(tmp_path: Path) -> None:
    """실시간 동기화의 근거. 이 두 값이 없으면 전체화면은 HUD 가 만든 작업을
    알아보지 못하고, 같은 대화인데도 새로고침해야 답이 보인다."""
    app = _app(tmp_path)
    client = TestClient(app)
    client.post("/v1/ui/presence", json={"session_id": "jarvis-live"}, headers={"X-JARVIS-TOKEN": "test-token"})

    _chat(client, {"prompt": "작은 창에서 물어본 것"})

    events = [event.to_dict() for event in app.state.jarvis.events.get_since(0, 50)]
    queued = [event for event in events if event["event"] == "job_queued"][-1]
    assert queued["payload"]["session_id"] == "jarvis-live"
    assert queued["payload"]["prompt"] == "작은 창에서 물어본 것"
