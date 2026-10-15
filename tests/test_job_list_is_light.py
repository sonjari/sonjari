"""목록은 미리보기만 — 답변 전문과 첨부를 싣지 않는다.

2026-08-19 실측: `/v1/jobs?limit=50` 이 **455KB** 였다. payload 는 다 합쳐 18KB
뿐이고 **299KB 가 result_json**(답변 전문 + 도구 걸음 전부)이었다. 사이드바 한
줄은 제목·상태·소요·걸음수만 그리므로 그 전부가 버려진다.

첨부가 있으면 더 나쁘다 — `payload.attachments[].data_base64` 가 그대로 들어
있어서(한 개 상한 48MB) 목록 한 번이 수백 MB 가 될 수 있다. 지금 DB 에 그런
줄이 0개라 안 터졌을 뿐이고, 이건 사고 N(큰 응답이 통과 중에 끊김)과 같은 모양이다.

여기서 못 박는 것 둘:
  1. `view=summary` 는 본문을 **안 싣는다**
  2. 기본값(`full`)은 예전 그대로다 — 벤치·스크립트가 이 경로를 이미 쓴다
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.models import JobStatus


def _config(tmp_path) -> JarvisConfig:
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )


def _heavy_job(runtime) -> str:
    job = runtime.store.create_job(
        "chat",
        "크몽에서 시장 조사를 해줘",
        {
            "prompt": "크몽에서 시장 조사를 해줘",
            "session_id": "office-main",
            "origin": "workspace",
            # 첨부는 이 자리에 base64 로 들어온다. 목록에 실리면 안 되는 것의 표본이다.
            "attachments": [{"name": "표.csv", "mime_type": "text/csv", "data_base64": "A" * 20_000}],
        },
    )
    job_id = str(job["id"])
    runtime.store.set_status(
        job_id,
        JobStatus.COMPLETED,
        result={
            "answer": "답" * 8_000,
            "completion_state": "complete",
            "agent_trace": {
                "steps": [{"step": i, "tool": "browser_extract", "ok": True} for i in range(22)],
                "verification": {"sources": 6},
            },
        },
    )
    return job_id


def test_summary_view_carries_the_row_without_the_body(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    with TestClient(app) as client:
        job_id = _heavy_job(runtime)
        rows = client.get("/v1/jobs?view=summary").json()

    assert len(rows) == 1
    row = rows[0]
    # 한 줄을 그리는 데 필요한 것은 전부 있다.
    assert row["id"] == job_id
    assert row["status"] == "completed"
    assert row["risk_level"] == "L0"
    assert row["session_id"] == "office-main"
    assert row["steps"] == 22
    assert row["completion_state"] == "complete"
    assert row["title"] == "크몽에서 시장 조사를 해줘"
    # 본문은 없다. 이름만 없애고 값이 다른 칸으로 새는 일이 없도록 통째로 확인한다.
    assert "payload" not in row and "result" not in row
    serialized = json.dumps(row, ensure_ascii=False)
    assert "AAAA" not in serialized
    assert "답답답" not in serialized


def test_summary_is_an_order_of_magnitude_smaller(tmp_path) -> None:
    """"가벼워졌다"를 감으로 말하지 않는다 — 두 응답의 바이트를 직접 잰다."""
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    with TestClient(app) as client:
        for _ in range(5):
            _heavy_job(runtime)
        full = len(client.get("/v1/jobs").content)
        summary = len(client.get("/v1/jobs?view=summary").content)

    assert summary * 10 < full, f"full={full}B summary={summary}B — 목록이 아직 무겁다"


def test_default_view_is_unchanged(tmp_path) -> None:
    """벤치·스크립트가 이미 이 경로를 쓴다. 기본값을 바꾸면 그쪽이 조용히 깨진다."""
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    with TestClient(app) as client:
        _heavy_job(runtime)
        row = client.get("/v1/jobs").json()[0]

    assert row["payload"]["prompt"] == "크몽에서 시장 조사를 해줘"
    assert row["result"]["completion_state"] == "complete"
