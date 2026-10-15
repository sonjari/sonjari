"""`javascript:go_view(N)` 링크와 「통한 길」 기억 (2026-10-02 대표 운영 판, K-Startup 두 번째 판).

K-Startup 목록의 공고 링크는 주소가 아니라 `javascript:go_view(178802)` 였다. browser_open 은 앞에 `https://` 를 붙여
엉뚱한 주소를 만들었고, 모델은 번호로 상세 주소를 **짐작**했다(`bizpbanc-view.do?id=N` — 본문이 빈 껍데기). 1시간 전 판에서
본문을 읽어 낸 진짜 모양(`bizpbanc-ongoing.do?schM=view&pbancSn=N`)은 기록에 없었다. 열 걸음을 헛돌다
`wrapped_up:no_progress` 로 접혔다(39걸음, 5개 중 3개, 파일 없음).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import browser as browser_mod
from alture_jarvis.browser import _js_literal_args, _read_route_pattern, _route_pattern
from alture_jarvis.site_traits import SiteTraits

LIST = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
DETAIL = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=178802"


def test_literal_arguments_only() -> None:
    assert _js_literal_args("178802") == [178802]
    assert _js_literal_args(" 'A12', 3 ") == ["A12", 3]
    assert _js_literal_args("") == []
    assert _js_literal_args("this.value") is None
    assert _js_literal_args("fetch('/x')") is None


def test_route_pattern_templates_the_argument() -> None:
    assert _route_pattern(DETAIL, [178802]) == "/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn={1}"
    assert _route_pattern("https://x.kr/a/b", [178802]) == ""


def test_read_route_pattern_drops_noise_and_numbers() -> None:
    saramin = ("https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=search&rec_idx=51000004&location=ts"
               "&searchword=%EC%97%AC&search_uuid=9943af0a-b94d-47dd-b8f9-8a78fcb18623")
    assert _read_route_pattern(saramin) == "/zf_user/jobs/relay/view?view_type=search&rec_idx={n}&searchword=%EC%97%AC"
    assert _read_route_pattern("https://www.perplexity.ai/hub/pricing") == "/hub/pricing"
    assert _read_route_pattern("https://www.k-startup.go.kr/") == ""


class _Page:
    def __init__(self, url: str, functions: set[str], goes_to: str) -> None:
        self.url = url
        self.functions = functions
        self.goes_to = goes_to
        self.called: list[Any] = []

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if "typeof window[n]" in script:
            return arg in self.functions
        self.called.append(arg)
        self.url = self.goes_to
        return None

    @contextmanager
    def expect_navigation(self, timeout: int = 0):
        yield

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "상세"


def _worker(tmp_path: Path, page: _Page) -> Any:
    worker = browser_mod.BrowserWorker.__new__(browser_mod.BrowserWorker)
    worker._context = None
    worker._page = page
    worker._last_dialog = None
    worker._site_traits = SiteTraits(tmp_path / "site_traits.json")
    worker._wait_until_operable = lambda p, **k: {"count": 12, "ms": 5, "polls": 1}
    worker._mark_visited = lambda url: None
    return worker


def test_a_javascript_link_is_followed_through_the_page_function(tmp_path: Path) -> None:
    page = _Page(LIST, {"go_view"}, DETAIL)
    worker = _worker(tmp_path, page)
    result = worker._open(page, {"url": "javascript:go_view(178802)"})
    assert page.called == [["go_view", [178802]]]
    assert result["url"] == DETAIL and result["followed_js_link"] == "go_view"
    assert "pbancSn={1}" in result["instruction"] and "짐작하지 마라" in result["instruction"]
    note = worker._site_traits.note_for(LIST)
    assert "go_view→/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn={1}" in note


@pytest.mark.parametrize("link", ["javascript:fn_delete(3)", "javascript:goApply(178802)", "javascript:logoutView()"])
def test_acting_functions_are_left_to_a_click(tmp_path: Path, link: str) -> None:
    page = _Page(LIST, {"fn_delete", "goApply", "logoutView"}, DETAIL)
    worker = _worker(tmp_path, page)
    with pytest.raises(RuntimeError, match="js_link_not_followed"):
        worker._open(page, {"url": link})
    assert page.called == []


def test_a_missing_function_says_where_to_go(tmp_path: Path) -> None:
    page = _Page("https://www.k-startup.go.kr/web", set(), DETAIL)
    with pytest.raises(RuntimeError, match="js_link_function_missing"):
        _worker(tmp_path, page)._open(page, {"url": "javascript:go_view(178802)"})


def test_the_route_that_read_is_remembered_and_the_empty_one_warned(tmp_path: Path) -> None:
    worker = _worker(tmp_path, _Page(LIST, set(), LIST))
    good = _Page(DETAIL, set(), DETAIL)
    empty = _Page("https://www.k-startup.go.kr/web/contents/bizpbanc-view.do?id=178802", set(), "")
    worker._note_read_route(good, {"char_count": 5200})
    worker._note_read_route(empty, {"char_count": 40})
    note = worker._site_traits.note_for(LIST)
    assert "읽혔던 주소 모양: /web/contents/bizpbanc-ongoing.do?schM=view&pbancSn={n}" in note
    assert "비어 오거나 없는 페이지였던 주소 모양: /web/contents/bizpbanc-view.do?id={n}" in note


def test_search_result_lists_do_not_crowd_out_the_routes(tmp_path: Path) -> None:
    worker = _worker(tmp_path, _Page(LIST, set(), LIST))
    worker._note_read_route(_Page(LIST + "?page=1&schStr=AI", set(), ""), {"char_count": 6000})
    assert worker._site_traits.traits_for(LIST) == []


def test_a_route_seen_readable_is_not_called_empty(tmp_path: Path) -> None:
    traits = SiteTraits(tmp_path / "t.json")
    traits.record(DETAIL, "empty_url", "/hub/pricing")
    traits.record(DETAIL, "readable_url", "/hub/pricing")
    note = traits.note_for(DETAIL)
    assert "읽혔던" in note and "비어 오거나" not in note


def test_list_codes_and_pages_are_not_detail_routes(tmp_path: Path) -> None:
    """10-02 새벽: `PBC010` 의 「010」이 번호로 읽혀 목록 주소 넷이 「읽혔던 상세 모양」 칸을 차지했다."""
    assert _read_route_pattern(LIST + "?pbancClssCd=PBC010&schM=view&pbancSn=179294") == (
        "/web/contents/bizpbanc-ongoing.do?pbancClssCd=PBC010&schM=view&pbancSn={n}")
    worker = _worker(tmp_path, _Page(LIST, set(), LIST))
    worker._note_read_route(_Page(LIST + "?page=1&pbancClssCd=PBC010", set(), ""), {"char_count": 6000})
    worker._note_read_route(_Page(LIST + "?pbancClssCd=PBC010", set(), ""), {"char_count": 6000})
    assert worker._site_traits.traits_for(LIST) == []
