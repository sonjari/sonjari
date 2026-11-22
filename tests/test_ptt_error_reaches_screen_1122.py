"""말하기 버튼 실패가 화면에 까닭으로 닿는다 (2026-11-22 맥 「Load failed」).

맥 옛 설치(11-19 개발판)에 음성 도우미가 없어 `recorder.start()` 가 RuntimeError(mac_voice_helper_missing)를 냈다.
잡지 않은 예외 → 500 · CORS 머리 없음 → 웹뷰는 본문을 못 읽고 「Load failed」만 보였다.
지금은 409 + 「code: 사람 문장」이고, 응답에 CORS 머리가 붙는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alture_jarvis.api import create_app, ptt_error_text
from alture_jarvis.config import JarvisConfig

AUTH = {"X-JARVIS-TOKEN": "test-token"}


@pytest.fixture()
def app(tmp_path: Path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md")
    return create_app(config, start_services=False)


def _broken_recorder(app, code: str) -> None:
    def start():  # type: ignore[no-untyped-def]
        raise RuntimeError(code)
    app.state.jarvis.recorder.start = start


@pytest.mark.parametrize("path", ["/v1/voice/ptt/toggle", "/v1/voice/ptt/start"])
def test_missing_helper_comes_back_as_a_sentence_not_a_crash(app, path):
    _broken_recorder(app, "mac_voice_helper_missing")
    with TestClient(app, raise_server_exceptions=False) as client:
        origin = "tauri://localhost"
        res = client.post(path, json={}, headers={**AUTH, "Origin": origin})
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail.startswith("mac_voice_helper_missing: ") and "음성 도우미" in detail
    # 웹뷰가 본문을 읽으려면 CORS 머리가 있어야 한다(500 에는 없었다).
    assert res.headers.get("access-control-allow-origin") == origin


def test_state_goes_back_to_idle_so_the_next_press_is_not_busy(app):
    _broken_recorder(app, "mac_voice_helper_missing")
    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.post("/v1/voice/ptt/toggle", json={}, headers=AUTH)
        second = client.post("/v1/voice/ptt/toggle", json={}, headers=AUTH)
    assert first.json()["detail"].startswith("mac_voice_helper_missing")
    assert second.json()["detail"].startswith("mac_voice_helper_missing")  # jarvis_busy 가 아님


def test_unknown_error_keeps_its_code():
    assert ptt_error_text("jarvis_busy:working").startswith("jarvis_busy: ")
    assert ptt_error_text("mic_denied").startswith("mic_denied: 녹음을 시작하지 못했습니다(mic_denied)")
    assert ptt_error_text("").startswith("ptt_failed: ")
