"""2026-11-16 대표 두 가지.

① 「권한 무시」여도 되돌릴 수 없는 **화면 동작**(창 닫기 · 앱 끝내기 · 지우기 단축키)은 사람이 본다.
   그날 맥 화면 조종 첫 실전에서 실행 4번이 권한 무시로 자동 승인됐다 — 평소 동작은 그대로 두고 위험한 단축키만 멈춘다.
② 「눌렀는데 반영이 안 됐다」 같은 알림이 MCP 판에서도 소리로 나왔다 → 답과 같은 규칙: 받아쓰기로 들어온 일만 소리.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from alture_jarvis.attention import AttentionService
from alture_jarvis.mac_automation import MacAutomationTools, MacPreview
from alture_jarvis.permissions import NEVER_BYPASS
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.tool_gateway import RiskLevel, ToolGateway
from alture_jarvis.windows_automation import ActionPreview, WindowsAutomationTools


class _Spec:
    def __init__(self, name: str, risk: RiskLevel = RiskLevel.L2) -> None:
        self.name = name
        self.risk_level = risk
        self.inverse = None


def _bypass_gateway() -> ToolGateway:
    gw = ToolGateway.__new__(ToolGateway)
    gw.auto_approve_all = True
    gw.auto_approve_shell = True
    gw.auto_approve_reversible = True
    gw.bypass_still_asks = {}
    return gw


# ── ① 권한 무시 + 되돌릴 수 없는 화면 동작 ───────────────────────────────

def test_bypass_still_auto_approves_an_ordinary_screen_action() -> None:
    gw = _bypass_gateway()
    gw.bypass_still_asks["mac_execute_preview"] = lambda args: False
    assert gw._auto_approvable(_Spec("mac_execute_preview"), RiskLevel.L2, {"preview_id": "p"}) is True


def test_bypass_asks_when_the_screen_action_cannot_be_undone() -> None:
    gw = _bypass_gateway()
    gw.bypass_still_asks["mac_execute_preview"] = lambda args: True
    assert gw._auto_approvable(_Spec("mac_execute_preview"), RiskLevel.L2, {"preview_id": "p"}) is False


def test_a_check_that_breaks_means_ask() -> None:
    gw = _bypass_gateway()

    def boom(_args: dict[str, Any]) -> bool:
        raise RuntimeError("x")

    gw.bypass_still_asks["windows_execute_preview"] = boom
    assert gw._auto_approvable(_Spec("windows_execute_preview"), RiskLevel.L2, {}) is False


def test_the_old_never_bypass_list_is_untouched() -> None:
    gw = _bypass_gateway()
    for name in NEVER_BYPASS:
        assert gw._auto_approvable(_Spec(name), RiskLevel.L2, {}) is False
    assert gw._auto_approvable(_Spec("local_delete_file"), RiskLevel.L2, {}) is True  # 9-23 범위 그대로


def _mac_tools(previews: dict[str, MacPreview]) -> MacAutomationTools:
    tools = MacAutomationTools.__new__(MacAutomationTools)
    tools._lock = threading.Lock()
    tools._previews = previews
    return tools


def _mac_preview(action: str, value: str) -> MacPreview:
    now = time.time()
    return MacPreview(preview_id="p", action=action, window_id=1, window_title="무제", app="텍스트 편집기",
                      target={}, value=value, screenshot_path="", before={}, created_at=now, expires_at=now + 300)


def test_mac_close_and_quit_keys_are_destructive_but_new_and_paste_are_not() -> None:
    assert _mac_tools({"p": _mac_preview("key", "cmd+w")}).preview_is_destructive({"preview_id": "p"}) is True
    assert _mac_tools({"p": _mac_preview("key", "Cmd+Q")}).preview_is_destructive({"preview_id": "p"}) is True
    assert _mac_tools({"p": _mac_preview("key", "cmd+n")}).preview_is_destructive({"preview_id": "p"}) is False
    assert _mac_tools({"p": _mac_preview("paste", "안녕")}).preview_is_destructive({"preview_id": "p"}) is False
    assert _mac_tools({}).preview_is_destructive({"preview_id": "없음"}) is True


def _win_tools(previews: dict[str, ActionPreview]) -> WindowsAutomationTools:
    tools = WindowsAutomationTools.__new__(WindowsAutomationTools)
    tools._lock = threading.Lock()
    tools._previews = previews
    return tools


def _win_preview(action: str, value: str) -> ActionPreview:
    now = time.time()
    return ActionPreview(preview_id="p", source="uia", action=action, window_id=1, target={}, value=value,
                         screenshot_path="", created_at=now, expires_at=now + 300)


def test_windows_alt_f4_is_destructive_but_ctrl_s_is_not() -> None:
    assert _win_tools({"p": _win_preview("key", "alt+f4")}).preview_is_destructive({"preview_id": "p"}) is True
    assert _win_tools({"p": _win_preview("key", "ctrl+s")}).preview_is_destructive({"preview_id": "p"}) is False
    assert _win_tools({"p": _win_preview("click", "")}).preview_is_destructive({"preview_id": "p"}) is False


# ── ② 알림 소리는 말로 들어온 일만 ─────────────────────────────────────────

class _Events:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def publish(self, name: str, _payload: dict[str, Any]) -> None:
        self.seen.append(name)


class _Notes:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def notify(self, title: str, _message: str) -> None:
        self.sent.append(title)


def _attention(spoken_jobs: set[str] | None):
    said: list[str] = []
    events, notes = _Events(), _Notes()
    service = AttentionService(
        events, notes, said.append,
        speaks_for=None if spoken_jobs is None else (lambda job_id: job_id in spoken_jobs),
    )
    return service, said, events, notes


def test_an_alert_for_a_typed_or_mcp_job_shows_but_stays_silent() -> None:
    service, said, events, notes = _attention(spoken_jobs={"voice-job"})
    service.announce(code="c", title="t", message="m", speech="눌렀지만 반영이 안 됐어요", job_id="mcp-job")
    assert said == []
    assert events.seen == ["attention_required"] and notes.sent  # 카드 · 알림은 그대로


def test_an_alert_for_a_spoken_job_is_still_said() -> None:
    service, said, _events, _notes = _attention(spoken_jobs={"voice-job"})
    service.announce(code="c", title="t", message="m", speech="눌렀지만 반영이 안 됐어요", job_id="voice-job")
    assert said == ["눌렀지만 반영이 안 됐어요"]


def test_the_rule_path_follows_the_same_gate() -> None:
    service, said, _events, _notes = _attention(spoken_jobs=set())
    for _ in range(3):
        service.check(job_id="mcp-job", tool="browser_click", arguments={}, observation={"ok": False, "error": "x"})
    assert said == []


def test_the_runtime_knows_which_jobs_were_spoken() -> None:
    runtime = JarvisRuntime.__new__(JarvisRuntime)
    jobs = {"a": {"payload": {"spoken_input": True}}, "b": {"payload": {"origin": "mcp"}}}
    runtime.store = type("S", (), {"get_job": staticmethod(lambda job_id: jobs.get(job_id))})()
    assert runtime._job_was_spoken("a") is True
    assert runtime._job_was_spoken("b") is False
    assert runtime._job_was_spoken("") is False
    assert runtime._job_was_spoken("없음") is False
