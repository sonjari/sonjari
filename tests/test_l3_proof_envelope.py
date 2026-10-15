from __future__ import annotations

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.proof import ProofSpec, finalize_proof, same_fingerprint
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec


def _gateway(tmp_path, state, calls, *, verified=True):
    gateway = ToolGateway(JobStore(tmp_path / "jarvis.db"), EventBus())

    def capture(arguments):
        return {
            "url": state["url"],
            "ref": arguments["ref"],
            "target": state["target"],
            "fingerprint": f"{state['url']}|{arguments['ref']}|{state['target']}",
        }

    def execute(arguments):
        calls.append(dict(arguments))
        return {
            "action": "clicked",
            "url": state["url"],
            "ref": arguments["ref"],
            "verified": verified,
            "verification": {"status": "verified" if verified else "unknown"},
        }

    gateway.register(
        ToolSpec(
            name="irreversible_click",
            description="되돌릴 수 없는 클릭",
            risk_level=RiskLevel.L2,
            handler=execute,
            proof=ProofSpec(
                capture_before=capture,
                same_target=same_fingerprint,
                finalize=finalize_proof,
                capture_after=lambda arguments, result: {
                    "screenshot": "after.png",
                    "url": state["url"],
                },
            ),
        )
    )
    return gateway


def _approve_first(gateway):
    first = gateway.execute("irreversible_click", {"ref": "j20"})
    assert first.status == "approval_required"
    approval = gateway.store.get_approval(first.approval_nonce)
    assert approval["proof"]["fingerprint"]
    gateway.decide(first.approval_nonce, True)
    return first.approval_nonce


def test_approval_is_bound_to_the_exact_target_and_drift_clicks_zero_times(tmp_path) -> None:
    state = {"url": "https://shop.test/checkout", "target": "결제하기"}
    calls = []
    gateway = _gateway(tmp_path, state, calls)
    nonce = _approve_first(gateway)
    state["target"] = "회원 탈퇴"

    result = gateway.execute("irreversible_click", {"ref": "j20"})

    assert result.ok is False
    assert result.status == "proof_target_drifted"
    assert calls == []
    assert gateway.store.get_approval(nonce)["status"] == "consumed"


def test_verified_l3_result_contains_before_and_after_proof(tmp_path) -> None:
    state = {"url": "https://shop.test/checkout", "target": "결제하기"}
    calls = []
    gateway = _gateway(tmp_path, state, calls)
    _approve_first(gateway)

    result = gateway.execute("irreversible_click", {"ref": "j20"})

    assert result.ok is True
    assert result.result["verified"] is True
    assert result.result["proof"]["before"]["target"] == "결제하기"
    assert result.result["proof"]["after"]["verified"] is True
    assert result.result["proof"]["after"]["screenshot"] == "after.png"
    assert calls == [{"ref": "j20"}]


def test_an_executed_but_unverified_l3_write_is_not_silently_retryable(tmp_path) -> None:
    state = {"url": "https://shop.test/checkout", "target": "결제하기"}
    calls = []
    gateway = _gateway(tmp_path, state, calls, verified=False)
    _approve_first(gateway)

    result = gateway.execute("irreversible_click", {"ref": "j20"})
    second = gateway.execute("irreversible_click", {"ref": "j20"})

    assert result.ok is True
    assert result.status == "executed_unverified"
    assert result.result["proof"]["after"]["verified"] is False
    assert second.status == "approval_required", "소비한 승인을 재사용해 자동 재클릭하면 안 된다"
    assert calls == [{"ref": "j20"}]
