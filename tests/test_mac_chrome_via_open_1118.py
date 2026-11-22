"""맥에서 크롬을 `open -a` 로 띄운다 — 크롬이 제 허락 책임자가 되어 「python3.12 가 앱을 수정 · 로컬 네트워크 · 다른 앱 데이터」
창이 손자리 이름으로 뜨지 않게(2026-11-18 · 맥 새 계정 시험). 실제로 창이 사라지는지는 새 계정에서 확인한다 — 여기선 띄우는 모양만."""
from __future__ import annotations

import subprocess

import pytest

import alture_jarvis.browser as browser_module
from alture_jarvis.browser import BrowserWorker, _OpenedProcess

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE = "/Users/x/Library/Application Support/Sonjari/data/chrome-profile"


def _worker(scans: list[dict[int, str]]):
    worker = BrowserWorker.__new__(BrowserWorker)
    calls = iter(scans)
    worker._chrome_scan = lambda max_age_sec=1.0: next(calls, scans[-1])
    return worker


def test_it_opens_the_app_bundle_through_launchservices_and_finds_our_main_process(monkeypatch) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(browser_module.subprocess, "run", lambda args, **_kw: ran.append(args))
    worker = _worker([
        {},
        {501: f"{CHROME} --type=renderer --user-data-dir={PROFILE}",
         502: f"{CHROME} --remote-debugging-port=9222 --user-data-dir={PROFILE} --no-first-run",
         777: f"{CHROME} --user-data-dir=/Users/x/Library/Application Support/Google/Chrome"},
    ])
    proc = worker._mac_open_chrome([CHROME, "--remote-debugging-port=9222", f"--user-data-dir={PROFILE}", "--no-first-run"])
    assert ran == [["/usr/bin/open", "-n", "-g", "-a", "/Applications/Google Chrome.app", "--args",
                    "--remote-debugging-port=9222", f"--user-data-dir={PROFILE}", "--no-first-run"]]
    assert isinstance(proc, _OpenedProcess) and proc.pid == 502, "사람의 크롬(777) · 렌더러(501)가 아니라 우리 프로필의 본 프로세스"


def test_it_says_so_when_chrome_never_shows_up(monkeypatch) -> None:
    monkeypatch.setattr(browser_module.subprocess, "run", lambda *_a, **_kw: None)
    monkeypatch.setattr(BrowserWorker, "MAC_OPEN_FIND_SEC", 0.2)
    with pytest.raises(RuntimeError, match="browser_start_failed"):
        _worker([{}])._mac_open_chrome([CHROME, f"--user-data-dir={PROFILE}"])


def test_the_wrapper_answers_like_popen(monkeypatch) -> None:
    alive = {"yes": True}
    sent: list[int] = []

    def fake_kill(pid: int, number: int) -> None:
        if number == 0 and not alive["yes"]:
            raise ProcessLookupError
        sent.append(number)

    monkeypatch.setattr(browser_module.os, "kill", fake_kill)
    proc = _OpenedProcess(502)
    assert proc.poll() is None
    proc.terminate()
    assert sent[-1] != 0
    alive["yes"] = False
    assert proc.poll() == 0 and proc.wait(timeout=1) == 0
    with pytest.raises(subprocess.TimeoutExpired):
        alive["yes"] = True
        _OpenedProcess(503).wait(timeout=0.1)
