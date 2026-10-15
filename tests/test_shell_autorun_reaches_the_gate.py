"""「셸 명령 자동 실행」을 **켰으면 게이트가 실제로 지나가게 한다** — 안 켰으면 지금처럼 물어본다 (2026-09-21).

## 어떻게 찾았나

이 PC 에서 권한 모드를 `workspace`(「작업 폴더 안에서는 알아서」)로 올리고 35B 에게 코딩 사다리를 시켰다.
여섯째 과제가 `python -c "…"` 를 `local_run_shell` 로 돌리려다 **승인 카드에 걸려 25분을 기다렸다**(잡 상태
`waiting_approval`, 걸음 0). 모드 설명은 「파일을 만들고 지우는 명령까지 묻지 않습니다」인데 카드가 떴다.

## 왜 안 됐나 — 설계는 있었는데 배선이 없었다

`_shell_risk` 는 자동 실행이 켜지면 L1 을 돌려준다. 그런데 게이트웨이의 실제 등급은
`max(등록 바닥, 동적 등급)` — **동적 계산은 올리기만 한다**(우회로를 막으려는 규칙이다). `local_run_shell` 의
등록 바닥이 L2 라서 동적 L1 은 **항상 무시**됐다. 즉 자동 실행 설정과 `workspace` 모드의 셸 항목은 켜도 아무 효과가 없었다.

기존 시험(`test_a_real_shell_with_a_brake.py`)은 `_shell_risk` 를 **떼어내서** 시험한다 — 게이트웨이가 그 값을 어떻게
합치는지는 안 본다. 가짜(함수 하나)가 진짜(게이트웨이 합성)의 이름과 같은 값을 돌려주니 통과했다.

## 고친 것 — 좁게, 켠 사람에게만

바닥을 L1 로 내리지 **않았다.** `_SHELL_READ_ONLY` 에 `python`·`git`·`Get-Content` 가 「보기만 하는 명령」으로 들어 있어서,
내리면 기본 모드에서도 `python -c "임의 코드"` 와 `Get-Content …\\.env` 가 **무승인**으로 돈다(셸에는 민감 파일 필터가 없다).
그건 기본 보안 태세를 바꾸는 소유자 결정이다.

대신 **사용자가 명시적으로 켠 자동 실행**만 승인 단계에서 자동으로 지나가게 한다. 닫힌 문 목록(`ALWAYS_ASK`)과 셸 안의
보안 거부(`security_setting_change_blocked`·`system_folder_blocked`)는 그대로다. 자동으로 지나가도 **기록과 알림은 남긴다.**
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec


def _gateway(tmp_path: Path, *, autorun: bool) -> tuple[ToolGateway, list[str], EventBus, JobStore]:
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    gateway = ToolGateway(store, events, auto_approve_shell=autorun)
    ran: list[str] = []
    # 진짜와 같은 모양으로 등록한다 — 바닥은 L2, 동적 등급은 「자동 실행이면 L1」(local_computer 와 같다).
    gateway.register(ToolSpec(
        "local_run_shell", "셸", RiskLevel.L2, lambda args: ran.append(str(args.get("command"))) or {"ok": True},
        dynamic_risk=lambda args: RiskLevel.L1 if autorun else RiskLevel.L2,
    ))
    gateway.register(ToolSpec(
        "local_delete_file", "지우기", RiskLevel.L1, lambda args: ran.append("delete") or {"ok": True},
        dynamic_risk=lambda args: RiskLevel.L2,
    ))
    gateway.register(ToolSpec(
        "google_gmail_send", "메일", RiskLevel.L2, lambda args: ran.append("mail") or {"ok": True},
    ))
    return gateway, ran, events, store


def test_by_default_a_shell_command_asks(tmp_path: Path) -> None:
    """기본은 그대로다 — 셸 명령은 승인 카드가 먼저 뜬다."""
    gateway, ran, _events, _store = _gateway(tmp_path, autorun=False)

    result = gateway.execute("local_run_shell", {"command": "python -c \"print(1)\""})

    assert result.status == "approval_required" and ran == []


def test_when_the_user_turned_autorun_on_the_command_runs_and_is_recorded(tmp_path: Path) -> None:
    gateway, ran, events, store = _gateway(tmp_path, autorun=True)

    result = gateway.execute("local_run_shell", {"command": "python -c \"print(1)\""}, job_id="job-1")

    assert result.ok and ran == ['python -c "print(1)"']
    assert "approval_auto_approved" in [event.event for event in events.get_since(0)], "조용히 지나가면 안 된다"
    audits = [row for row in store.list_audit(50) if row.get("event") == "approval_auto_approved"] \
        if hasattr(store, "list_audit") else []
    if audits:
        assert "local_run_shell" in str(audits[0])


def test_autorun_never_opens_the_closed_doors(tmp_path: Path) -> None:
    """메일 발송·삭제 같은 닫힌 문은 어느 설정에서도 사람이 본다."""
    gateway, ran, _events, _store = _gateway(tmp_path, autorun=True)

    assert gateway.execute("google_gmail_send", {"to": "a@b.c"}).status == "approval_required"
    assert gateway.execute("local_delete_file", {"path": "x"}).status == "approval_required"
    assert ran == []


def test_the_switch_is_live_on_the_gateway(tmp_path: Path) -> None:
    """설정을 바꾸면 이미 떠 있는 게이트웨이가 따라와야 한다(권한 모드는 재시작 없이 적용된다)."""
    gateway, ran, _events, _store = _gateway(tmp_path, autorun=False)
    assert gateway.execute("local_run_shell", {"command": "dir"}).status == "approval_required"

    gateway.auto_approve_shell = True

    assert gateway.execute("local_run_shell", {"command": "dir"}).ok and ran == ["dir"]


def test_the_runtime_passes_the_setting_and_updates_it_on_change() -> None:
    """만들어 놓고 부르는 자리가 없으면 아무 일도 안 일어난다(이 저장소가 여러 번 겪은 모양)."""
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    assert "auto_approve_shell=self.config.shell_autorun_enabled" in inspect.getsource(JarvisRuntime.__init__)
    handler = inspect.getsource(JarvisRuntime._settings_changed)
    assert "shell_autorun_enabled" in handler and "auto_approve_shell" in handler


def test_the_register_floor_is_still_l2() -> None:
    """바닥은 L2 로 둔다 — 낮추면 기본 모드에서 `python -c` 가 무승인으로 돈다(소유자 결정 사항)."""
    import inspect

    from alture_jarvis.local_computer import LocalComputerTools

    assert '"local_run_shell": RiskLevel.L2' in inspect.getsource(LocalComputerTools.register)
