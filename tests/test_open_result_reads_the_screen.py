"""목록이 눈앞에 있으면, **어떻게 도착했든** 몇 번째를 열 수 있어야 한다.

## 무엇이었나 (2026-08-13, 위시켓 15걸음 판)

자비스가 **사람처럼** 갔다:

    홈 열기 → '프로젝트 찾기' 클릭 → 검색칸에 입력 → Enter → 목록이 떴다

그리고 `browser_open_result(1)` 이 이렇게 답했다:

    no_search_results — 먼저 browser_search 로 검색해야 결과에 순위가 생긴다.

9·13·15 번 걸음에서 **세 번** 거절당했다. 화면에는 프로젝트 목록이 멀쩡히 떠 있었다.
그때마다 ref 로 손클릭해 하나 열었고, `browser_back` 이 30초 타임아웃 나면서
목록을 통째로 잃었다.

## 왜 이게 근본 문제인가

"몇 번째를 열어라"가 **화면의 성질**이 아니라 **어떻게 도착했는지**에 묶여 있었다.
`_last_results` 는 `browser_search`·`browser_site_search` 를 거칠 때만 채워진다.

사람은 그렇게 안 본다. 목록이 보이면 세 번째를 누른다. 어떻게 왔는지는 상관없다.
**도구가 사람처럼 다닌 것을 벌준 셈이다.**

이 시험은 그 계약을 지킨다: 순위는 화면에서 나온다.
"""

from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker


class _Worker:
    """`_open_result` 만 떼어 본다 — 크롬도 네트워크도 없다."""

    def __init__(self, found: list[dict[str, Any]]) -> None:
        self._last_results: list[dict[str, Any]] = []
        self._visited: set[str] = set()
        self._reads_since_search = 0
        self._searches_without_read = 0
        self._found = found
        self.collected = 0
        # 순위를 어디서 세웠는지. 이 시험은 **같은 화면**을 전제하므로 비워 둔다 —
        # 비어 있으면 "남의 순위인가" 판정은 아무 말도 안 한다(모르면 안 버린다).
        self._results_origin_host = ""
        # 이 판에는 요청한 날짜가 없다 → 주소는 하나도 안 바뀐다(예전 동작).
        self._requested_stay = None

    # 지금 화면에서 목록을 찾는 척
    def _collect_results(self, page: Any, *, limit: int = 12) -> list[dict[str, Any]]:
        self.collected += 1
        return list(self._found)

    def _recover_results_for_open(self, page: Any, *, limit: int = 15) -> list[dict[str, Any]]:
        del page, limit
        self.collected += 1
        return list(self._found)

    # 진짜 판정을 그대로 빌려 온다(사본을 만들면 어긋난다).
    _results_are_someone_elses = BrowserWorker._results_are_someone_elses
    _remember_results_origin = BrowserWorker._remember_results_origin
    # 2026-10-05: 순위를 세운 목록의 링크를 적어 두고, 주소로 떠난 뒤에는 추측해서 열지 않는다(여기서는 떠난 적이 없다).
    _ORIGIN_LINKS_MAX = BrowserWorker._ORIGIN_LINKS_MAX
    _links_on = BrowserWorker._links_on
    _standing_where_it_departed_to = BrowserWorker._standing_where_it_departed_to
    _remember_where_it_landed = BrowserWorker._remember_where_it_landed
    # 날짜 갈아 끼우기도 진짜를 빌려 온다. 흉내를 내면 "요청 날짜가 없을 때 안
    # 건드린다"는 성질을 이 시험이 못 지킨다.
    _goto_with_dates = BrowserWorker._goto_with_dates
    # staticmethod 로 다시 감싼다 — 그냥 대입하면 평범한 함수가 되어 self 가 끼어든다.
    _date_rewrite_evidence = staticmethod(BrowserWorker._date_rewrite_evidence)

    _validate_url = staticmethod(lambda url: url)
    _goto_checked = staticmethod(lambda page, url: None)
    _wait_until_operable = staticmethod(lambda page: {"count": 42, "polls": 1})
    _mark_visited = staticmethod(lambda url: None)
    _site_search_offer = staticmethod(lambda page: "")
    _evidence = staticmethod(lambda action, **kw: {"action": action, **kw})


def _rows() -> list[dict[str, Any]]:
    return [
        {"rank": index, "url": f"https://www.wishket.com/project/{15740 + index}/",
         "title": f"프로젝트 {index}"}
        for index in (1, 2, 3)
    ]


def test_a_list_on_screen_is_enough() -> None:
    """검색 도구를 한 번도 안 불러도 rank 1 이 열려야 한다."""
    worker = _Worker(_rows())
    result = BrowserWorker._open_result(worker, page=None, arguments={"rank": 1})

    assert result["action"] == "opened_result"
    assert result["rank"] == 1
    assert worker.collected == 1, "화면에서 목록을 찾아보지도 않았다"


def test_the_ranks_are_kept_for_the_next_call() -> None:
    """한 번 만들었으면 다시 훑지 않는다 — 순위가 매번 바뀌면 2번째가 딴 게 된다."""
    worker = _Worker(_rows())
    BrowserWorker._open_result(worker, page=None, arguments={"rank": 1})
    BrowserWorker._open_result(worker, page=None, arguments={"rank": 2})

    assert worker.collected == 1
    assert [item["rank"] for item in worker._last_results] == [1, 2, 3]


def test_no_list_on_screen_still_fails_loudly() -> None:
    """목록이 없으면 없는 것이다. 조용히 아무거나 열면 그게 더 나쁘다.

    다만 문구가 달라진다 — "먼저 검색해라"는 이제 틀린 안내다(검색 없이도 된다).
    """
    worker = _Worker([])
    with pytest.raises(RuntimeError, match="no_result_list"):
        BrowserWorker._open_result(worker, page=None, arguments={"rank": 1})


def test_a_rank_outside_the_list_is_not_rounded() -> None:
    """가장 가까운 것으로 바꿔 주면, 모델은 자기가 딴 것을 열었다는 걸 모른다."""
    worker = _Worker(_rows())
    with pytest.raises(ValueError, match="result_rank_not_found"):
        BrowserWorker._open_result(worker, page=None, arguments={"rank": 9})


def test_a_detail_pages_general_links_are_not_recovered_as_search_ranks() -> None:
    """회사 상세의 홈페이지·메뉴 링크는 결과 목록이 아니다.

    2026-08-17 사람인 기업정보 화면에서 이것을 허용해 rank 3이 케이엠넷
    홈페이지가 됐다. 넓은 링크 수집 결과가 있어도 반복 목록 구조가 없으면 거절한다.
    """

    class DetailWorker:
        _recover_results_for_open = BrowserWorker._recover_results_for_open

        @staticmethod
        def _result_list_rows(page: Any) -> list[dict[str, Any]]:
            del page
            return []

        @staticmethod
        def _collect_results(page: Any, *, limit: int = 15) -> list[dict[str, Any]]:
            del page, limit
            return [
                {"rank": 1, "url": "https://company.test/", "title": "회사 홈페이지"},
                {"rank": 2, "url": "https://company.test/about", "title": "회사 소개"},
                {"rank": 3, "url": "https://company.test/news", "title": "회사 소식"},
            ]

    assert DetailWorker()._recover_results_for_open(object(), limit=15) == []
