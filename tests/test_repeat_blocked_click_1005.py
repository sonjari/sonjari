"""같은 것이 그대로 가리고 있는 자리를 또 누르면 기다리지 않고 바로 알린다 (2026-10-05 사다리 L2).

모델이 만든 페이지의 카드 덧씌움(`.card::before`)이 버튼을 가렸다. 가로막힌 클릭 한 번이 17초(기다렸다 누르기 두 번)였고,
모델은 같은 버튼을 여덟 번 눌렀다 — 그 판이 226초에서 600초가 됐다. 첫 시도는 그대로 기다린다(잠깐 뜨는 가림막은 걷힌다).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker

COVER = "<조상>div.card.g1 | 북극 해빙 · 노르웨이"


class _Locator:
    def __init__(self, blocked: bool = True) -> None:
        self.blocked, self.clicks = blocked, 0

    def click(self, timeout: int = 0, **_kw: Any) -> None:
        self.clicks += 1
        if self.blocked:
            raise RuntimeError("Timeout 8000ms exceeded — <div class=card> intercepts pointer events")


class _Page:
    url = "http://127.0.0.1:63296/index.html"


def _worker(blocker: list[str]) -> BrowserWorker:
    worker = object.__new__(BrowserWorker)
    worker.config = SimpleNamespace(browser_action_timeout_sec=8)
    worker._intercepting_element = lambda locator: blocker[0]  # type: ignore[method-assign]
    worker._first_visible_popup = lambda page: None  # type: ignore[method-assign]
    worker._dismiss_dialogs = lambda page, prefix="browser": None  # type: ignore[method-assign]
    worker._clear_blocker = lambda page, locator, timeout=0: False  # type: ignore[method-assign]
    return worker


def test_the_first_blocked_click_waits_and_retries_as_before() -> None:
    blocker = [COVER]
    locator = _Locator()

    with pytest.raises(RuntimeError) as failed:
        _worker(blocker)._guarded_click(locator, what="관측 시작", page=_Page())

    assert locator.clicks == 2, "첫 시도는 예전대로: 누르기 → 가림막 치우기 → 한 번 더"
    assert "browser_click_intercepted:관측 시작:" in str(failed.value)


def test_the_same_blocked_spot_is_not_waited_on_again() -> None:
    blocker = [COVER]
    worker = _worker(blocker)
    locator = _Locator()
    with pytest.raises(RuntimeError):
        worker._guarded_click(locator, what="관측 시작", page=_Page())
    before = locator.clicks

    with pytest.raises(RuntimeError) as again:
        worker._guarded_click(locator, what="관측 시작", page=_Page())

    assert locator.clicks == before, "같은 가림막이 그대로면 다시 눌러 보지 않는다(17초를 또 쓰지 않는다)"
    assert "다시 눌러도 같다" in str(again.value)


def test_an_ancestor_cover_is_named_as_an_overlay() -> None:
    with pytest.raises(RuntimeError) as failed:
        _worker([COVER])._guarded_click(_Locator(), what="관측 시작", page=_Page())

    assert "조상" in str(failed.value) and "pointer-events:none" in str(failed.value)


def test_once_the_cover_is_gone_the_click_is_tried_again() -> None:
    blocker = [COVER]
    worker = _worker(blocker)
    locator = _Locator()
    with pytest.raises(RuntimeError):
        worker._guarded_click(locator, what="관측 시작", page=_Page())

    blocker[0] = ""          # 페이지를 고쳐 덧씌움이 사라졌다
    locator.blocked = False
    before = locator.clicks
    worker._guarded_click(locator, what="관측 시작", page=_Page())

    assert locator.clicks == before + 1


def test_a_different_target_is_not_refused() -> None:
    blocker = [COVER]
    worker = _worker(blocker)
    with pytest.raises(RuntimeError):
        worker._guarded_click(_Locator(), what="관측 시작", page=_Page())
    other = _Locator(blocked=False)
    blocker[0] = ""

    worker._guarded_click(other, what="◀ 닫기", page=_Page())

    assert other.clicks == 1
