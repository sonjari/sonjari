"""사이트 검색 결과는 **그려진 뒤에** 센다 (2026-10-13 가격 조사 판의 틀린 칸을 까닭별로 가르다 찾음).

재는 판의 11번가 사이트 검색 190번 가운데 15번이 `result_count 0` 으로 돌아왔다. 그 가운데 12번은 이랬다:

    결과 0개일 때   요소 13~28개 · 제목 「11번가 | 검색결과」(검색어가 아직 안 들어간 껍데기)
    결과 있을 때    요소 중간값 404개 · 제목에 검색어

같은 검색어를 바로 다시 치면 10개가 나왔다. 그 화면은 링크 7개짜리 껍데기가 문서와 함께 먼저 오고 결과는 스크립트가
그 뒤에 그린다(한가할 때 0.7~1.1초 — 재 봄). 도구는 Enter 뒤 1.2초를 기다렸다가 **한 번** 셌다. 모델이 도는 동안은
그보다 늦게 그려져 껍데기를 셌고, 「이 사이트가 직접 준 목록이다(0건)」이 됐다 — 모델은 그 가게를 건너뛰거나 표를 썼다.

검색엔진 쪽(`_wait_for_results`)은 08-06 에 같은 고장을 고쳤다. 사이트 검색과 「배운 주소로 바로 가기」는 그대로였다 —
뒤쪽은 덜 그려진 화면을 「낡은 주소」로 읽어 **멀쩡히 배운 주소를 버리기까지** 했다.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from alture_jarvis.browser import BrowserWorker


class _Page:
    url = "https://search.shop.example/pc/total-search?kwd=무선+마우스"

    def __init__(self) -> None:
        self.waited: list[int] = []

    def wait_for_timeout(self, ms: int) -> None:
        self.waited.append(ms)


def _rows(count: int) -> list[dict[str, str]]:
    return [{"rank": str(n + 1), "url": f"https://shop.example/products/{9000 + n}", "title": f"무선 마우스 {n + 1}"} for n in range(count)]


def _worker(counts: list[int], *, says_none: bool = False, timeout_ms: int = 6000) -> tuple[BrowserWorker, list[int]]:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker.config = SimpleNamespace(browser_ready_timeout_ms=timeout_ms)
    asked: list[int] = []

    def collect(page: object, *, limit: int = 12) -> list[dict[str, str]]:
        asked.append(limit)
        return _rows(counts[min(len(asked) - 1, len(counts) - 1)])[:limit]

    worker._collect_results = collect  # type: ignore[method-assign]
    worker._page_says_no_results = lambda page: says_none  # type: ignore[method-assign]
    return worker, asked


def test_a_shell_that_has_not_drawn_yet_is_not_counted_as_zero() -> None:
    worker, asked = _worker([0, 0, 0, 10, 10])
    page = _Page()

    results = worker._results_once_drawn(page, limit=15)

    assert len(results) == 10, "껍데기를 0건으로 돌려주면 모델은 그 가게를 건너뛴다"
    assert page.waited and all(ms <= 500 for ms in page.waited), "짧게 여러 번 본다"


def test_a_list_that_is_already_there_costs_nothing_extra() -> None:
    """흔한 길(재는 판 190번 중 170번대)은 지금처럼 한 번에 끝나야 한다."""
    worker, asked = _worker([10])
    page = _Page()

    assert len(worker._results_once_drawn(page, limit=15)) == 10
    assert len(asked) == 1 and page.waited == []


def test_a_half_drawn_list_is_watched_until_it_stops_growing() -> None:
    worker, asked = _worker([1, 4, 9, 9])

    assert len(worker._results_once_drawn(_Page(), limit=15)) == 9


def test_a_page_that_says_nothing_was_found_is_not_waited_on() -> None:
    worker, asked = _worker([0], says_none=True)
    page = _Page()

    assert worker._results_once_drawn(page, limit=15) == []
    assert len(asked) == 1 and page.waited == [], "「결과 없음」이라고 적힌 화면을 6초씩 기다리지 않는다"


def test_a_really_empty_page_gives_up_at_the_ready_timeout() -> None:
    worker, asked = _worker([0], timeout_ms=1500)
    page = _Page()

    assert worker._results_once_drawn(page, limit=15) == []
    assert 2 <= len(asked) <= 7, f"한도(1.5초) 안에서만 다시 본다 — {len(asked)}번 셌다"


def test_two_real_results_are_kept_after_one_more_look() -> None:
    """정말 두 건뿐인 검색에서 한도를 다 쓰지 않는다."""
    worker, asked = _worker([2, 2])

    assert len(worker._results_once_drawn(_Page(), limit=15)) == 2
    assert len(asked) == 2


def test_both_doors_count_only_after_the_list_is_drawn() -> None:
    """검색칸에 치는 길과 배운 주소로 바로 가는 길 — 한쪽만 고치면 다른 쪽이 계속 껍데기를 센다."""
    for door in (BrowserWorker._site_search_here, BrowserWorker._learned_search):
        source = inspect.getsource(door)
        assert "_results_once_drawn(" in source, door.__name__
        assert "self._collect_results(page" not in source, f"{door.__name__} 이 아직 한 번만 센다"
