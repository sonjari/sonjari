"""일 조회 문(`/v1/jobs/{id}`)이 바깥 AI 가 맡긴 일의 답을 **토큰 없이 읽으면 정제해서** 준다 (2026-10-15).

10-15 아침 끝까지 시험해 보니: 정제(`outbound.refine`)는 MCP 연결 프로세스 안(`delegation.summarize_job`)에서 일어나는데, 떠 있는
연결 프로세스는 호스트 세션마다 하나씩 며칠을 산다. 어제 뜬 옛 프로세스는 정제를 몰라서 **화면 영수증은 「정제 2」인데 바깥 AI 에게는
원문(전화 · 메일)이 갔다.** 그리고 이 문은 토큰 없이 열려 있어서 이 PC 의 아무 프로그램이나 맡긴 일의 답을 읽을 수 있었다.

그래서 정제를 **백엔드 한 곳**에서 한다:
- 토큰 없이 읽으면 — 연결 프로세스가 옛것이든 새것이든 이 길이다 — 바깥 AI 가 맡긴 일(origin=mcp)의 답은 정제한 판이 나간다.
  밝힌 연락처(`needs`)는 그대로, 주민번호 · 카드 번호 · 비밀 키는 늘 가린다(`outbound.refine` 과 같은 규칙).
- 토큰을 들고 읽으면(이 PC 의 화면) 원문 그대로다 — 기록은 이 PC 에 원문으로 남는다.
- 사람이 직접 시킨 일은 지금처럼 그대로다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

ANSWER = "담당자 연락처 010-1234-5678 · 메일 someone@example.com · 가격 129,000원"


def _app(tmp_path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False)
    return create_app(config, start_services=False)


def _job(app, payload: dict) -> str:
    runtime = app.state.jarvis
    job = runtime.store.create_job("chat", "t", payload)
    runtime.store.attach_result(job["id"], {"answer": ANSWER, "agent_trace": {"steps": []}})
    return job["id"]


def test_a_delegated_answer_is_refined_without_the_token(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        job_id = _job(app, {"prompt": "연락처 찾아", "origin": "mcp"})
        body = client.get(f"/v1/jobs/{job_id}").json()
    answer = body["result"]["answer"]
    assert "010-1234-5678" not in answer and "someone@example.com" not in answer
    assert "129,000원" in answer
    assert body["result"]["outbound"]["refined"] == [{"kind": "전화번호", "count": 1}, {"kind": "메일 주소", "count": 1}]


def test_contacts_named_in_needs_go_out(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        job_id = _job(app, {"prompt": "연락처 찾아", "origin": "mcp", "needs": ["연락처"]})
        answer = client.get(f"/v1/jobs/{job_id}").json()["result"]["answer"]
    assert "010-1234-5678" in answer and "someone@example.com" in answer


def test_the_screen_with_the_token_reads_the_original(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        job_id = _job(app, {"prompt": "연락처 찾아", "origin": "mcp"})
        body = client.get(f"/v1/jobs/{job_id}", headers={"X-JARVIS-TOKEN": "test-token"}).json()
    assert body["result"]["answer"] == ANSWER


def test_a_job_the_person_gave_is_left_alone(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        job_id = _job(app, {"prompt": "연락처 찾아", "origin": "chat"})
        assert client.get(f"/v1/jobs/{job_id}").json()["result"]["answer"] == ANSWER
