"""맥판 안전 구멍 (2026-11-03 · 전수조사 B15).

윈도우 거절 목록은 `SystemRoot` · `ProgramFiles` 같은 환경변수로 시스템 자리를 찾는다. 맥에는 그 변수가 없어
목록이 통째로 건너뛰어졌다. 또 읽기 범위가 홈 전체라, 맥의 `~/Library` 아래 크롬 쿠키 · 키체인 · 클로드 앱 쿠키가
그대로 열려 있었다(윈도우는 `User Data` 낱말로 걸렸다).

**양방향**: 막혀야 할 것은 막히고, 평범한 문서 · 깊은 작업 폴더는 그대로 열려야 한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

H = Path("/Users/someone")


@pytest.mark.parametrize(
    "path",
    [
        H / "Library" / "Keychains" / "login.keychain-db",
        H / "Library" / "Cookies" / "Cookies.binarycookies",
        H / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "History",
        H / "Library" / "Application Support" / "Microsoft Edge" / "Default" / "Preferences",
        H / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser" / "Default" / "History",
        H / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        Path("C:/Users/someone/AppData/Roaming/Claude/Cookies"),
        Path("C:/Users/someone/AppData/Roaming/Claude/config.json"),
        H / "Documents" / "old-profile" / "Cookies",
        H / "Documents" / "old-profile" / "Web Data",
    ],
)
def test_browser_profiles_keychains_and_claude_app_are_secret(path: Path) -> None:
    assert LocalComputerTools._is_sensitive(path) is True


@pytest.mark.parametrize(
    "path",
    [
        H / "Documents" / "chrome 확장 기획.docx",
        H / "Documents" / "claude" / "notes.md",
        H / "Documents" / "cookies_policy.md",
        H / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "보고서.xlsx",
        H / "Desktop" / "Application Support" / "readme.txt",
    ],
)
def test_ordinary_documents_stay_open(path: Path) -> None:
    assert LocalComputerTools._is_sensitive(path) is False


def _tools(tmp_path: Path) -> LocalComputerTools:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    return LocalComputerTools(
        JarvisConfig(local_file_allowed_roots=str(allowed), data_dir=tmp_path / "data")
    )


@pytest.mark.parametrize(
    "pick",
    ["/System/Library", "/Applications/Safari.app", "/Library", "/private/etc", "/usr/local",
     "/Volumes/USB", "~/Library", "~/Library/Application Support", "/private/tmp", "/private/var/folders",
     "/private/var/folders/ab/cd/T", "/private/var/vm", "/private"],
)
def test_mac_system_places_are_too_broad(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pick: str) -> None:
    tools = _tools(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    path = Path(pick.replace("~", str(home))).resolve(strict=False)
    assert tools._too_broad_for_workspace(path) != ""


@pytest.mark.parametrize("pick", ["~/dev/my-repo", "~/Library/Mobile Documents/repo", "/Volumes/USB/work/repo",
                                  "/private/tmp/my-repo", "/private/var/folders/ab/cd/T/repo"])
def test_mac_repos_are_still_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pick: str) -> None:
    tools = _tools(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    path = Path(pick.replace("~", str(home))).resolve(strict=False)
    assert tools._too_broad_for_workspace(path) == ""


def test_mac_rules_do_not_apply_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """윈도우에서 `/Library` 는 「현재 드라이브의 Library 폴더」라 평범한 폴더다 — 맥 규칙이 새면 안 된다."""
    tools = _tools(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    assert tools._too_broad_for_workspace(Path("/Library/project").resolve(strict=False)) == ""
