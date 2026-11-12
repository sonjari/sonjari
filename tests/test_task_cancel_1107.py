"""맡긴 과제를 멈추는 문 `sonjari_task_cancel` (2026-11-07 · Glama Completeness 3/5).

양방향:
- 해야 할 것: 바깥 AI 가 맡긴 일(origin mcp)은 멈춘다 · 이미 끝난 일은 오류 없이 「멈출 것 없음」 · 목록에 나온다(영어 설명도).
- 하면 안 되는 것: 사람이 손자리 창에서 시킨 일은 job_id 를 알아도 못 멈춘다(취소 길을 부르지도 않는다) ·
  늘 실어 두는 문(alwaysLoad)에 끼지 않는다 — 클로드 앞부분을 키우지 않는다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from alture_jarvis.delegation import CANCEL_TOOL, DELEGATION_TOOLS, localized_tool
from alture_jarvis.mcp_server import ALWAYS_LOAD, JarvisMcpBridge


class _Response:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        assert self.status_code < 400


class _Client:
    def __init__(self, job: dict[str, Any] | None, cancel_status: int = 200) -> None:
        self.job = job
        self.cancel_status = cancel_status
        self.posts: list[str] = []

    async def get(self, url: str, headers: dict[str, str] | None = None) -> Any:
        if url.endswith("/v1/tools"):
            return _Response([])
        if self.job is None:
            return _Response({"detail": "not found"}, 404)
        return _Response(self.job)

    async def post(self, url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:  # noqa: A002
        self.posts.append(url)
        if self.cancel_status != 200:
            return _Response({"detail": "job_not_cancellable"}, self.cancel_status)
        return _Response({"ok": True, "job_id": "j1"})

    async def aclose(self) -> None:
        return None


def _call(client: _Client, lang: str = "ko") -> tuple[str, bool]:
    bridge = JarvisMcpBridge(token="t", client=client)
    bridge.lang = lang
    return asyncio.run(bridge.call("sonjari_task_cancel", {"job_id": "j1"}))


def test_a_task_an_outside_ai_handed_off_is_stopped() -> None:
    client = _Client({"id": "j1", "status": "running", "payload": {"origin": "mcp"}})
    text, failed = _call(client)
    assert not failed and json.loads(text)["cancelled"] is True
    assert client.posts == ["http://127.0.0.1:8091/v1/jobs/j1/cancel"]


def test_work_a_person_started_in_the_window_is_not_stopped() -> None:
    client = _Client({"id": "j1", "status": "running", "payload": {"origin": "ui"}})
    text, failed = _call(client)
    assert failed and "손자리 창" in text
    assert client.posts == []  # 취소 길을 부르지도 않는다


def test_a_finished_task_says_nothing_to_stop_without_failing() -> None:
    client = _Client({"id": "j1", "status": "completed", "payload": {"origin": "mcp"}}, cancel_status=409)
    text, failed = _call(client)
    body = json.loads(text)
    assert not failed and body["cancelled"] is False and body["status"] == "completed"


def test_an_unknown_job_id_is_reported() -> None:
    text, failed = _call(_Client(None))
    assert failed and "j1" in text


def test_english_connection_gets_english_refusal() -> None:
    text, failed = _call(_Client({"id": "j1", "status": "running", "payload": {"origin": "ui"}}), lang="en")
    assert failed and "Sonjari window" in text


def test_the_cancel_door_is_listed_but_not_always_loaded() -> None:
    assert CANCEL_TOOL in DELEGATION_TOOLS
    assert CANCEL_TOOL["name"] not in ALWAYS_LOAD
    names = [tool["name"] for tool in asyncio.run(JarvisMcpBridge(token="t", client=_Client(None)).list_tools())]
    assert "sonjari_task_cancel" in names
    english = localized_tool(CANCEL_TOOL, "en")
    assert english["description"].startswith("Stop a task") and not any("가" <= ch <= "힣" for ch in english["description"])
