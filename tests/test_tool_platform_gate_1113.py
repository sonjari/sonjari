"""손이 없는 OS 의 도구는 켜짐으로도, 모델 목록에도 올라가지 않는다 (2026-11-13 맥 조사).

맥 `/v1/tools` 에 `windows_*` 8개 · `clipboard_*` 2개가 켜짐으로 올라가 있었고, 모델 앞부분에는 `hwp_*` · `sandbox_*` 까지
실렸다. 게이트웨이 등록 · 에이전트 목록 두 문이 `tool_gateway.tool_runs_here` 표 하나를 본다 — 여기서 그 둘을 다 지킨다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from alture_jarvis.agent import AgentToolCatalog
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.tool_gateway import ToolGateway, tool_runs_here
from alture_jarvis.windows_automation import WindowsAutomationTools


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")


def _names(tools: list[dict]) -> set[str]:
    return {str(t["function"]["name"]) for t in tools}


@pytest.mark.parametrize("name", ["windows_uia_snapshot", "windows_open_path", "hwp_read", "sandbox_run"])
def test_windows_only_hands_do_not_run_on_mac(name: str) -> None:
    assert tool_runs_here(name, "win32") is True
    assert tool_runs_here(name, "darwin") is False


@pytest.mark.parametrize("name", ["browser_open", "local_write_document", "video_read", "unity_editor_look"])
def test_tools_not_in_the_table_run_everywhere(name: str) -> None:
    assert tool_runs_here(name, "darwin") is True
    assert tool_runs_here(name, "win32") is True


def _registered(tmp_path: Path) -> tuple[ToolGateway, AgentToolCatalog]:
    config = _config(tmp_path)
    gateway = ToolGateway(JobStore(tmp_path / "jarvis.db"), EventBus())
    windows = WindowsAutomationTools(config)
    local = LocalComputerTools(config)
    windows.register(gateway)
    local.register(gateway)
    return gateway, AgentToolCatalog(windows, local)


def test_on_mac_windows_hands_are_off_and_hidden_from_the_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    gateway, catalog = _registered(tmp_path)
    listed = {t["name"]: t["enabled"] for t in gateway.list_tools()}
    windows_hands = {name for name in listed if name.startswith("windows_")}
    # 조사 때 맥에 켜짐으로 올라가 있던 8개(windows_automation 5 · local_computer 3)가 다 있어야 시험이 뜻이 있다.
    assert len(windows_hands) == 8
    assert not any(listed[name] for name in windows_hands)
    model = _names(catalog.ollama_tools)
    assert not (model & windows_hands)
    # 손이 있는 도구는 그대로다.
    assert "local_write_document" in model and listed["local_write_document"] is True


def test_on_windows_the_same_hands_stay_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    gateway, catalog = _registered(tmp_path)
    listed = {t["name"]: t["enabled"] for t in gateway.list_tools()}
    windows_hands = {name for name in listed if name.startswith("windows_")}
    assert windows_hands and all(listed[name] for name in windows_hands)
    assert windows_hands <= _names(catalog.ollama_tools)


def test_calling_a_mac_hidden_hand_by_name_says_it_is_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """목록에서 빠져도 이름으로 부르면 `unknown_tool` 이 아니라 「꺼져 있다 · 다른 도구로」를 받는다."""
    monkeypatch.setattr(sys, "platform", "darwin")
    gateway, _ = _registered(tmp_path)
    result = gateway.execute("windows_list_open_windows", {})
    assert result.ok is False and result.status == "disabled"
