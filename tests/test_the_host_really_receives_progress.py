"""진행이 **실제로** 호스트까지 가는가 — 이음새 시험 (2026-09-28 레딧 판).

`LiveProgress`(진행을 모은다)와 `summarize_job`(진행을 요약에 싣는다)은 각각 시험이 있었다. 그런데 둘을 잇는
MCP 다리가 `/v1/jobs/{id}/live` 를 **토큰 없이** 불러 401 을 받았고, 그 실패는 「진행은 덤」이라며 삼켜졌다.
그래서 클로드 쪽에는 14걸음 일하는 4분 내내 `steps: 0` 과 빈 진행만 갔다. 조각이 다 맞아도 잇는 선이 끊기면 없는 기능이다.
"""

import asyncio
import json

import httpx

from alture_jarvis.mcp_server import JarvisMcpBridge

TOKEN = "t0ken"
JOB = {"id": "j1", "status": "running", "started_at": 1.0, "result": None}
LIVE = {"job_id": "j1", "doing": "레딧 댓글을 읽는 중", "step": 11, "updated_at": 1.0,
        "requested": {"met": 1, "total": 2, "items": [{"label": "댓글 분류", "met": False, "saw": ""}]}}


def _handler(request: httpx.Request) -> httpx.Response:
    # 운영 API 처럼 /live 는 토큰이 있어야 연다(api.py `require_token`).
    if request.url.path.endswith("/live"):
        if request.headers.get("X-JARVIS-TOKEN") != TOKEN:
            return httpx.Response(401, json={"detail": "unauthorized"})
        return httpx.Response(200, json=LIVE)
    if request.url.path == "/v1/jobs/j1":
        return httpx.Response(200, json=JOB)
    return httpx.Response(404)


def _status() -> dict:
    async def run() -> dict:
        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        bridge = JarvisMcpBridge("http://ontelic.test", TOKEN, client=client)
        text, _error = await bridge._delegate("sonjari_task_status", {"job_id": "j1", "wait_sec": 0})
        await client.aclose()
        return json.loads(text)

    return asyncio.run(run())


def test_progress_reaches_the_host_while_the_job_runs():
    summary = _status()
    assert summary["status"] == "running"
    assert summary["progress"]["doing"] == "레딧 댓글을 읽는 중"
    assert "레딧 댓글을 읽는 중" in summary["message"]


def test_steps_are_counted_while_running_not_only_at_the_end():
    # 걸음 기록은 판이 끝나야 저장된다. 일하는 동안 「0걸음」이면 호스트는 멈춘 줄 안다.
    assert _status()["steps"] == 11
