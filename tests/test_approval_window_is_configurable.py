"""승인 창은 **조절 가능해야 하고, 잡보다 먼저 죽으면 안 된다.**

## 왜 이 시험이 생겼나 (2026-08-14)

`ToolGateway.__init__` 의 `approval_ttl_sec: int = 300` 이 클래스 기본값으로 박혀 있고
`runtime.py` 가 `ToolGateway(store, events)` 로 **인자 없이** 만들었다. env 변수도 없었다.
그래서 5분은 **아무도 못 고치는 값**이었다.

그 5분이 뭘 했나. 체크포인트는 1800초를 사는데 승인은 300초에 죽는다 — 되살릴 수
있는 잡을 승인이 없어서 못 되살린다. 실측(승인 20건): 만료 3 · 미응답 4, 그중 셋은
**열흘째** `waiting_approval` 로 남아 있었다.

그리고 이건 불편이 아니라 **위임의 천장**이었다. L4 의 정의가 "맡겨 놓고 잊어도
되는가"인데, 승인이 5분에 죽으면 자리를 비우는 순간 반드시 실패한다.

## 무엇을 지키나

사고 Q 의 교훈 그대로 — 상한이 사는 자리는 셋이고(dataclass 기본값 · env 로더 ·
함수 안 하드 상수) **하나만 고치면 낮은 쪽이 계속 일한다.** 그래서 셋을 다 건다.
"""

from __future__ import annotations

import time

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import ApprovalRequired, JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec


def test_the_approval_outlives_the_job_it_belongs_to() -> None:
    """승인은 **그 잡을 되살릴 수 있는 동안** 살아 있어야 한다.

    이 부등식이 깨지면 "승인은 받았는데 실행이 안 됨"이 구조적으로 생긴다.
    """
    config = JarvisConfig()
    assert config.approval_ttl_sec >= config.agent_checkpoint_ttl_sec, (
        f"승인({config.approval_ttl_sec}초)이 체크포인트({config.agent_checkpoint_ttl_sec}초)보다 "
        "먼저 죽는다 — 되살릴 수 있는 잡을 승인이 없어서 못 되살린다"
    )


def test_the_env_var_actually_reaches_the_dataclass(monkeypatch) -> None:
    """env 로더에 안 넣으면 dataclass 만 고치고 헛돈다(사고 Q 의 첫 줄)."""
    monkeypatch.setenv("JARVIS_APPROVAL_TTL_SEC", "2400")
    assert JarvisConfig.from_env().approval_ttl_sec == 2400
    monkeypatch.setenv("JARVIS_APPROVAL_REMINDER_LEAD_SEC", "420")
    assert JarvisConfig.from_env().approval_reminder_lead_sec == 420


def test_the_gateway_uses_the_value_it_is_given(tmp_path) -> None:
    """마지막 자리 — **함수 안 하드 상수**. 여기가 제일 안 보인다.

    `runtime.py` 가 인자 없이 만들면 클래스 기본값이 그대로 살아서, config 를
    고쳐도 아무 일이 안 일어난다. 그 상태가 실제로 몇 달 갔다.
    """
    gateway = ToolGateway(
        JobStore(tmp_path / "j.db"), EventBus(), approval_ttl_sec=1234
    )
    assert gateway.approval_ttl_sec == 1234


def test_the_runtime_wires_config_into_the_gateway() -> None:
    """진짜 배선. 위 셋이 다 맞아도 이 줄이 빠지면 전부 헛것이다.

    런타임 전체를 띄우지 않고 **소스에서 확인**한다 — 런타임은 브라우저·모델·
    카메라를 다 물고 올라와서 시험에서 세울 수가 없다.
    """
    import inspect

    from alture_jarvis import runtime

    source = inspect.getsource(runtime)
    assert "approval_ttl_sec=self.config.approval_ttl_sec" in source, (
        "runtime 이 config 값을 게이트웨이에 안 넘긴다 — 인자 없이 만들면 "
        "클래스 기본값이 조용히 이긴다"
    )
    assert "approval_reminder_lead_sec=self.config.approval_reminder_lead_sec" in source


def test_an_approval_is_pushed_now_and_once_before_it_expires(tmp_path) -> None:
    class Notifications:
        def __init__(self) -> None:
            self.sent: list[tuple[str, str]] = []

        def notify(self, title: str, message: str) -> dict:
            self.sent.append((title, message))
            return {"ok": True}

    store = JobStore(tmp_path / "j.db")
    events = EventBus()
    notifications = Notifications()
    gateway = ToolGateway(
        store,
        events,
        approval_ttl_sec=0.35,
        approval_reminder_lead_sec=0.15,
        notifications=notifications,
    )
    gateway.register(
        ToolSpec(
            name="dangerous_write",
            description="사용자님 파일 수정",
            risk_level=RiskLevel.L2,
            handler=lambda arguments: {"ok": True},
        )
    )
    job = store.create_job("chat", "approval", {"prompt": "고쳐줘"})

    with pytest.raises(ApprovalRequired):
        gateway.execute("dangerous_write", {}, job_id=job["id"])

    assert len(notifications.sent) == 1
    time.sleep(0.25)
    assert len(notifications.sent) == 2
    assert any(event.event == "approval_reminder" for event in events.get_since(0))
