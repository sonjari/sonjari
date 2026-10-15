"""「권한 무시」 모드 — 결제·메일 보내기·발행만 묻는다 (2026-09-23 사장님 결정).

> 온텔릭도 이제 클로드 권한방식이랑 똑같이 하자 … 맨날 승인 버튼누르는것도 귀찮고

클로드 코드의 bypass 는 전부 연다. 온텔릭은 로컬 모델이라 지어낸 내용으로 메일이 나가거나
돈이 빠질 수 있다 — 그 셋만 남기고 나머지(지우기·폴더 권한·PC 설정 포함)는 연다.

잰다:
  ① 권한 무시에서 **평소엔 늘 묻던 것**(삭제·폴더 권한·PC 설정)이 자동으로 지나간다
  ② 권한 무시에서도 결제·메일 보내기·발행은 **여전히 묻는다**
  ③ 모드를 끄면 원래대로 돌아온다
  ④ 모드를 고르면 관문까지 실제로 닿는다(설정 → 관문 복사본)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.models import RiskLevel
from alture_jarvis.permissions import ALWAYS_ASK, NEVER_BYPASS, apply_mode, mode_of
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec


def _spec(name: str, *, risk: RiskLevel = RiskLevel.L2, inverse: object | None = None) -> ToolSpec:
    return ToolSpec(name=name, description=name, parameters={"type": "object", "properties": {}},
                    handler=lambda _a: {"ok": True}, risk_level=risk, inverse=inverse)


def _gate(**kwargs) -> ToolGateway:
    import tempfile

    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore

    return ToolGateway(JobStore(Path(tempfile.mkdtemp()) / "jobs.db"), EventBus(), **kwargs)


@pytest.mark.parametrize("tool", sorted(ALWAYS_ASK - NEVER_BYPASS))
def test_bypass_opens_what_every_other_mode_keeps_asking(tool: str) -> None:
    """지우기·폴더 권한·PC 설정 — 다른 모드에선 닫힌 문인데 권한 무시에선 열린다."""
    assert _gate(auto_approve_all=True)._auto_approvable(_spec(tool), RiskLevel.L2) is True, tool
    assert _gate(auto_approve_reversible=True, auto_approve_shell=True)._auto_approvable(
        _spec(tool, risk=RiskLevel.L1, inverse=object()), RiskLevel.L2) is False, tool


@pytest.mark.parametrize("tool", sorted(NEVER_BYPASS))
def test_money_and_outbound_still_ask_under_bypass(tool: str) -> None:
    """★ 이 셋은 권한 무시에서도 사람이 본다 — 되돌릴 수 없다."""
    assert _gate(auto_approve_all=True)._auto_approvable(_spec(tool), RiskLevel.L2) is False, tool


def test_bypass_also_opens_irreversible_ordinary_tools() -> None:
    """되돌리기가 없고 등록부터 L2 인 도구도 연다 — 편집 자동 수락과 다른 점."""
    spec = _spec("windows_type", risk=RiskLevel.L2, inverse=None)
    assert _gate(auto_approve_all=True)._auto_approvable(spec, RiskLevel.L2) is True
    assert _gate(auto_approve_reversible=True)._auto_approvable(spec, RiskLevel.L2) is False


def test_never_bypass_is_a_subset_of_always_ask() -> None:
    """권한 무시가 **새로 묻는** 것은 없어야 한다 — 좁히기만 한다."""
    assert NEVER_BYPASS <= ALWAYS_ASK
    for kind in ("gmail_send", "publish", "payment"):
        assert any(kind in name for name in NEVER_BYPASS), kind


def test_off_means_off() -> None:
    assert _gate(auto_approve_all=False)._auto_approvable(_spec("local_delete_file"), RiskLevel.L2) is False


def test_choosing_the_mode_reaches_the_gate(tmp_path: Path) -> None:
    """모드 → 설정값 → 런타임이 관문 복사본을 갱신하는 키까지(사고 Q: 값이 사는 자리)."""
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    changes = apply_mode(config, "bypass")
    assert changes["approval_bypass_enabled"] is True
    for key, value in changes.items():
        setattr(config, key, value)
    assert mode_of(config) == "bypass"
    # 다른 모드로 돌아가면 권한 무시는 **반드시** 꺼진다 — 안 꺼지면 「수동」인데 다 여는 화면 거짓말.
    for other in ("ask", "reversible", "workspace", "read_only"):
        assert apply_mode(config, other)["approval_bypass_enabled"] is False, other

    import inspect

    from alture_jarvis import runtime
    source = inspect.getsource(runtime)
    assert "auto_approve_all=self.config.approval_bypass_enabled" in source
    assert 'if "approval_bypass_enabled" in keys:' in source
