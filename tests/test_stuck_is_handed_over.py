"""같은 자리에서 헛돌면 **멈추고, 이유를 말하고, 넘긴다** (2026-09-23 제품 요청).

「못 하는 걸 붙잡고 헤맨다(결제 수단이 없는데 결제하려고) — 시간만 쓰고 UX 최악. 클로드는 될 때까지 하다가 안 되면
『이래서 못 했다, 이것만 해 주시면 이어가겠다』고 한다.」 예전엔 「같은 벽」을 모델에게 **알리기만** 했고 모델은 계속
두드렸다. 이제 알림의 두 배만큼 같은 자리에서 실패하면 코드가 멈추고 한 것·막힌 곳·해 주실 일을 체크포인트에 실어
사람에게 넘긴다. 사람이 손보고 「이어서」를 누르면 그 자리부터 잇는다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import (
    STUCK_FAILURES_AFTER,
    STUCK_LOCATE_AFTER,
    BrowserAgent,
    _stuck_report,
    _trailing_failures,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import ContinuationRequired, JobStore
from alture_jarvis.tool_gateway import ToolResult


def _fail(tool: str = "browser_click", error: str = "browser_click_failed: element not found") -> dict:
    return {"tool": tool, "ok": False, "error": error}


def _ok(tool: str = "browser_open", url: str = "https://shop.example/cart") -> dict:
    return {"tool": tool, "ok": True, "evidence_record": {"effect": "read_web", "source_id": url}}


def test_a_few_failures_are_not_yet_stuck() -> None:
    """★ 좋은 표본 — 한두 번 틀리는 건 방향을 바꿀 여지다. 멈추지 않는다."""
    steps = [_ok(), *[_fail() for _ in range(STUCK_FAILURES_AFTER - 1)]]
    assert _stuck_report(steps) is None


def test_consecutive_failures_become_a_hand_over_report() -> None:
    steps = [_ok(), *[_fail() for _ in range(STUCK_FAILURES_AFTER)]]
    report = _stuck_report(steps)
    assert report is not None and report["kind"] == "keeps_failing"
    message = report["message"]
    assert "여기까지 했습니다" in message and "여기서 막혔습니다" in message
    assert "이것만 해 주세요" in message and "이어서" in message
    assert "https://shop.example/cart" in message, "어느 화면인지가 있어야 사람이 찾아간다"


def test_a_success_in_between_resets_the_streak() -> None:
    """★ 좋은 표본 — 중간에 한 번이라도 나아갔으면 헛도는 게 아니다."""
    steps = [*[_fail() for _ in range(3)], _ok("browser_click"), *[_fail() for _ in range(3)]]
    assert _trailing_failures(steps) == 3 and _stuck_report(steps) is None


def test_repeated_cant_find_is_its_own_kind() -> None:
    steps = [_ok(), *[{"tool": "browser_find", "ok": True, "locate_miss": True} for _ in range(STUCK_LOCATE_AFTER)]]
    report = _stuck_report(steps)
    assert report is not None and report["kind"] == "cant_find"
    assert "단추나 칸" in report["ask"]


def test_a_timeout_asks_to_wait_not_to_fix_the_screen() -> None:
    steps = [_ok(), *[_fail(error="browser_action_timeout — 시간이 끊겼을 뿐") for _ in range(STUCK_FAILURES_AFTER)]]
    assert "잠시 뒤" in _stuck_report(steps)["ask"]


# ── 반복문에서 실제로 멈추나 ───────────────────────────────────────────────────


class _AlwaysFails:
    def execute(self, name, arguments, *, job_id=""):
        return ToolResult(False, name, error="browser_click_failed: element not found")


class _KeepsClicking:
    """사람이 보기엔 안 되는 걸 계속 누르는 모델 — 매번 다른 대상이라 되풀이 차단에도 안 걸린다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        return {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "browser_click", "arguments": {"ref": f"e{self.calls}"}}}
        ]}


def test_the_loop_stops_and_hands_over_instead_of_pounding(tmp_path) -> None:
    from test_agent import FakeBrowser, FakeTools  # 같은 폴더의 대역

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, ollama_max_tool_steps=30)
    store = JobStore(tmp_path / "jarvis.db")
    model = _KeepsClicking()
    agent = BrowserAgent(config, model, _AlwaysFails(), FakeBrowser(), FakeTools(), store, EventBus())
    job = store.create_job("chat", "pay", {"prompt": "장바구니 결제해줘"})
    store.claim_next()

    with pytest.raises(ContinuationRequired) as stopped:
        agent.run("장바구니 결제해줘", job_id=job["id"], origin="chat")

    payload = stopped.value.payload
    assert payload["reason"] == "stuck"
    assert "여기서 막혔습니다" in payload["report"]["message"]
    assert model.calls <= STUCK_FAILURES_AFTER + 2, f"멈추기 전에 {model.calls}번이나 두드렸다"
    assert store.get_agent_checkpoint(job["id"]), "「이어서」로 그 자리부터 잇도록 체크포인트가 남아야 한다"
