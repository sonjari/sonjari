"""맥 Ollama 설치(2026-11-03 · 설계 D4 뒤집음 — 마법사가 직접 깐다).

맥미니에서 실제로 잰 것: 공식 `Ollama-darwin.zip`(v0.40.13 · 219MB) 받기 → 해시 대조 → `ditto` 풀기 → 서명 · 팀 · 공증 확인이
22.9초에 끝났고, 받은 앱에 quarantine 표시가 없었다. 여기서는 **거르는 쪽**을 본다 — 해시 · 서명 · 팀 · 공증 중 하나라도 어긋나면 안 깐다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from alture_jarvis import ollama_install
from alture_jarvis.ollama_install import MAC_ASSET_NAME, MAC_TEAM_ID, OllamaInstaller, verify_mac_app


def _runner(verify: int = 0, team: str = MAC_TEAM_ID, spctl: str = "accepted\nsource=Notarized Developer ID",
            spctl_code: int = 0):
    def run(args, **_k):  # noqa: ANN001, ANN202
        if args[:2] == ["codesign", "--verify"]:
            return subprocess.CompletedProcess(args, verify, stdout="", stderr="" if verify == 0 else "modified")
        if args[:2] == ["codesign", "-dv"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr=f"Identifier=com.electron.ollama\nTeamIdentifier={team}\n")
        return subprocess.CompletedProcess(args, spctl_code, stdout="", stderr=spctl)
    return run


def test_official_signed_notarized_app_passes() -> None:
    assert verify_mac_app(Path("/x/Ollama.app"), run=_runner())["ok"] is True


@pytest.mark.parametrize("kwargs, reason", [
    ({"verify": 1}, "codesign_verify_failed"),
    ({"team": "ABCDE12345"}, "wrong_team"),
    ({"spctl": "rejected", "spctl_code": 3}, "not_notarized"),
    ({"spctl": "accepted\nsource=Developer ID"}, "not_notarized"),
])
def test_tampered_or_foreign_apps_are_refused(kwargs: dict, reason: str) -> None:
    result = verify_mac_app(Path("/x/Ollama.app"), run=_runner(**kwargs))
    assert result["ok"] is False and result["reason"] == reason


def test_mac_asks_for_the_mac_asset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    installer = OllamaInstaller(install_root=tmp_path)
    assert installer.asset_name == MAC_ASSET_NAME
    sums = f"{'a' * 64}  ./ollama-windows-amd64.zip\n{'b' * 64}  ./{MAC_ASSET_NAME}\n"
    installer._latest_page_url = lambda: "https://github.com/ollama/ollama/releases/tag/v0.40.13"
    installer._fetch_bytes = lambda url: sums.encode()
    resolved = installer._resolve_without_api()
    assert resolved["url"].endswith(MAC_ASSET_NAME) and resolved["sha256"] == "b" * 64


def test_hash_mismatch_installs_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    installer = OllamaInstaller(install_root=tmp_path)
    installer.resolve = lambda: {"version": "v1", "url": "u", "sha256": "0" * 64, "size": "3"}
    installer._download = lambda url, target, progress: target.write_bytes(b"bad")
    target = tmp_path / "Applications" / "Ollama.app"
    installer.mac_app_target = lambda: target
    assert installer.install_mac() == {"ok": False, "error": "hash_mismatch"}
    assert not target.exists()


def test_mac_app_folder_counts_as_an_installed_system_app(tmp_path: Path) -> None:
    app = tmp_path / "Ollama.app"
    app.mkdir()
    installer = OllamaInstaller(install_root=tmp_path, system_apps=(app,))
    assert installer.system_app() == app
    assert ollama_install.MAC_TEAM_ID == "3MU9H2V9Y9"
