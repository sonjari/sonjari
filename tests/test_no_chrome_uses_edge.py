"""크롬이 없으면 엣지로 브라우저 일을 한다 (2026-09-29 밤, AWS 윈도우 서버 첫 실행).

## 무슨 일이 있었나

크롬 없는 깨끗한 윈도우(엣지는 있음)에서 「YES24 에서 파이썬 입문서 3권…」:
「떠 있는 크롬에 붙지 못했습니다 · chrome_not_found — JARVIS_BROWSER_CHROME_PATH 를 알려주세요」 →
「Executable doesn't exist … ms-playwright\\chromium-1234 … Please run playwright install」 영어 원문. 시킨 것 0/3.

`_find_chrome` 는 구글 크롬만 찾았고, 띄우기가 실패하면 포장에 없는 Playwright 번들 크로미움으로 다시 시도했다.

## 규칙

크롬 → 없으면 엣지(윈도우 10/11 에 늘 있다) → 둘 다 없으면 사람 말. 엣지 프로필은 **다른 폴더**.
창·프로세스를 가려내는 이름도 찾은 브라우저를 따른다(`chrome.exe` 로 박혀 있으면 엣지 창을 못 알아본다).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis import browser as browser_module
from alture_jarvis.browser import NO_BROWSER_MESSAGE, BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path: Path) -> BrowserWorker:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.browser_chrome_path = ""
    config.browser_profile_dir = tmp_path / "browser-profile"
    return BrowserWorker(config)


def _install(root: Path, *parts: str) -> Path:
    exe = root.joinpath(*parts)
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"")
    return exe


@pytest.fixture
def clean_pc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pc = tmp_path / "pc"
    for variable, name in (("PROGRAMFILES", "pf"), ("PROGRAMFILES(X86)", "pf86"), ("LOCALAPPDATA", "local")):
        monkeypatch.setenv(variable, str(pc / name))
    monkeypatch.setattr(browser_module.sys, "platform", "win32")
    monkeypatch.setattr(browser_module.shutil, "which", lambda name: None)
    return pc


def test_chrome_is_still_first(tmp_path: Path, clean_pc: Path) -> None:
    chrome = _install(clean_pc, "pf", "Google", "Chrome", "Application", "chrome.exe")
    _install(clean_pc, "pf86", "Microsoft", "Edge", "Application", "msedge.exe")
    worker = _worker(tmp_path)
    assert worker._find_chrome() == str(chrome)
    assert worker._exe_name == "chrome.exe"
    assert worker._profile_dir == tmp_path / "browser-profile"


def test_no_chrome_picks_edge_with_its_own_profile(tmp_path: Path, clean_pc: Path) -> None:
    edge = _install(clean_pc, "pf86", "Microsoft", "Edge", "Application", "msedge.exe")
    worker = _worker(tmp_path)
    assert worker._find_chrome() == str(edge)
    assert worker._is_edge
    assert worker._exe_name == "msedge.exe"
    assert worker._profile_dir == tmp_path / "browser-profile-edge"


def test_neither_speaks_korean_without_env_names(tmp_path: Path, clean_pc: Path) -> None:
    worker = _worker(tmp_path)
    with pytest.raises(RuntimeError) as caught:
        worker._find_chrome()
    message = str(caught.value)
    assert message == NO_BROWSER_MESSAGE
    assert "크롬이나 엣지" in message
    assert "JARVIS_" not in message and "playwright" not in message.lower()
    assert worker._browser_exe() == ""
    assert worker._exe_name == "chrome.exe"  # 못 찾았을 땐 예전 이름 그대로 — 달라지는 것이 없다
