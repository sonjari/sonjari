"""부정 버튼이 없는 창은 Esc 로 닫아 본다 (2026-09-26 A/B 벤치 · 네이버 날씨 「지역 설정」)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from alture_jarvis.browser import BrowserWorker


class _Page:
    def __init__(self, closes_on_escape: bool) -> None:
        self.open, self.closes_on_escape, self.keys = True, closes_on_escape, []
        self.keyboard = SimpleNamespace(press=self._press)

    def _press(self, key: str) -> None:
        self.keys.append(key)
        if key == "Escape" and self.closes_on_escape:
            self.open = False

    def wait_for_timeout(self, _ms: int) -> None:
        return None


def _worker(page: _Page) -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._first_visible_popup = lambda _page: object() if page.open else None  # type: ignore[method-assign]
    worker._dismiss_one_popup = lambda _popup: {"dismissed": False, "text": "지역 설정 최근 본 지역", "buttons": []}  # type: ignore[method-assign]
    return worker


def test_a_panel_without_a_negative_button_closes_with_escape() -> None:
    page = _Page(closes_on_escape=True)
    records = _worker(page)._dismiss_dialogs(page, rounds=2)
    assert page.keys == ["Escape"] and records[0]["dismissed"] and records[0]["button"] == "Esc"


def test_when_escape_does_nothing_the_error_says_to_use_the_panel() -> None:
    page = _Page(closes_on_escape=False)
    with pytest.raises(RuntimeError) as caught:
        _worker(page)._dismiss_dialogs(page, rounds=1)
    message = str(caught.value)
    assert message.startswith("browser_popup_blocking:지역 설정")
    assert "그 창 안의" in message, "모델이 스스로 연 창이면 닫지 말고 창 안을 누르라고 알려야 한다"
