"""승인 방식: 수동 / 되돌릴 수 있는 것만 자동 (2026-09-16).

왜 만들었나 — 바깥 Claude 가 시킨 일의 승인 카드는 온텔릭 창에만 뜬다. 사람이 Claude 창을 보고 있으면 아무도 못
보고 30분 뒤 만료돼 **일이 조용히 죽는다**(실측에서 그렇게 멈췄다).

지켜야 할 선: 이 스위치로도 **등록 자체가 L2 인 것**(메일 발송·발행·결제·삭제)은 열리지 않는다. 자동은
「대상 때문에 등급이 올라간 + 되돌리기가 달린」 동작뿐이다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import InverseSpec, ToolGateway, ToolSpec


def _gateway(tmp_path: Path, *, auto: bool) -> tuple[ToolGateway, list[str], EventBus]:
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    gateway = ToolGateway(store, events, auto_approve_reversible=auto)
    done: list[str] = []

    def write(arguments: dict) -> dict:
        done.append(str(arguments.get("path") or ""))
        return {"ok": True, "path": arguments.get("path")}

    gateway.register(ToolSpec(
        "local_write_file", "파일 쓰기", RiskLevel.L1, write,
        dynamic_risk=lambda args: RiskLevel.L2 if "내문서" in str(args.get("path") or "") else RiskLevel.L1,
        inverse=InverseSpec(label="되돌리기", handle_from=lambda args, result: {"path": result.get("path")},
                            undo=lambda handle: {"ok": True}),
    ))
    gateway.register(ToolSpec(
        "google_gmail_send", "메일 보내기", RiskLevel.L2, lambda args: done.append("mail") or {"ok": True},
        inverse=InverseSpec(label="되돌리기(흉내)", handle_from=lambda args, result: {}, undo=lambda handle: {"ok": True}),
    ))
    return gateway, done, events


def test_manual_is_the_default_and_asks_before_writing_into_my_folder(tmp_path: Path) -> None:
    gateway, done, _ = _gateway(tmp_path, auto=False)
    result = gateway.execute("local_write_file", {"path": "내문서/보고서.md", "content": "x"})
    assert result.status == "approval_required" and done == []


def test_auto_lets_a_reversible_write_through_and_says_so(tmp_path: Path) -> None:
    gateway, done, events = _gateway(tmp_path, auto=True)
    result = gateway.execute("local_write_file", {"path": "내문서/보고서.md", "content": "x"})
    assert result.ok and done == ["내문서/보고서.md"]
    kinds = [event.event for event in events.get_since(0)]
    assert "approval_auto_approved" in kinds


def test_the_switch_never_opens_mail_or_anything_registered_as_irreversible(tmp_path: Path) -> None:
    gateway, done, _ = _gateway(tmp_path, auto=True)
    result = gateway.execute("google_gmail_send", {"to": "a@b.c", "subject": "x", "body": "y"})
    assert result.status == "approval_required" and done == []


def test_a_write_without_an_undo_still_asks(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    gateway = ToolGateway(store, EventBus(), auto_approve_reversible=True)
    gateway.register(ToolSpec(
        "local_shred", "되돌릴 수 없는 쓰기", RiskLevel.L1, lambda args: {"ok": True},
        dynamic_risk=lambda args: RiskLevel.L2,
    ))
    assert gateway.execute("local_shred", {"path": "x"}).status == "approval_required"
