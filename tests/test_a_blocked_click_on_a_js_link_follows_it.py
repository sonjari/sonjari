"""누르기가 막힌 이동용 `javascript:` 링크는 그 함수로 따라간다 (2026-10-02 K-Startup 4차 판 70a447c4).

목록의 공고 `<a href="javascript:go_view(176076)">` 를 browser_click 으로 눌렀더니 겹친 요소에 막혀 8초 시간 초과.
새벽에 넣은 javascript 링크 따라가기는 browser_open 길에만 있었다 — 판은 검색칸·필터에 40걸음을 쓰고 상세를 하나만 읽었다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import browser as browser_mod
from alture_jarvis.site_traits import SiteTraits

LIST = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
DETAIL = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=176076"


class _Page:
    def __init__(self) -> None:
        self.url = LIST
        self.called: list[Any] = []

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if "typeof window[n]" in script:
            return arg in {"go_view", "fn_delete"}
        self.called.append(arg)
        self.url = DETAIL
        return None

    def expect_navigation(self, timeout: int = 0):
        from contextlib import nullcontext

        return nullcontext()

    def wait_for_timeout(self, _ms: int) -> None:
        return None

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "공고 상세"


class _Link:
    def __init__(self, href: str, label: str) -> None:
        self.href, self.label = href, label

    def get_attribute(self, name: str, timeout: int = 0) -> str | None:
        return {"href": self.href}.get(name)

    def inner_text(self, timeout: int = 0) -> str:
        return self.label

    def evaluate(self, script: str) -> str:
        return "a"


class _Config:
    browser_read_only = False


def _worker(tmp_path: Path, page: _Page, link: _Link) -> Any:
    worker = browser_mod.BrowserWorker.__new__(browser_mod.BrowserWorker)
    worker._context = None
    worker._page = page
    worker._last_dialog = None
    worker.config = _Config()
    worker._site_traits = SiteTraits(tmp_path / "site_traits.json")
    worker._wait_until_operable = lambda p, **k: {"count": 12, "ms": 5, "polls": 1}
    worker._mark_visited = lambda url: None
    worker._ref_locator = lambda p, ref: link
    worker._show_visual = lambda *a, **k: None
    worker._toggle_state = lambda locator: None

    def blocked(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("browser_click_failed:Locator.click: Timeout 8000ms exceeded")

    worker._guarded_click = blocked
    return worker


def _function_calls(page: "_Page") -> list:
    """링크의 함수를 부른 것만 — 누르기 전에 화면 지문을 읽는 호출(2026-10-07 부터 모든 클릭이 뜬다)은 세지 않는다."""
    return [call for call in page.called if isinstance(call, list)]


def test_a_blocked_click_on_a_navigation_link_follows_the_function(tmp_path: Path) -> None:
    page = _Page()
    worker = _worker(tmp_path, page, _Link("javascript:go_view(176076);", "2026년 팁스(TIPS) 창업기업 지원계획 수정 공고"))
    result = worker._click(page, {"ref": "j32"})
    assert _function_calls(page) == [["go_view", [176076]]]
    assert result["url"] == DETAIL and result["clicked_via_js_link"] is True
    assert "대신 따라갔다" in result["instruction"]


def test_an_acting_function_is_not_called_for_a_blocked_click(tmp_path: Path) -> None:
    page = _Page()
    worker = _worker(tmp_path, page, _Link("javascript:fn_delete(3)", "관리"))
    with pytest.raises(RuntimeError, match="browser_click_failed"):
        worker._click(page, {"ref": "j9"})
    assert _function_calls(page) == []


def test_an_ordinary_link_failure_still_fails(tmp_path: Path) -> None:
    page = _Page()
    worker = _worker(tmp_path, page, _Link("https://www.k-startup.go.kr/web/main.do", "홈"))
    with pytest.raises(RuntimeError, match="browser_click_failed"):
        worker._click(page, {"ref": "j1"})
