"""사람이 아니면 못 푸는 실패는 조용히 지나가면 안 된다.

2026-08-05: 네이버 편집기에서 막힌 채로 자비스가 "준비를 완벽하게 마쳤습니다"라고
답했다. 도구 결과는 실패였는데 그 사실이 사람에게 닿는 경로가 없었다 — 진행 목록에
회색 줄 하나로 남을 뿐이었다.

여기서 검증하는 두 가지:
1) 사람이 아니면 못 푸는 것(봇 확인·로그인·반쯤 채워진 폼·확인 못 한 저장)만 올린다
2) 에이전트가 스스로 회복하는 실패(셀렉터 못 찾음 등)로는 울리지 않는다
   — 잦은 경보는 무시되고, 무시되는 경보는 없는 것과 같다
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.attention import AttentionService, classify
from alture_jarvis.events import EventBus


class _Notifications:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def notify(self, title: str, message: str) -> dict[str, Any]:
        self.sent.append((title, message))
        return {"ok": True}


def _service() -> tuple[AttentionService, EventBus, _Notifications, list[str]]:
    events = EventBus()
    notifications = _Notifications()
    spoken: list[str] = []
    service = AttentionService(events, notifications, spoken.append)
    return service, events, notifications, spoken


def _failed(error: str) -> dict[str, Any]:
    return {"ok": False, "error": error, "status": "failed", "result": {}}


def test_a_bot_check_calls_a_person() -> None:
    assert classify(_failed("search_blocked:google")) is not None
    assert classify(_failed("naver_blog_manual_intervention_required")) is not None


def test_a_half_filled_form_calls_a_person() -> None:
    rule = classify(_failed("fill_form_stopped_at:3/7:ref_12:timeout"))
    assert rule is not None and rule.code == "form_partially_filled"


def test_a_click_we_could_not_verify_calls_a_person() -> None:
    """실패가 아니라 **모름**이다. 다시 누르면 두 번 저장될 수 있어 사람이 봐야 한다."""
    observation = {"ok": True, "result": {"action": "clicked", "verified": False}}
    rule = classify(observation)
    assert rule is not None and rule.code == "change_not_verified"


def test_a_failed_project_test_is_repair_evidence_not_human_attention() -> None:
    observation = {
        "ok": True,
        "result": {
            "action": "local_run_project_command",
            "exit_code": 1,
            "verified": False,
            "failure_kind": "test_assertion",
            "failure_fingerprint": "abc123",
        },
    }
    assert classify(observation) is None


def test_ordinary_recoverable_failures_stay_quiet() -> None:
    assert classify(_failed("selector_not_found:.btn")) is None
    assert classify(_failed("stale_element_ref:take_a_new_snapshot")) is None
    assert classify(_failed("duplicate_action_blocked")) is None
    assert classify({"ok": True, "result": {"action": "clicked", "verified": True}}) is None


def test_a_notice_reaches_screen_notification_and_voice() -> None:
    service, events, notifications, spoken = _service()

    notice = service.check(
        job_id="job-1", tool="browser_search", arguments={}, observation=_failed("captcha")
    )

    assert notice is not None and notice["code"] == "bot_check"
    published = [e.to_dict() for e in events.get_since(0, 50)]
    assert any(e["event"] == "attention_required" for e in published), "화면 카드가 안 뜬다"
    assert notifications.sent, "윈도우 알림이 안 나갔다"
    assert spoken, "음성으로 알리지 않았다"


def test_the_same_cause_only_rings_once_per_job() -> None:
    service, _events, _notifications, spoken = _service()

    first = service.check(job_id="j", tool="browser_search", arguments={}, observation=_failed("captcha"))
    second = service.check(job_id="j", tool="browser_search", arguments={}, observation=_failed("captcha"))

    assert first is not None
    assert second is None
    assert len(spoken) == 1


def test_repeated_ordinary_failures_eventually_call_a_person() -> None:
    """한 번은 흔하다. 같은 도구가 계속 막히면 화면이 예상과 다른 상태다."""
    service, _events, _notifications, _spoken = _service()
    observation = _failed("selector_not_found:.btn")

    outcomes = [
        service.check(job_id="j", tool="browser_click", arguments={}, observation=observation)
        for _ in range(3)
    ]

    assert outcomes[0] is None and outcomes[1] is None
    assert outcomes[2] is not None and outcomes[2]["code"] == "repeated_failure"


def test_a_job_does_not_ring_forever() -> None:
    service, _events, _notifications, spoken = _service()
    for error in ("captcha", "login_required", "browser_action_timeout", "fill_form_stopped_at:1/2:r:x"):
        service.check(job_id="j", tool="browser_click", arguments={}, observation=_failed(error))

    assert len(spoken) == 3, "한 작업에서 울릴 수 있는 횟수를 넘겼다"


def test_the_agent_loop_raises_it_and_tells_the_model() -> None:
    """도구 결과가 지나는 길목에 실제로 물려 있는지. 서비스만 맞고 배선이 빠지면
    테스트는 다 통과하면서 화면에는 아무것도 안 뜬다 — 오늘 아침에 그런 종류의 버그를
    이미 한 번 봤다."""
    from alture_jarvis.agent import BrowserAgent

    service, events, _notifications, spoken = _service()
    agent = object.__new__(BrowserAgent)
    agent.events = events
    agent.attention = service
    messages: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []

    agent._record_observation(
        job_id="job-9",
        name="browser_fill_form",
        arguments={},
        step_number=1,
        label="양식 채우기",
        observation=_failed("fill_form_stopped_at:2/5:ref_3:timeout"),
        steps=steps,
        messages=messages,
        evidence_urls=[],
        last_action_ids={},
        tool_numbers=set(),
            tool_numbers_body=set(),
    )

    assert any(e.to_dict()["event"] == "attention_required" for e in events.get_since(0, 50))
    assert spoken
    # 모델도 알아야 우회하거나 "완료했습니다"라고 답하지 않는다.
    assert any("사용자에게 알렸다" in str(m.get("content")) for m in messages)


def test_disabled_service_stays_silent() -> None:
    events = EventBus()
    service = AttentionService(events, None, None, enabled=False)

    assert service.check(job_id="j", tool="t", arguments={}, observation=_failed("captcha")) is None
    assert not events.get_since(0, 10)
