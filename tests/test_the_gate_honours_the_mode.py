"""모드는 **관문에서 실제로 지켜져야** 한다 (2026-09-21).

설정 화면에 모드를 그려 놓고 관문이 안 보면, 그건 「켜짐이라 적혀 있는데 실제로는
못 쓰는 상태」다 — 이 저장소가 노트북에서 겪은 그것(설정엔 「말로 시키기: 켜짐」인데
받아쓰기 모듈이 없었다).

두 가지를 잰다:

  ① `read_only` 에서 쓰기 도구가 **막히고, 왜인지 말한다**
  ② `ALWAYS_ASK` 목록은 **어느 모드에서도 자동으로 안 지나간다**
"""

from __future__ import annotations

import pytest

from alture_jarvis.models import RiskLevel
from alture_jarvis.permissions import ALWAYS_ASK
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec


def _spec(name: str, *, risk: RiskLevel, inverse: object | None = None) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        handler=lambda _a: {"ok": True},
        risk_level=risk,
        inverse=inverse,
    )


def _gate(**kwargs) -> ToolGateway:
    import tempfile
    from pathlib import Path

    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore

    store = JobStore(Path(tempfile.mkdtemp()) / "jobs.db")
    return ToolGateway(store, EventBus(), **kwargs)


# ── ① 읽기만 모드 ───────────────────────────────────────────────────────────
def test_read_only_blocks_a_write_and_says_why() -> None:
    gate = _gate(auto_approve_reversible=False, write_enabled=False)
    assert gate.refusal_for_read_only(_spec("local_write_file", risk=RiskLevel.L1)) is not None
    why = gate.refusal_for_read_only(_spec("local_write_file", risk=RiskLevel.L1))
    assert "읽기만" in why["instruction"]


def test_read_only_still_lets_reading_through() -> None:
    gate = _gate(auto_approve_reversible=False, write_enabled=False)
    assert gate.refusal_for_read_only(_spec("local_grep", risk=RiskLevel.L0)) is None


def test_write_mode_does_not_block_anything() -> None:
    gate = _gate(auto_approve_reversible=False, write_enabled=True)
    assert gate.refusal_for_read_only(_spec("local_write_file", risk=RiskLevel.L1)) is None


def test_read_only_now_also_blocks_running_project_commands() -> None:
    """★ 2026-09-23 발견·수정: `local_run_project_command` 는 등급이 L1 이라
    승인 카드가 안 뜨는데, 허용 명령에 `ruff format .` 처럼 저장소 파일을 실제로
    고쳐 쓰는 것이 있다. 목록에 없으면 「읽기만」 모드에서도 그대로 돌아갔다 —
    그 모드의 약속("아무것도 안 바꾼다")이 깨지는 자리였다.
    """
    gate = _gate(auto_approve_reversible=False, write_enabled=False)
    refusal = gate.refusal_for_read_only(
        _spec("local_run_project_command", risk=RiskLevel.L1)
    )
    assert refusal is not None
    assert "읽기만" in refusal["instruction"]


# ── ② 어느 모드에서도 안 열리는 것 ──────────────────────────────────────────
@pytest.mark.parametrize("tool", sorted(ALWAYS_ASK))
def test_the_never_auto_tools_are_never_auto_approved(tool: str) -> None:
    """★ 설정을 가장 넓게 열어 놓고도 이 도구들은 사람이 본다."""
    gate = _gate(auto_approve_reversible=True, write_enabled=True)
    spec = _spec(tool, risk=RiskLevel.L1, inverse=object())
    assert gate._auto_approvable(spec, RiskLevel.L2) is False, tool


def test_an_ordinary_reversible_tool_is_still_auto_approved() -> None:
    """목록을 넓히다 멀쩡한 자동 승인까지 막으면 모드가 쓸모없어진다."""
    gate = _gate(auto_approve_reversible=True, write_enabled=True)
    spec = _spec("local_write_file", risk=RiskLevel.L1, inverse=object())
    assert gate._auto_approvable(spec, RiskLevel.L2) is True


def test_turning_the_setting_off_stops_auto_approval() -> None:
    gate = _gate(auto_approve_reversible=False, write_enabled=True)
    spec = _spec("local_write_file", risk=RiskLevel.L1, inverse=object())
    assert gate._auto_approvable(spec, RiskLevel.L2) is False


# ── ③ 이 목록의 **범위**를 못 박아 둔다 ────────────────────────────────────
def test_the_never_auto_list_only_bites_once_something_escalated() -> None:
    """★ 실전에서 확인한 범위 (2026-09-21 AURORA 2차).

    `local_delete_file` 을 목록에 넣어 뒀는데 그 판에서 **승인 없이 지나갔다.**
    고장이 아니다 — `_auto_approvable` 은 **이미 L2 로 올라간 뒤**에만 물어보는
    자리이고, 작업 폴더 안의 삭제는 L1 이라 그 문을 아예 안 지난다.

    동작은 맞다(제가 만든 파일을 제가 치우는 것). 그런데 **시험이 L2 경로만 덮고
    있으면 다음 사람은 「삭제는 언제나 물어본다」로 읽는다.** 그래서 여기 적는다:

        폴더 밖 삭제  → 대상 때문에 L2 로 올라감 → 목록이 막는다 → 카드가 뜬다
        폴더 안 삭제  → L1 그대로            → 이 문을 안 지남 → 카드가 안 뜬다
    """
    gate = _gate(auto_approve_reversible=True, write_enabled=True)
    spec = _spec("local_delete_file", risk=RiskLevel.L1, inverse=object())

    # 대상 때문에 올라간 경우 — 목록이 막는다
    assert gate._auto_approvable(spec, RiskLevel.L2) is False

    # 안 올라간 경우 — 이 함수는 애초에 안 불린다. 불러도 False 지만,
    # 실제 경로에서는 `execute` 가 L2 미만이면 승인 분기로 안 간다.
    assert gate._auto_approvable(spec, RiskLevel.L1) is False
