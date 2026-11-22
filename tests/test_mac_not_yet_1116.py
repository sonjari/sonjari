"""「맥에서는 아직」 — 맥에 손이 없는 기능은 조용히 실패하지 않고 그렇다고 말한다 (2026-11-16 · 설계_맥업데이트 §8).

자리는 하나: `tool_gateway._NOT_YET_ON_MAC`. 게이트웨이(모델 · MCP 가 부르는 문) · `/v1/tools` · MCP 고정 문 · `/health` 가
그 표 하나를 본다. 윈도우에서는 아무것도 안 바뀐다.
"""

from __future__ import annotations

import sys

import pytest

from alture_jarvis import tool_gateway
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import (
    _NOT_YET_ON_MAC,
    _PLATFORM_ONLY,
    ToolGateway,
    ToolSpec,
    mac_not_yet,
    mark_not_on_mac,
    not_yet_on_mac,
    tool_runs_here,
)


class _Store:
    def add_audit(self, *a, **k):
        return None


class _Events:
    def publish(self, *a, **k):
        return None


def _gateway(names: list[str]) -> ToolGateway:
    gateway = ToolGateway(_Store(), _Events())  # type: ignore[arg-type]
    for name in names:
        gateway.register(ToolSpec(name=name, description="d", risk_level=RiskLevel.L0, handler=lambda args: {"ran": True}))
    return gateway


SAMPLES = ["windows_focus_window", "hwp_open", "sandbox_run", "camera_look", "anim_pose_sheet", "anim_video_to_biped"]


