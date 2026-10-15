"""MSIX 패키지 모드 — 밖의 앱에 알려 줄 경로 (W1, 2026-09-15).

실측(인수인계서 1.1): 패키지 앱이 AppData 에 **새로 만든** 파일은 앱 전용 칸으로 가고, 이미 있던
파일을 고치면 실제 파일이 바뀐다. 그래서 같은 문자열 경로가 우리 눈과 밖의 앱 눈에서 다른 파일이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis import msix
from alture_jarvis.config import JarvisConfig
from alture_jarvis.mcp_connect import MCP_ALIAS, ConnectService, server_entry

FAMILY = "RoboMetaFit.Jarvis_abc123xyz"


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    local = tmp_path / "AppData" / "Local"
    roaming = tmp_path / "AppData" / "Roaming"
    local.mkdir(parents=True)
    roaming.mkdir(parents=True)
    return local, roaming


def test_outside_a_package_paths_are_left_alone(tmp_path: Path) -> None:
    local, roaming = _dirs(tmp_path)
    token = local / "AltureJarvis" / "data" / "control.token"
    assert msix.external_path(token, family_name="", localappdata=local, appdata=roaming) == token


def test_a_new_token_resolves_to_the_private_cache(tmp_path: Path) -> None:
    local, roaming = _dirs(tmp_path)
    token = local / "AltureJarvis" / "data" / "control.token"
    private = local / "Packages" / FAMILY / "LocalCache" / "Local" / "AltureJarvis" / "data" / "control.token"
    # 아직 아무 데도 없다 → 만들면 전용 칸으로 간다.
    assert msix.external_path(token, family_name=FAMILY, localappdata=local, appdata=roaming) == private
    private.parent.mkdir(parents=True)
    private.write_text("t", encoding="utf-8")
    assert msix.external_path(token, family_name=FAMILY, localappdata=local, appdata=roaming) == private


def test_a_file_that_existed_before_install_stays_real(tmp_path: Path) -> None:
    local, roaming = _dirs(tmp_path)
    token = local / "AltureJarvis" / "data" / "control.token"
    token.parent.mkdir(parents=True)
    token.write_text("old", encoding="utf-8")
    assert msix.external_path(token, family_name=FAMILY, localappdata=local, appdata=roaming) == token


def test_roaming_and_other_package_and_home_paths(tmp_path: Path) -> None:
    local, roaming = _dirs(tmp_path)
    new_roaming = roaming / "Claude" / "claude_desktop_config.json"
    assert msix.external_path(new_roaming, family_name=FAMILY, localappdata=local, appdata=roaming) == (
        local / "Packages" / FAMILY / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
    )
    other = local / "Packages" / "Claude_pzs8" / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
    assert msix.external_path(other, family_name=FAMILY, localappdata=local, appdata=roaming) == other
    home_file = tmp_path / "RoboMetaFit" / "JARVIS" / "backup" / "x.db"
    assert msix.external_path(home_file, family_name=FAMILY, localappdata=local, appdata=roaming) == home_file


def test_package_detection_is_empty_on_a_normal_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_FAKE_PACKAGE_FULL_NAME", raising=False)
    # 시험을 도는 파이썬은 패키지가 아니다. ctypes 호출이 실제로 돌고 빈 값을 돌려줘야 한다.
    msix._cache.clear()
    assert msix.package_full_name() == ""
    assert msix.is_packaged() is False


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path / "rt", data_dir=tmp_path / "AppData" / "Local" / "AltureJarvis" / "data",
                        output_dir=tmp_path / "rt" / "outputs")


def test_packaged_entry_uses_the_alias_and_the_real_token_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("JARVIS_FAKE_PACKAGE_FULL_NAME", "RoboMetaFit.Jarvis_1.0.0.0_x64__abc123xyz")
    monkeypatch.setenv("JARVIS_FAKE_PACKAGE_FAMILY_NAME", FAMILY)
    entry = server_entry(_config(tmp_path))
    assert entry["command"] == str(local / "Microsoft" / "WindowsApps" / MCP_ALIAS)
    assert "PYTHONPATH" not in entry["env"]
    assert entry["env"]["JARVIS_TOKEN_FILE"] == str(
        local / "Packages" / FAMILY / "LocalCache" / "Local" / "AltureJarvis" / "data" / "control.token"
    )
    assert "secret" not in json.dumps(entry)


def test_unpackaged_entry_is_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_FAKE_PACKAGE_FULL_NAME", raising=False)
    monkeypatch.delenv("JARVIS_FAKE_PACKAGE_FAMILY_NAME", raising=False)
    msix._cache.clear()
    config = _config(tmp_path)
    entry = server_entry(config)
    assert entry["env"]["JARVIS_TOKEN_FILE"] == str(Path(config.data_dir) / "control.token")
    assert "PYTHONPATH" in entry["env"]


def test_packaged_desktop_without_a_config_file_asks_for_paste(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude Desktop 설치형인데 설정 파일이 아직 없다 → 새 파일은 전용 칸으로 가 Claude 가 못 본다(W1-5)."""
    home = tmp_path / "home"
    local = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    (roaming / "Claude").mkdir(parents=True)  # 앱은 깔렸고 폴더는 있는데 설정 파일은 없다
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("JARVIS_FAKE_PACKAGE_FULL_NAME", "RoboMetaFit.Jarvis_1.0.0.0_x64__abc123xyz")
    monkeypatch.setenv("JARVIS_FAKE_PACKAGE_FAMILY_NAME", FAMILY)
    service = ConnectService(_config(tmp_path), processes=lambda: [], home=home, appdata=roaming,
                             localappdata=local, which=lambda _name: None)
    scanned = next(c for c in service.scan()["clients"] if c["id"] == "claude_desktop")
    assert scanned["can_apply"] is False and scanned["reason"] == "msix_new_file_hidden"
    applied = service.apply("claude_desktop")
    assert applied["ok"] is False and applied["error"] == "msix_new_file_hidden"
    assert "mcpServers" in applied["manual"]
    assert not (roaming / "Claude" / "claude_desktop_config.json").exists()
    # 파일이 이미 있으면 고치기는 실제 파일에 닿으므로 그대로 잇는다.
    (roaming / "Claude" / "claude_desktop_config.json").write_text("{}", encoding="utf-8")
    assert service.apply("claude_desktop")["ok"] is True
