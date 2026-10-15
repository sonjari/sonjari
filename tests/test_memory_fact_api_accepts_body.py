"""「기억에 직접 넣기」·「잊기」 API 가 **본문**을 받는가 (2026-09-16 밤 실측).

요청 모델을 `create_app` 안에서 선언했더니 `from __future__ import annotations` 때문에 FastAPI 가
본문 대신 `?request=` 쿼리로 읽어 **모든 요청을 422** 로 거절했다. 사람이 기억을 고치는 유일한
문이 조용히 닫혀 있었다 — 전역 프로필의 개인 사실을 기억으로 옮기려다 드러났다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig


def _config(tmp_path) -> JarvisConfig:
    return JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False,
        voice_enabled=False, tts_enabled=False,
    )


def test_learn_then_forget_a_fact_through_the_real_app(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    headers = {"X-JARVIS-TOKEN": "test-token"}
    with TestClient(app) as client:
        learned = client.post(
            "/v1/memory/facts",
            json={"kind": "person", "subject": "사용자", "fact": "시험용 사실 한 줄"},
            headers=headers,
        )
        assert learned.status_code == 200, learned.text
        fact_id = learned.json()["fact_id"]

        forgot = client.post("/v1/memory/facts/forget", json={"fact_id": fact_id}, headers=headers)
        assert forgot.status_code == 200, forgot.text
