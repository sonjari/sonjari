"""되돌릴 수 없는 버튼에 막히면 **도구가 스스로** 승인 카드를 띄운다.

## 왜 이 시험이 생겼나 (2026-09-30 코드 벤치)

자기 앱의 「추가」(폼 submit)를 누르자 `browser_click` 이 「되돌릴 수 없는 동작 —
browser_click_confirmed 로 요청하라」는 **글**을 돌려줬다. 카드는 모델이 그 도구를 다시
불러야만 떴고, 코드 모드엔 그 도구가 없어 또 막혔다. 모델이 안 부르면 카드는 영영 안 뜬다.

대표: 「승인이 필요하면 왜 질문 카드를 안 던지나」.

## 무엇을 지키나

- 막힘 → 게이트웨이가 **같은 인자로** 승인 도구를 대신 불러 카드를 만든다(잡이면 멈춘다).
- 승인 뒤 재개는 **막혔던 그 호출**(`browser_click`)을 재생한다 — 같은 길로 승격돼 승인을 소비하고 눌린다.
- 다른 오류는 승격하지 않는다. 승인 없이 눌리는 길은 여전히 없다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import ApprovalRequired, JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec


def _gateway(tmp_path, clicked: list[dict]) -> tuple[ToolGateway, JobStore]:
    store = JobStore(tmp_path / "j.db")
    gateway = ToolGateway(store, EventBus())

    def plain_click(arguments: dict) -> dict:
        if arguments.get("ref") == "e9":
            raise RuntimeError("irreversible_click_needs_approval:결제하기 — 되돌릴 수 없는 동작입니다.")
        if arguments.get("ref") == "gone":
            raise RuntimeError("stale_ref:gone")
        clicked.append({"tool": "browser_click", **arguments})
        return {"ok": True}

    def confirmed_click(arguments: dict) -> dict:
        clicked.append({"tool": "browser_click_confirmed", **arguments})
        return {"ok": True, "clicked": arguments.get("ref")}

    gateway.register(ToolSpec(name="browser_click", description="누르기", risk_level=RiskLevel.L0,
                              handler=plain_click))
    gateway.register(ToolSpec(name="browser_click_confirmed", description="되돌릴 수 없는 버튼 누르기",
                              risk_level=RiskLevel.L2, handler=confirmed_click))
    gateway.approval_escalations["browser_click"] = (
        "irreversible_click_needs_approval", "browser_click_confirmed",
    )
    return gateway, store


def test_a_blocked_click_becomes_an_approval_card_without_the_model_asking(tmp_path) -> None:
    clicked: list[dict] = []
    gateway, store = _gateway(tmp_path, clicked)
    job = store.create_job("chat", "approval", {"prompt": "주문해 줘"})

    with pytest.raises(ApprovalRequired) as raised:
        gateway.execute("browser_click", {"ref": "e9"}, job_id=job["id"])

    approval = store.get_approval(raised.value.nonce)
    assert approval is not None
    assert approval["tool_name"] == "browser_click_confirmed"
    assert approval["arguments"] == {"ref": "e9"}
    assert clicked == [], "승인 전에는 아무것도 눌리면 안 된다"


def test_replaying_the_blocked_call_after_approval_presses_it_once(tmp_path) -> None:
    clicked: list[dict] = []
    gateway, store = _gateway(tmp_path, clicked)
    job = store.create_job("chat", "approval", {"prompt": "주문해 줘"})
    with pytest.raises(ApprovalRequired) as raised:
        gateway.execute("browser_click", {"ref": "e9"}, job_id=job["id"])
    store.decide_approval(raised.value.nonce, True)

    # 재개는 체크포인트의 `browser_click` 을 그대로 재생한다(agent 의 pending_tool_call).
    result = gateway.execute("browser_click", {"ref": "e9"}, job_id=job["id"])

    assert result.ok is True
    assert clicked == [{"tool": "browser_click_confirmed", "ref": "e9"}]
    # 승인은 한 번만 쓴다 — 같은 호출을 또 하면 새 카드다.
    with pytest.raises(ApprovalRequired):
        gateway.execute("browser_click", {"ref": "e9"}, job_id=job["id"])


def test_other_failures_are_not_escalated(tmp_path) -> None:
    clicked: list[dict] = []
    gateway, store = _gateway(tmp_path, clicked)
    job = store.create_job("chat", "approval", {"prompt": "눌러 줘"})

    result = gateway.execute("browser_click", {"ref": "gone"}, job_id=job["id"])

    assert result.ok is False
    assert "stale_ref" in str(result.error)
    assert result.status == "failed"


def test_the_real_browser_toolset_registers_the_escalation() -> None:
    """배선. 게이트웨이만 고치고 브라우저가 규칙을 안 걸면 헛것이다(소스에서 확인)."""
    import inspect

    from alture_jarvis import browser

    source = inspect.getsource(browser)
    assert 'gateway.approval_escalations["browser_click"]' in source
    assert '"irreversible_click_needs_approval", "browser_click_confirmed"' in source
