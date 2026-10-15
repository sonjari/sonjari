"""큰 플랫폼이 우리를 부르면, 호스트 채팅에서도 「지금 무엇을 하는 중인지」 보인다 (2026-09-22, 사장님 스크린샷).

## 무엇이 비어 있었나

온텔릭 화면은 기다림을 지루하지 않게 한다 — 걸음 표시, 실제 화면, 「시킨 것 2/3」, 근거를 몇 곳에서 읽었는지. 그런데 MCP 로 부르면
사용자는 **그 화면이 아니라 호스트 채팅만** 본다. 거기에는 「일하는 중, 0걸음」만 나왔다.

정보는 이미 있었다. 에이전트가 `agent_progress`·`agent_plan` 이벤트로 **흘려보낼 뿐** 어디에도 저장하지 않아 HTTP 로 조회할 수 없었다.

## 지킬 것

1. 진행 이벤트의 최신 값만 작업별로 들고 있다가(`LiveProgress`) `/v1/jobs/{id}/live` 로 내준다 — 토큰이 있어야 한다.
2. 진행 중 요약에 `progress`(지금 하는 일 · 시킨 것 n/m · 마지막 소식이 몇 초 전)와 호스트가 그대로 옮길 한두 문장이 실린다.
3. **남은 시간 예측은 어디에도 싣지 않는다.** 화면의 「3분 남음」이 얼마나 맞는지 재 본 적이 없다 — 틀린 예측을 호스트가 전하면 신뢰를 깎는다.
4. **진행 표시가 작업을 막으면 안 된다** — 청취 실패는 삼키고, 청취자는 잠금 밖에서 불린다.
5. 진행 정보를 못 받아도 상태는 나간다(덤이다).
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.delegation import STATUS_TOOL, summarize_job
from alture_jarvis.events import EventBus
from alture_jarvis.live_progress import LiveProgress, without_eta
from alture_jarvis.mcp_server import JarvisMcpBridge
from alture_jarvis.models import EventRecord


def _event(event: str, **payload: Any) -> EventRecord:
    return EventRecord(seq=1, event=event, timestamp=1_000.0, payload=payload)


# --- 저장소 -----------------------------------------------------------------------

def test_the_latest_progress_of_a_job_is_kept() -> None:
    live = LiveProgress()
    live.on_event(_event("agent_progress", job_id="j", phase="tool", message="웹에서 ‘넥스세라’ 검색 중", step=3, tool="browser_search"))
    live.on_event(_event("agent_progress", job_id="j", phase="tool", message="웹페이지를 여는 중", step=4, tool="browser_open"))

    snap = live.snapshot("j")

    assert snap["doing"] == "웹페이지를 여는 중" and snap["step"] == 4 and snap["tool"] == "browser_open"


def test_the_step_never_goes_backwards() -> None:
    live = LiveProgress()
    live.on_event(_event("agent_progress", job_id="j", message="a", step=9))
    live.on_event(_event("agent_progress", job_id="j", message="정리 중", step=0))  # 걸음 없는 안내문

    assert live.snapshot("j")["step"] == 9 and live.snapshot("j")["doing"] == "정리 중"


def test_the_requested_items_come_from_the_plan_event_and_are_capped() -> None:
    live = LiveProgress()
    items = [{"label": "긴 이름 " * 30, "met": i < 2, "saw": "본 것 " * 40} for i in range(12)]
    live.on_event(_event("agent_plan", job_id="j", items=items, met=2, total=12))

    requested = live.snapshot("j")["requested"]

    assert requested["met"] == 2 and requested["total"] == 12
    assert len(requested["items"]) == 8
    assert all(len(i["label"]) <= 60 and len(i["saw"]) <= 80 for i in requested["items"])


def test_the_eta_the_screen_shows_is_never_kept() -> None:
    """화면 문구의 「3분 남음」 — 얼마나 맞는지 재 본 적이 없어 호스트에게 넘기지 않는다."""
    live = LiveProgress()
    live.on_event(_event("agent_progress", job_id="j", message="계속 진행합니다 — 1곳에서 읽음(www.saramin.co.kr) · 남은 것: 파일 만들기 · 3분 남음"))
    live.on_event(_event("agent_progress", job_id="k", message="계속 진행합니다 — 아직 읽은 본문 없음 · 1분 미만 남음"))

    assert live.snapshot("j")["doing"] == "계속 진행합니다 — 1곳에서 읽음(www.saramin.co.kr) · 남은 것: 파일 만들기"
    assert "남음" not in live.snapshot("k")["doing"]


def test_only_a_trailing_eta_is_removed() -> None:
    assert without_eta("웹페이지를 여는 중") == "웹페이지를 여는 중"
    assert without_eta("남음 표시가 글 중간에 있는 문장입니다") == "남음 표시가 글 중간에 있는 문장입니다"
    assert without_eta("") == ""


def test_jobs_do_not_leak_into_each_other() -> None:
    live = LiveProgress()
    live.on_event(_event("agent_progress", job_id="a", message="A 하는 중"))
    live.on_event(_event("agent_progress", job_id="b", message="B 하는 중"))

    assert live.snapshot("a")["doing"] == "A 하는 중" and live.snapshot("b")["doing"] == "B 하는 중"
    assert live.snapshot("nope") == {} and live.snapshot("") == {}


def test_the_oldest_jobs_are_dropped_first() -> None:
    live = LiveProgress(max_jobs=3)
    for name in ("a", "b", "c", "d"):
        live.on_event(_event("agent_progress", job_id=name, message=name))

    assert live.snapshot("a") == {} and live.snapshot("d")["doing"] == "d"


def test_a_snapshot_is_a_copy() -> None:
    live = LiveProgress()
    live.on_event(_event("agent_plan", job_id="j", items=[{"label": "x", "met": False}], met=0, total=1))

    live.snapshot("j")["requested"]["items"].append({"label": "낙서"})

    assert len(live.snapshot("j")["requested"]["items"]) == 1


def test_junk_events_never_raise_and_other_events_are_ignored() -> None:
    live = LiveProgress()
    live.on_event(_event("agent_progress", job_id="j", step="abc", message=None))       # 깨진 값
    live.on_event(EventRecord(seq=1, event="agent_progress", timestamp=0.0, payload=None))  # type: ignore[arg-type]
    live.on_event(_event("job_created", job_id="z", message="상관없음"))

    assert live.snapshot("z") == {}


# --- 이벤트 버스 ------------------------------------------------------------------

def test_a_broken_listener_cannot_stop_publishing_or_the_others() -> None:
    bus = EventBus()
    seen: list[str] = []

    def broken(record: EventRecord) -> None:
        raise RuntimeError("청취자가 죽었다")

    bus.add_listener(broken)
    bus.add_listener(lambda record: seen.append(record.event))

    record = bus.publish("agent_progress", {"job_id": "j"})

    assert record.event == "agent_progress" and seen == ["agent_progress"]
    assert bus.sequence == 1


def test_a_listener_may_publish_again_without_deadlocking() -> None:
    """청취자는 잠금 밖에서 불린다 — 청취자 안에서 또 발행해도 멈추지 않는다."""
    bus = EventBus()
    order: list[str] = []

    def echo(record: EventRecord) -> None:
        order.append(record.event)
        if record.event == "first":
            bus.publish("second", {})

    bus.add_listener(echo)
    bus.publish("first", {})

    assert order == ["first", "second"]


def test_the_runtime_feeds_the_store_from_its_event_bus(tmp_path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="t", camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    runtime = app.state.jarvis

    runtime.events.publish("agent_progress", {"job_id": "j9", "phase": "tool", "message": "웹페이지를 여는 중", "step": 2, "tool": "browser_open"})

    assert runtime.live.snapshot("j9")["doing"] == "웹페이지를 여는 중"


# --- 조회 주소 ---------------------------------------------------------------------

def test_the_live_endpoint_needs_the_token_and_returns_the_latest(tmp_path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    app.state.jarvis.events.publish("agent_plan", {"job_id": "j1", "items": [{"label": "사람인에서 하기", "met": True, "saw": "1건"}], "met": 1, "total": 3})
    app.state.jarvis.events.publish("agent_progress", {"job_id": "j1", "phase": "tool", "message": "본문을 읽는 중 · 3분 남음", "step": 5})
    headers = {"X-JARVIS-TOKEN": "test-token"}

    with TestClient(app) as client:
        assert client.get("/v1/jobs/j1/live").status_code == 401
        body = client.get("/v1/jobs/j1/live", headers=headers).json()
        empty = client.get("/v1/jobs/unknown/live", headers=headers).json()

    assert body["doing"] == "본문을 읽는 중" and body["step"] == 5  # 남은 시간은 떨어져 나갔다
    assert body["requested"]["met"] == 1 and body["requested"]["total"] == 3
    assert empty == {}


# --- 요약 -------------------------------------------------------------------------

_LIVE = {
    "doing": "웹에서 ‘넥스세라’ 검색 중", "step": 11, "updated_at": 1_000.0,
    "requested": {"met": 2, "total": 3, "items": [
        {"label": "사람인에서 하기", "met": True, "saw": "1건"},
        {"label": "근거가 되는 대상 실제로 읽기", "met": True, "saw": "4개 실제로 읽음"},
        {"label": "실제 산출물 파일 만들기", "met": False, "saw": "열 수 있는 산출물 없음"},
    ]},
}


def test_a_running_summary_carries_what_the_work_is_doing() -> None:
    summary = summarize_job({"id": "j", "status": "running", "result": None}, live=_LIVE, now=1_010.0)

    progress = summary["progress"]
    assert progress["doing"] == "웹에서 ‘넥스세라’ 검색 중" and progress["step"] == 11
    assert progress["requested"]["met"] == 2 and progress["requested"]["total"] == 3
    assert progress["seconds_since_update"] == 10
    # 호스트가 그대로 옮길 문장
    assert "지금: 웹에서 ‘넥스세라’ 검색 중." in summary["message"]
    assert "시킨 것 2/3 채웠습니다." in summary["message"]
    assert "남은 것: 실제 산출물 파일 만들기." in summary["message"]


def test_no_remaining_time_is_ever_promised_to_the_host() -> None:
    summary = summarize_job({"id": "j", "status": "running", "result": None, "started_at": 990.0}, live=_LIVE, now=1_010.0)

    text = json.dumps(summary, ensure_ascii=False)

    assert "남음" not in text and "남았" not in text


def test_a_quiet_job_is_said_to_be_quiet() -> None:
    summary = summarize_job({"id": "j", "status": "running", "result": None}, live=_LIVE, now=1_000.0 + 300)

    assert summary["progress"]["seconds_since_update"] == 300
    assert "마지막 소식이 5분 전입니다." in summary["message"]


def test_without_live_the_running_summary_is_what_it_always_was() -> None:
    summary = summarize_job({"id": "j", "status": "running", "result": None})

    assert "progress" not in summary
    assert summary["message"] == "일하는 중입니다. 잠시 뒤 sonjari_task_status 를 다시 부르세요."


def test_a_queued_job_has_no_progress_to_report() -> None:
    summary = summarize_job({"id": "j", "status": "queued", "result": {}}, ahead=1, live=_LIVE)

    assert "progress" not in summary and "앞에 1개" in summary["message"]


def test_an_approval_wait_keeps_its_message_and_still_shows_where_it_stopped() -> None:
    summary = summarize_job({"id": "j", "status": "waiting_approval", "result": {}}, live=_LIVE, now=1_005.0)

    assert summary["status"] == "needs_approval" and "승인" in summary["message"]
    assert summary["progress"]["doing"] == "웹에서 ‘넥스세라’ 검색 중"


def test_a_finished_job_ignores_live() -> None:
    job = {"id": "j", "status": "completed", "result": {"answer": "끝", "completion_state": "complete",
                                                       "agent_trace": {"steps": [], "tool_numbers": [], "tool_numbers_body": []}}}

    assert "progress" not in summarize_job(job, live=_LIVE)


# --- MCP 다리: 끝에서 끝까지 ---------------------------------------------------------

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
    def __init__(self, job: dict[str, Any], live: Any = None, live_status: int = 200, live_raises: bool = False) -> None:
        self.job, self.live, self.live_status, self.live_raises = job, live, live_status, live_raises
        self.urls: list[str] = []

    async def get(self, url: str, headers: dict[str, str] | None = None) -> Any:
        self.urls.append(url)
        if url.endswith("/live"):
            if self.live_raises:
                raise RuntimeError("연결 끊김")
            # ★ 운영처럼 토큰을 요구한다(2026-09-28). 이 가짜가 토큰을 안 봐서 운영의 401 을 4일 동안 못 잡았다.
            if (headers or {}).get("X-JARVIS-TOKEN") != "t":
                return _Response({"detail": "unauthorized"}, 401)
            return _Response(self.live, self.live_status)
        return _Response(self.job)

    async def aclose(self) -> None:
        return None


def _status(client: _Client) -> dict[str, Any]:
    bridge = JarvisMcpBridge(token="t", client=client)
    text, _failed = asyncio.run(bridge.call("sonjari_task_status", {"job_id": "j", "wait_sec": 0}))
    return json.loads(text)


def test_the_host_chat_gets_the_live_progress_end_to_end() -> None:
    client = _Client({"id": "j", "status": "running", "result": None}, live=_LIVE)

    body = _status(client)

    assert body["status"] == "running"
    assert body["progress"]["requested"]["total"] == 3
    assert "시킨 것 2/3 채웠습니다." in body["message"]
    assert any(url.endswith("/v1/jobs/j/live") for url in client.urls)


def test_a_finished_job_is_not_asked_for_progress() -> None:
    job = {"id": "j", "status": "completed", "result": {"answer": "끝", "completion_state": "complete",
                                                        "agent_trace": {"steps": [], "tool_numbers": [], "tool_numbers_body": []}}}
    client = _Client(job, live=_LIVE)

    _status(client)

    assert not any(url.endswith("/live") for url in client.urls)


def test_missing_progress_never_breaks_the_status() -> None:
    for client in (
        _Client({"id": "j", "status": "running", "result": None}, live_status=404),
        _Client({"id": "j", "status": "running", "result": None}, live_raises=True),
        _Client({"id": "j", "status": "running", "result": None}, live={}),
    ):
        body = _status(client)

        assert body["status"] == "running" and "progress" not in body


# --- 배선 -------------------------------------------------------------------------

def test_the_runtime_registers_the_listener_and_the_host_is_told_how_to_use_it() -> None:
    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime.__init__)
    assert "self.events.add_listener(self.live.on_event)" in source

    description = STATUS_TOOL["description"]
    assert "progress.doing" in description and "progress.requested" in description
    assert "예측해 주지 않습니다" in description and "지어 말하지 마세요" in description
