"""맥판 5단계 — 빠진 기능 채우기 (2026-11-03 · 전수조사 B3 · B6 · B7 · B8 · C5 · C7 · C8 · C9).

맥미니에서 직접 확인한 것: NFD 한글 이름을 NFC 로 찾으면 0건이었다(고친 뒤 1건) · 표시 언어 ko-KR 인데 로캘이 ('C', 'UTF-8')
이라 en 으로 읽었다(고친 뒤 ko). 여기서는 맥 갈래를 `sys.platform` 을 바꿔 끼워 윈도우 PC 에서도 돌린다.
"""

from __future__ import annotations

import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from alture_jarvis import file_open, mcp_language, notifications, scribe
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools, _nfc


@pytest.fixture
def mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")


class _Done:
    def __init__(self, code: int) -> None:
        self.returncode = code


def test_mac_open_uses_open_and_falls_back_to_text_editor_or_finder(tmp_path: Path, mac: None) -> None:
    calls: list[list[str]] = []
    target = tmp_path / "보고서.md"
    target.write_text("x", encoding="utf-8")
    assert file_open._open_on_mac(str(target), popen=calls.append, run=lambda *a, **k: _Done(0)) == "app"
    assert file_open._open_on_mac(str(target), popen=calls.append, run=lambda *a, **k: _Done(1)) == "notepad"
    assert calls[-1] == ["open", "-e", str(target)]
    other = tmp_path / "그림.xyz"
    other.write_text("x", encoding="utf-8")
    assert file_open._open_on_mac(str(other), popen=calls.append, run=lambda *a, **k: _Done(1)) == "revealed"
    assert calls[-1] == ["open", "-R", str(other)]


def test_mac_reveal_and_url(mac: None) -> None:
    calls: list[list[str]] = []
    assert file_open.reveal_file(Path("/Users/x/Documents/Sonjari/표.xlsx"), popen=calls.append)
    assert file_open.open_folder_or_url("https://example.com", popen=calls.append)
    assert calls == [["open", "-R", str(Path("/Users/x/Documents/Sonjari/표.xlsx"))], ["open", "https://example.com"]]


def test_mac_notification_goes_through_osascript(mac: None, monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[list[str]] = []
    monkeypatch.setattr(notifications.subprocess, "Popen", lambda args, **_k: launched.append(args))

    class Bus:
        def publish(self, *_a: object) -> None:
            pass

    result = notifications.NotificationService(Bus()).notify('끝 "남"', "엑셀을 만들었습니다")  # type: ignore[arg-type]
    assert result["ok"] and launched[0][:2] == ["osascript", "-e"]
    assert 'with title "끝 \\"남\\""' in launched[0][2]


def test_mac_shell_tool_is_described_as_sh_not_powershell(tmp_path: Path, mac: None) -> None:
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(tmp_path), data_dir=tmp_path / "d"))
    shell = next(d for d in tools._build_definitions() if d["function"]["name"] == "local_run_shell")
    text = shell["function"]["description"] + shell["function"]["parameters"]["properties"]["command"]["description"]
    assert "PowerShell" not in text and "grep" in text


def test_windows_shell_tool_still_says_powershell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(tmp_path), data_dir=tmp_path / "d"))
    shell = next(d for d in tools._build_definitions() if d["function"]["name"] == "local_run_shell")
    assert "PowerShell" in shell["function"]["description"]


def test_nfd_korean_names_are_found_with_nfc_queries(tmp_path: Path) -> None:
    """맥 파인더가 만든 이름(NFD)을 사람이 친 이름(NFC)으로 찾는다. NTFS 도 이름 바이트를 그대로 둬 여기서 잴 수 있다."""
    root = tmp_path / "docs"
    root.mkdir()
    (root / unicodedata.normalize("NFD", "계약서_최종.txt")).write_text("hello", encoding="utf-8")
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(root), data_dir=tmp_path / "d"))
    found = tools.search_files({"query": "계약서", "path": str(root)})
    assert found["count"] == 1
    # 돌려주는 경로는 **원본(NFD) 그대로** — NTFS · ext4 는 정규화를 가려서 NFC 로 바꾸면 못 연다(11-03 코드 검토).
    assert Path(found["items"][0]["path"]).read_text(encoding="utf-8") == "hello"
    globbed = tools.glob_files({"pattern": "계약서*", "path": str(root)})
    assert globbed["count"] == 1 and Path(globbed["items"][0]["path"]).is_file()
    assert _nfc("abc") == "abc"


def test_mac_language_reads_the_system_setting(mac: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_language, "_mac_first_language", lambda: "ko-KR")
    monkeypatch.setattr(mcp_language.locale, "getlocale", lambda: ("C", "UTF-8"))
    assert mcp_language.os_language() == "ko"
    monkeypatch.setattr(mcp_language, "_mac_first_language", lambda: "en-US")
    assert mcp_language.os_language() == "en"


def test_mac_first_language_parses_defaults_output(monkeypatch: pytest.MonkeyPatch) -> None:
    out = '(\n    "ko-KR",\n    "en-US"\n)\n'
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
    assert mcp_language._mac_first_language() == "ko-KR"


def test_mac_temp_projects_are_folded() -> None:
    assert scribe._is_temp("/private/var/folders/ab/xyz/T/bench")
    assert scribe._is_temp("-private-var-folders-ab-xyz-T-bench")
    assert not scribe._is_temp("/Users/d/dev/my-repo")


def test_rg_and_uniq_are_not_treated_as_read_only() -> None:
    """`rg --pre` 는 아무 프로그램이나 돌리고 `uniq a b` 는 b 에 쓴다 — 승인 없이 돌면 안 된다(11-03 코드 검토)."""
    from alture_jarvis.local_computer import _SHELL_READ_ONLY

    assert "rg" not in _SHELL_READ_ONLY and "uniq" not in _SHELL_READ_ONLY
    assert {"grep", "head", "tail"} <= _SHELL_READ_ONLY


def test_profile_argument_must_end_at_a_boundary(tmp_path: Path) -> None:
    from alture_jarvis.browser import BrowserWorker

    worker = BrowserWorker.__new__(BrowserWorker)
    profile = tmp_path / "browser-profile"
    worker.config = JarvisConfig(browser_profile_dir=profile, data_dir=tmp_path / "d")
    worker._found_browser_exe = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert worker._profile_arg_in(f"chrome --user-data-dir={profile} --no-first-run")
    assert worker._profile_arg_in(f"chrome --user-data-dir={profile}")
    assert not worker._profile_arg_in(f"chrome --user-data-dir={profile}-edge --no-first-run")
