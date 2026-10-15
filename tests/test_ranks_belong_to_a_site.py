"""순위는 **그것을 세운 사이트의 것**이다.

## 2026-08-16 실측

사람인 검색 결과가 눈앞에 떠 있는데 `browser_open_result(rank=1)` 이 **쿠팡 상품
페이지**를 열었다. 앞 판(1시간 50분 전 쿠팡 잡)의 순위가 그대로 남아 있었다.

`forget_results()` 는 판이 바뀔 때 부르는 것인데 그 호출이 `agent.run` 한 곳뿐이라,
`/v1/tools/execute` 나 MCP 처럼 **잡 없이** 부르는 길로 들어오면 안 불린다.
`test_ranks_do_not_leak_between_jobs.py` 가 이미 있었는데도 그 길은 못 막았다 —
그 시험은 **잡이 있는** 경로만 본다.

## 왜 "지금 화면과 다르면 버린다"가 아닌가

결과 → 상세로 들어간 뒤 `rank 2` 를 여는 것이 이 도구의 존재 이유다. 화면이
바뀌었다고 버리면 그게 통째로 죽는다. 검색엔진 SERP 는 결과마다 호스트가 다르니
호스트만 봐도 안 된다.

그래서 **둘을 같이** 본다: 딴 사이트이면서, **그 화면이 자기 목록을 갖고 있을 때**만
남의 것으로 친다. 사람이 하는 판단과 같다 — 눈앞에 목록이 있으면 그것의 세 번째를 누른다.
"""

from __future__ import annotations

from alture_jarvis.browser import BrowserWorker


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url


def _worker(origin: str, results: list[dict], *, here_has_list: bool) -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._last_results = results
    worker._results_origin_host = origin
    worker._collect_results = lambda page, limit=12: (  # type: ignore[assignment]
        [{"rank": 1, "href": "https://x.test/1"}] if here_has_list else []
    )
    # 「자기 목록」 판정은 반복 카드 기준(`_result_list_rows` 3개 이상)이다.
    worker._result_list_rows = lambda page: (  # type: ignore[assignment]
        [{"name": f"item {i}", "href": f"https://x.test/{i}"} for i in range(5)] if here_has_list else []
    )
    return worker


_RANKS = [{"rank": 1, "href": "https://www.coupang.com/vp/products/1"}]


def test_someone_elses_list_in_front_of_a_real_one_is_refused() -> None:
    """★ 그날의 사고. 사람인 목록 앞에서 쿠팡 순위를 쓰면 안 된다."""
    worker = _worker("www.coupang.com", _RANKS, here_has_list=True)
    assert worker._results_are_someone_elses(_Page("https://www.saramin.co.kr/zf_user/search/recruit?x=1"))


def test_going_deeper_on_the_same_site_keeps_the_ranks() -> None:
    """결과 → 상세 → rank 2. 이게 이 도구의 존재 이유다."""
    worker = _worker("www.saramin.co.kr", _RANKS, here_has_list=False)
    assert not worker._results_are_someone_elses(
        _Page("https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1")
    )


def test_a_detail_page_elsewhere_is_not_a_leak() -> None:
    """검색엔진에서 온 결과는 상세마다 호스트가 다르다 — 그것만으로 버리면 안 된다.

    그 화면이 **자기 목록을 갖고 있지 않으면** 남의 것이라고 부르지 않는다.
    """
    worker = _worker("search.naver.com", _RANKS, here_has_list=False)
    assert not worker._results_are_someone_elses(_Page("https://prod.danawa.com/info/?pcode=1"))


def test_the_opened_rank_keeps_the_rest_even_if_detail_has_related_links() -> None:
    """상세의 추천 목록은 새 검색 결과가 아니다 — rank 2 를 계속 열 수 있어야 한다."""
    ranks = [
        {"rank": 1, "url": "https://prod.danawa.com/info/?pcode=1"},
        {"rank": 2, "url": "https://other.test/item/2"},
    ]
    worker = _worker("search.naver.com", ranks, here_has_list=True)

    assert not worker._results_are_someone_elses(
        _Page("https://prod.danawa.com/info/?pcode=1")
    )


def test_nothing_to_judge_when_there_are_no_ranks() -> None:
    worker = _worker("www.coupang.com", [], here_has_list=True)
    assert not worker._results_are_someone_elses(_Page("https://www.saramin.co.kr/"))


def test_an_unknown_origin_is_left_alone() -> None:
    """어디서 세운 목록인지 모르면 판정하지 않는다 — 모르면 안 버린다."""
    worker = _worker("", _RANKS, here_has_list=True)
    assert not worker._results_are_someone_elses(_Page("https://www.saramin.co.kr/"))


def test_the_origin_is_recorded_from_the_page() -> None:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._remember_results_origin(_Page("https://www.saramin.co.kr/zf_user/search/recruit"))
    assert worker._results_origin_host == "www.saramin.co.kr"


def test_a_blog_post_with_a_few_links_does_not_wipe_search_ranks() -> None:
    """★ 2026-10-01 운영 판: 검색 결과 → 블로그 글로 바로 옮긴 뒤 rank 1·4 가 `no_result_list` 로 둘 다 실패했다.
    글의 메뉴·관련 글 링크 몇 개(넓은 수집에는 잡힘)는 반복 카드 목록이 아니다 — 기억한 순위를 지우면 안 된다."""
    worker = _worker("www.google.com", _RANKS, here_has_list=False)
    worker._collect_results = lambda page, limit=12: [{"rank": 1, "href": "https://dcordero.me/about"}]  # type: ignore[assignment]
    assert not worker._results_are_someone_elses(_Page("https://dcordero.me/posts/from-manual-pain-to-automation-chaos.html"))
