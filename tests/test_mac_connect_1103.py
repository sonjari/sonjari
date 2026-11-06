"""맥에서 클로드 잇기 (2026-11-03 · 전수조사 C2).

예전엔 맥에서도 `~/AppData/Roaming/Claude/claude_desktop_config.json` 을 봤다 — 맥에 그런 폴더는 없으므로
「설치 안 됨」이 되거나, 누가 만들어 두면 엉뚱한 자리에 써 놓고 성공으로 보였다(조용히 틀림).
맥 자리와 실행 파일 모양은 맥미니(macOS 15.8.2, Claude 데스크톱 · 딸린 클로드 코드 2.1.309)에서 확인했다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from alture_jarvis import macos
from alture_jarvis.config import JarvisConfig
from alture_jarvis.mcp_connect import SERVER_NAME, ConnectService

DESKTOP = "/Applications/Claude.app/Contents/MacOS/Claude"
HELPER = "/Applications/Claude.app/Contents/Frameworks/Claude Helper.app/Contents/MacOS/Claude Helper"
CLI = ("/Users/d/Library/Application Support/Claude/claude-code/2.1.309/5af865b9901c/"
       "claude.app/Contents/MacOS/claude")


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path / "rt", data_dir=tmp_path / "rt" / "data",
                        output_dir=tmp_path / "rt" / "out", control_token="secret-token-should-not-leak")


@pytest.fixture
def mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")


def test_mac_desktop_config_lives_in_library(tmp_path: Path, mac: None) -> None:
    home = tmp_path / "home"
    service = ConnectService(_config(tmp_path), home=home, which=lambda _: None, processes=lambda: [])
    assert service.desktop_paths() == [home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"]


def test_mac_does_not_write_to_a_windows_shaped_folder(tmp_path: Path, mac: None) -> None:
    """윈도우 모양 폴더가 있어도 맥에서는 쓰지 않는다 — 클로드가 그 파일을 안 읽는다."""
    home = tmp_path / "home"
    wrong = home / "AppData" / "Roaming" / "Claude"
    wrong.mkdir(parents=True)
    (wrong / "claude_desktop_config.json").write_text("{}", encoding="utf-8")
    service = ConnectService(_config(tmp_path), home=home, which=lambda _: None, processes=lambda: [])
    result = service.apply("claude_desktop")
    assert result.get("ok") is not True
    assert json.loads((wrong / "claude_desktop_config.json").read_text(encoding="utf-8")) == {}


def test_mac_desktop_apply_writes_the_library_file(tmp_path: Path, mac: None) -> None:
    home = tmp_path / "home"
    target = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"preferences": {"x": 1}}), encoding="utf-8")
    service = ConnectService(_config(tmp_path), home=home, which=lambda _: None, processes=lambda: [])
    assert service.apply("claude_desktop")["ok"]
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["preferences"] == {"x": 1} and SERVER_NAME in data["mcpServers"]
    assert "secret-token-should-not-leak" not in target.read_text(encoding="utf-8")


def test_mac_desktop_app_is_told_apart_from_its_bundled_cli(tmp_path: Path) -> None:
    service = ConnectService(_config(tmp_path), which=lambda _: None, processes=lambda: [DESKTOP, HELPER, CLI])
    assert service.desktop_exes() == [DESKTOP]


def test_mac_finds_the_cli_the_desktop_app_carries(tmp_path: Path, mac: None) -> None:
    home = tmp_path / "home"
    base = home / "Library" / "Application Support" / "Claude" / "claude-code"
    for version in ("2.1.9", "2.1.309"):
        exe = base / version / "abc" / "claude.app" / "Contents" / "MacOS" / "claude"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
    service = ConnectService(_config(tmp_path), home=home, which=lambda _: None, processes=lambda: [])
    assert "/2.1.309/" in service._claude_cli().replace("\\", "/")


def test_mac_processes_parse_paths_with_spaces() -> None:
    out = f"  1 /sbin/launchd\n 2914 {DESKTOP}\n 3011 {HELPER}\n"

    def run(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout=out, stderr="")

    rows = macos.processes(run)
    assert (2914, DESKTOP) in rows and (3011, HELPER) in rows
    assert macos.app_bundle_of(DESKTOP) == "/Applications/Claude.app"
