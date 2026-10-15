"""주소를 직접 쳐서 다른 곳으로 간 뒤에는, 앞 목록의 순위를 추측해서 열지 않는다 (2026-10-05 AWS 영어 윈도우, c3c1b051).

    2  browser_site_search  github.com/search?q=trending+Python…      ← 순위를 세움
    4  browser_open         github.com/trending/python                 ← 모델이 주소로 직접 감
    8  browser_open_result  rank 1 → github.com/bonfy/github-trending  ← **검색 목록의** 1번
    11 browser_open_result  rank 2 → github.com/topics/python
    16 browser_open_result  rank 3 → github.com/topics/github-trending

「3개 읽음」이 채워졌고 답은 「각 저장소 페이지를 열어 확인했다」고 했다. 연 것은 딴 페이지 셋이었다.

「지금 화면이 목록이면 그것을 쓴다」로는 못 고친다(실측: 판정기가 GitHub 인기 목록을 0줄, 저장소 상세를 18줄로 본다).
그래서 화면이 아니라 **모델이 어떻게 거기 갔는지**로 가른다.
"""
from __future__ import annotations

import pytest

from alture_jarvis.browser import BrowserWorker

SEARCH = "https://github.com/search?q=trending+Python&type=repositories"
TRENDING = "https://github.com/trending/python"
RANKS = [
    {"rank": 1, "url": "https://github.com/bonfy/github-trending", "title": "bonfy/github-trending"},
    {"rank": 2, "url": "https://github.com/topics/python", "title": "python"},
    {"rank": 3, "url": "https://github.com/topics/github-trending", "title": "github-trending"},
]
ON_THE_SEARCH_PAGE = [item["url"] for item in RANKS] + ["https://github.com/pricing", "https://github.com/vinta/awesome-python"]


class _Page:
    def __init__(self, url: str, links: list[str] | None = None) -> None:
        self.url, self._links = url, links

    def evaluate(self, script: str, arg: object = None) -> list[str]:
        if self._links is None:
            raise RuntimeError("Execution context was destroyed")
        return list(self._links)


def _ranked(links: list[str] | None = ON_THE_SEARCH_PAGE) -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._page = None
    worker._last_results = [dict(item) for item in RANKS]
    worker._result_list_rows = lambda page: []  # type: ignore[method-assign]
    worker._remember_results_origin(_Page(SEARCH, links))
    return worker


def _went_by_address(worker: BrowserWorker, url: str) -> _Page:
    page = _Page(url, [])
    assert worker._noting_departure(page, {"action": "opened"}) == {"action": "opened"}
    return page


def test_a_rank_asked_on_a_page_reached_by_address_is_not_guessed() -> None:
    worker = _ranked()
    page = _went_by_address(worker, TRENDING)

    with pytest.raises(RuntimeError) as refused:
        worker._open_result(page, {"rank": 1})

    said = str(refused.value)
    assert said.startswith("stale_result_list")
    assert "github.com/search" in said and "github.com/trending/python" in said
    assert "browser_click" in said, "지금 화면의 항목을 여는 길을 알려 준다"


def test_a_page_picked_from_the_list_keeps_the_ranks() -> None:
    """목록에 걸려 있던 주소를 주소로 연 것은 목록에서 고른 것이다 — 상세를 읽고 다음 순위로 가는 정상 흐름."""
    worker = _ranked()
    for picked in ("https://github.com/vinta/awesome-python", RANKS[1]["url"]):
        page = _went_by_address(worker, picked)
        assert worker._standing_where_it_departed_to(page) == ""


def test_the_same_path_is_left_alone() -> None:
    """다음 쪽 · 목록과 상세가 같은 경로인 사이트(K-Startup `bizpbanc-ongoing.do?schM=view&pbancSn=…`)."""
    worker = _ranked()
    page = _went_by_address(worker, "https://github.com/search?q=trending+Python&type=repositories&p=2")
    assert worker._standing_where_it_departed_to(page) == ""


def test_coming_back_to_the_list_makes_the_ranks_good_again() -> None:
    worker = _ranked()
    _went_by_address(worker, TRENDING)

    assert worker._standing_where_it_departed_to(_Page(SEARCH)) == ""
    assert worker._results_departed_to == ""


def test_without_knowing_what_was_on_the_list_nothing_is_judged() -> None:
    worker = _ranked(links=None)   # 목록 화면의 링크를 못 읽었다
    page = _went_by_address(worker, TRENDING)
    assert worker._standing_where_it_departed_to(page) == ""


def test_a_new_ranking_and_a_new_job_both_clear_it() -> None:
    worker = _ranked()
    _went_by_address(worker, TRENDING)
    assert worker._results_departed_to

    worker._remember_results_origin(_Page(TRENDING, ["https://github.com/earthtojake/text-to-cad"]))
    assert worker._results_departed_to == ""

    _went_by_address(worker, "https://github.com/explore")
    assert worker._results_departed_to
    worker.forget_results()
    assert worker._results_departed_to == "" and worker._results_origin_links == frozenset()
