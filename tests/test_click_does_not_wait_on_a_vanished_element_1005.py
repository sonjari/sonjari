"""링크를 눌러 넘어간 뒤 **사라진 요소를 16초 기다렸다** (2026-10-05 AWS 영어 윈도우 첫 실행).

GitHub 인기 저장소 판(ac2bd8ec, 233초): `browser_click` 세 번이 19,297 · 19,266 · 19,436ms.
누른 뒤 같은 요소를 두 번 더 찾았다 — 누름 표시 자리(`bounding_box`) 8초 + 토글 상태(`get_attribute`) 8초 + 페이지 대기 3초.
이 PC 운영 기록도 같았다: 주소가 바뀌는 클릭 28번 중 24번이 7초 이상(가운데값 11.5초).
실제 크롬: 클릭 0.58초 · 자리 재기 8.01초 · 속성 읽기 8.00초 · 세기(`count`) 0.03초.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker


class _Gone:
    """다른 페이지로 넘어가 사라진 요소 — 세면 0, 찾으면 기본 대기만큼 기다린 뒤 실패한다."""

    def __init__(self) -> None:
        self.waited_on: list[str] = []

    def count(self) -> int:
        return 0

    def bounding_box(self) -> dict[str, float]:
        self.waited_on.append("bounding_box")
        raise RuntimeError("Timeout 8000ms exceeded")

    def get_attribute(self, name: str) -> str | None:
        self.waited_on.append(f"get_attribute:{name}")
        raise RuntimeError("Timeout 8000ms exceeded")


class _Page:
    url = "https://github.com/earthtojake/text-to-cad"

    def __init__(self) -> None:
        self.drawn: list[dict[str, Any]] = []

    def is_closed(self) -> bool:
        return False

    def evaluate(self, script: str, arg: Any = None) -> None:
        self.drawn.append(arg)


def test_counting_says_whether_it_is_still_there() -> None:
    assert BrowserWorker._still_there(_Gone()) is False
    assert BrowserWorker._still_there(SimpleNamespace(count=lambda: 1)) is True
    assert BrowserWorker._still_there(object()) is True, "셀 줄 모르는 것은 예전대로 있다고 본다"

    def broken() -> int:
        raise RuntimeError("Execution context was destroyed, most likely because of a navigation")

    assert BrowserWorker._still_there(SimpleNamespace(count=broken)) is False, "넘어가는 중이면 그 요소도 없다"


def test_the_press_mark_does_not_measure_an_element_that_is_gone() -> None:
    worker = object.__new__(BrowserWorker)
    worker.config = SimpleNamespace(browser_visual_overlay=True)
    gone, page = _Gone(), _Page()

    worker._show_visual(page, "text-to-cad 선택", locator=gone, pulse=True)

    assert gone.waited_on == [], "사라진 요소의 자리를 재지 않는다(8초)"
    assert page.drawn and page.drawn[0]["x"] is None, "자리 없이 표시만 그린다"


def test_the_click_path_reads_the_toggle_again_only_when_there_was_one() -> None:
    import inspect

    source = inspect.getsource(BrowserWorker._click)
    assert "self._toggle_state(locator) if toggle_before and self._still_there(locator) else None" in source


def test_in_a_real_browser_the_gone_element_is_known_at_once() -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            # 누르면 화면이 통째로 바뀌어 그 링크가 사라진다(다른 페이지로 넘어간 것과 같은 모양 — 크롬은 data: 주소로의 이동을 막는다).
            page.set_content("""<a id="go" href="#" onclick="document.body.innerHTML='<p>next page</p>'">go</a>""")
            locator = page.locator("#go")
            assert BrowserWorker._still_there(locator) is True
            locator.click()
            started = time.monotonic()
            assert BrowserWorker._still_there(locator) is False
            assert time.monotonic() - started < 2.0, "기다리지 않고 안다"
        finally:
            browser.close()


# ── 뒤로 가기: 돌아갔는지는 주소로 본다 ──────────────────────────────────────────────────────
#
# 같은 판의 `browser_back` 두 번이 8,108 · 8,016ms 였고(이 PC 운영 기록 26번 중 5번도 8초), 결과는 「뒤로 가기가 안 끝나
# 그만뒀다(화면은 그대로일 수 있다)」였다 — 실제로는 목록으로 **돌아가 있었다**(증거의 주소가 목록). GitHub 는 화면을 스스로
# 바꿔 끼워서 문서 이벤트가 새로 안 온다.


class _SelfSwappingSite:
    """뒤로 가면 주소는 바뀌는데 `go_back` 의 기다림은 시간 초과가 나는 사이트."""

    def __init__(self, *, really_goes_back: bool) -> None:
        self.url = "https://github.com/earthtojake/text-to-cad"
        self._really = really_goes_back
        self.asked: list[dict[str, Any]] = []
        self.waited_ms = 0

    def go_back(self, **kwargs: Any) -> None:
        self.asked.append(kwargs)
        if self._really:
            self.url = "https://github.com/trending/python"
        raise TimeoutError("Timeout 2500ms exceeded")

    def wait_for_timeout(self, ms: int) -> None:
        self.waited_ms += ms

    def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        # 되살린 화면에는 「읽기 끝」 신호가 다시 안 온다 — 이것을 기다리면 5초를 꽉 채운다(2026-10-05 아침 15/15).
        raise AssertionError("뒤로 간 뒤에는 읽기 끝 신호를 기다리지 않는다 — 문서 상태를 직접 묻는다")

    def evaluate(self, script: str) -> str:
        assert "readyState" in script
        return "complete"


class _RestoredFromCache(_SelfSwappingSite):
    """이동은 바로 시작되는데(시간 초과 없음) 주소가 정말 바뀌었는지는 따로 봐야 하는 화면."""

    def go_back(self, **kwargs: Any) -> None:
        self.asked.append(kwargs)
        if self._really:
            self.url = "https://github.com/trending/python"


def _back_worker() -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._last_results = []
    worker._page = None
    worker._last_dialog = None
    return worker


def test_a_back_whose_wait_timed_out_but_whose_address_changed_did_go_back() -> None:
    page = _SelfSwappingSite(really_goes_back=True)

    out = BrowserWorker._back(_back_worker(), page, {})

    assert out["action"] == "went_back", out
    assert "그만뒀다" not in str(out.get("instruction") or "")
    assert page.asked == [{"wait_until": "commit", "timeout": BrowserWorker._BACK_COMMIT_MS}]
    assert page.waited_ms == 0, "주소가 이미 바뀌었으면 더 기다리지 않는다"


def test_a_back_that_really_went_nowhere_still_says_so() -> None:
    worker = _back_worker()
    worker._BACK_URL_WATCH_SEC = 0.05  # type: ignore[misc]
    page = _SelfSwappingSite(really_goes_back=False)

    out = BrowserWorker._back(worker, page, {})

    assert out["action"] == "back_timed_out", out


# ── 뒤로 가기 5초의 정체 (2026-10-05 아침) ─────────────────────────────────────────────────────
#
# 직접 띄운 크롬에 붙은 조건에서 GitHub·해커뉴스·arXiv 각 5번: 주소는 0.1초 만에 바뀌는데 `wait_for_load_state` 가 15번 전부
# 5초를 채웠다. 문서 상태를 직접 물으면 0.0~0.1초. 그리고 운영 브라우저의 한 판은 「went_back」이라면서 주소가 상세 그대로였다.


def test_a_restored_page_is_ready_without_waiting_for_a_load_event() -> None:
    page = _RestoredFromCache(really_goes_back=True)

    out = BrowserWorker._back(_back_worker(), page, {})

    assert out["action"] == "went_back", out
    assert page.waited_ms == 0


def test_a_back_that_started_but_never_changed_the_address_is_not_called_done() -> None:
    worker = _back_worker()
    worker._BACK_URL_SETTLE_SEC = 0.05  # type: ignore[misc]
    page = _RestoredFromCache(really_goes_back=False)

    out = BrowserWorker._back(worker, page, {})

    assert out["action"] == "back_timed_out", out


def test_document_ready_gives_up_instead_of_spinning() -> None:
    class _NeverReady:
        def evaluate(self, script: str) -> str:
            return "loading"

        def wait_for_timeout(self, ms: int) -> None:
            raise RuntimeError("page closed")

    assert BrowserWorker._wait_document_ready(_NeverReady(), timeout_sec=5.0) is False

