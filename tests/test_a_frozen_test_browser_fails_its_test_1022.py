"""시험이 띄운 크롬이 멈추면 **그 시험의 실패**가 된다 — 작업자가 통째로 죽지 않는다 (2026-10-22 밤 · tests/conftest.py 감시).

10-19 ~ 10-22 전체 회귀 기록 6판에서 크롬 시험 하나가 돌아오지 않았고, 300초 감시가 작업자를 끝내 「worker 'gw10' crashed」 한 줄만
남았다(스택은 출력 가로채기 임시 파일과 함께 사라졌다). 이제 감시는 크롬 시험이 멈추면 진단을 먼저 적고 **그 시험이 띄운 크롬만**
끝낸다. 이 시험은 그 약속을 실제 크롬으로 본다: 크롬을 얼려 `page.evaluate` 가 영원히 기다리게 만들면 →
감시가 끝내고 → Playwright 가 오류를 내고 → 같은 프로세스에서 다음 크롬이 정상으로 뜬다.
"""
from __future__ import annotations

import sys
import time

import pytest


def _watchdog_module():  # type: ignore[no-untyped-def]
    for module in list(sys.modules.values()):
        if hasattr(module, "_BROWSER_STALL_SEC") and hasattr(module, "_watchdog_state"):
            return module
    pytest.fail("tests/conftest.py 의 크롬 감시를 찾지 못했다")


def test_deliberate_browser_stall_a_frozen_test_browser_is_ended_and_the_test_gets_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    psutil = pytest.importorskip("psutil")
    watchdog = _watchdog_module()
    monkeypatch.setattr(watchdog, "_BROWSER_STALL_SEC", 5)
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        page = browser.new_page()
        page.set_content("<p>frozen</p>")
        for child in psutil.Process().children(recursive=True):
            if child.name().lower().startswith(("chrome", "headless_shell")):
                child.suspend()
        started = time.monotonic()
        with pytest.raises(Exception, match="closed"):
            page.evaluate("1 + 1")  # 얼린 크롬 — 감시가 끝내야 풀린다
        waited = time.monotonic() - started
        try:
            browser.close()
        except Exception:  # noqa: BLE001 — 이미 끝난 브라우저
            pass
    assert waited < 60, f"감시가 {waited:.0f}초 만에야 풀었다"
    stalled = watchdog._watchdog_state["stalled"].get(
        __import__("os").environ.get("PYTEST_CURRENT_TEST", "").rsplit(" ", 1)[0], "")
    assert "자손" in stalled and "끝낸 크롬" in stalled, stalled[:500]

    # 같은 프로세스에서 다음 크롬은 멀쩡히 뜬다(감시가 이 프로세스를 망가뜨리지 않는다).
    with playwright_api.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<b>ok</b>")
        assert page.inner_text("b") == "ok"
        browser.close()