@pytest.mark.parametrize("name", SAMPLES)
def test_a_mac_call_says_not_yet_and_what_to_do_instead(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    gateway = _gateway([name])
    if name.startswith("camera_"):
        # 카메라는 맥에서 설정이 끈다(윈도우 전용 표에 넣으면 맥 시험판의 카메라 시험이 깨진다) — 그 상태를 흉내 낸다.
        gateway._tools[name].enabled = False
    result = gateway.execute(name, {})
    assert not result.ok and result.status == "disabled"
    assert result.error.startswith("tool_disabled — 맥에서는 아직 안 됩니다:"), result.error
    assert result.result["not_on_mac"] is True and result.result["instead"]


@pytest.mark.parametrize("name", SAMPLES)
def test_windows_runs_the_same_tools(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    result = _gateway([name]).execute(name, {})
    assert result.ok and result.result == {"ran": True}


def test_a_tool_disabled_on_windows_keeps_the_old_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """윈도우에서 꺼진 도구는 예전 말(꺼져 있다 · 대신할 도구) 그대로 — 맥 문구가 새지 않는다."""
    monkeypatch.setattr(sys, "platform", "win32")
    gateway = _gateway(["sandbox_run"])
    gateway._tools["sandbox_run"].enabled = False
    result = gateway.execute("sandbox_run", {})
    assert "맥" not in result.error and "local_write_document" in result.error
    assert result.result is None


def test_a_mac_tool_that_is_not_in_the_table_keeps_the_old_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    gateway = _gateway(["browser_open"])
    gateway._tools["browser_open"].enabled = False
    result = gateway.execute("browser_open", {})
    assert "맥" not in result.error and result.error.startswith("tool_disabled — browser_open")


def test_pose_tools_are_hidden_from_the_model_on_mac_only() -> None:
    for name in ("anim_pose_sheet", "anim_video_to_biped"):
        assert tool_runs_here(name, "win32") is True
        assert tool_runs_here(name, "darwin") is False
    # 같은 animator 팩의 다른 도구는 맥에서도 그대로 보인다(블렌더 판 등).
    assert tool_runs_here("anim_blender_check", "darwin") is True


def test_the_tool_list_carries_the_reason_on_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    listed = {item["name"]: item for item in _gateway(["anim_pose_sheet", "browser_open"]).list_tools()}
    assert listed["anim_pose_sheet"]["enabled"] is False and "맥에서는 아직" in listed["anim_pose_sheet"]["not_on_mac"]
    assert "not_on_mac" not in listed["browser_open"]


def test_the_tool_list_is_unchanged_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    item = _gateway(["anim_pose_sheet"]).list_tools()[0]
    assert set(item) == {"name", "description", "risk_level", "enabled", "parameters"}


# ── 표 자체의 규칙 ─────────────────────────────────────────────────────────────────────────


def test_every_tool_the_mac_cannot_run_is_explained() -> None:
    """윈도우 전용 표에 넣고 「맥에서는 아직」에 안 적으면 맥은 또 「꺼져 있다」 한 줄만 받는다."""
    for prefix, platforms in _PLATFORM_ONLY:
        if "darwin" not in platforms and "win32" in platforms:
            assert not_yet_on_mac(prefix + "x", "darwin") is not None, f"{prefix} 가 맥 표에 없다"


def test_nothing_the_mac_can_run_is_still_listed_as_not_yet() -> None:
    """맥에서 되게 만든 날 표에서 안 지우면 「안 된다」는 거짓말이 남는다."""
    for key, kind, _feature, _instead in _NOT_YET_ON_MAC:
        if kind == "tool" and key != "camera_":  # 카메라는 설정으로 꺼진다(위 시험 참고)
            assert tool_runs_here(key + "x" if key.endswith("_") else key, "darwin") is False, f"{key} 는 맥에서 돈다"


def test_every_entry_says_what_to_do_instead() -> None:
    for key, kind, feature, instead in _NOT_YET_ON_MAC:
        assert kind in {"tool", "feature"} and feature and instead, key


# ── /health ──────────────────────────────────────────────────────────────────────────────


def test_health_marks_hotkey_and_media_on_mac_only() -> None:
    status = {"enabled": False, "ok": False}
    marked = mark_not_on_mac("hotkey", status, "darwin")
    assert "음성 단축키" in marked["not_on_mac"] and status == {"enabled": False, "ok": False}
    assert "음악" in mark_not_on_mac("media", {"ok": False}, "darwin")["not_on_mac"]
    assert mark_not_on_mac("hotkey", status, "win32") is status, "윈도우 /health 칸이 바뀌었다"
    assert mark_not_on_mac("hotkey", "문자열", "darwin") == "문자열"


def test_health_lists_everything_from_the_one_table() -> None:
    listed = mac_not_yet("darwin")
    assert [item["key"] for item in listed] == [entry[0] for entry in _NOT_YET_ON_MAC]
    assert {"hotkey", "media", "camera_", "sandbox_", "anim_pose_sheet"} <= {item["key"] for item in listed}
    assert mac_not_yet("win32") == []


def test_runtime_health_adds_mac_keys_only_on_mac() -> None:
    import inspect

    from alture_jarvis import runtime

    source = inspect.getsource(runtime.JarvisRuntime)
    assert '"mac_not_yet": mac_not_yet()' in source
    assert 'if sys.platform == "darwin" else {}' in source
    assert 'mark_not_on_mac("hotkey"' in source and 'mark_not_on_mac("media"' in source


# ── MCP 고정 문 ────────────────────────────────────────────────────────────────────────────


def test_the_mcp_door_answers_not_yet_instead_of_no_such_tool() -> None:
    import asyncio

    from alture_jarvis import mcp_server

    bridge = mcp_server.JarvisMcpBridge.__new__(mcp_server.JarvisMcpBridge)
    bridge.lang = "ko"
    bridge._runtime_names = {"anim_pose_sheet"}
    bridge._runtime_not_on_mac = {"anim_pose_sheet": "맥에서는 아직 안 됩니다: 영상에서 자세 뽑기(포즈 시트). 윈도우 PC 의 손자리에서 하세요."}

    async def no_pack(name: str) -> str:
        return ""

    bridge._disabled_pack_of = no_pack  # type: ignore[method-assign]
    message = asyncio.run(bridge._door_refusal("anim_pose_sheet", []))
    assert "맥에서는 아직" in message and "다시 부르지 마세요" in message
