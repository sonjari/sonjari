"""지어낸 검색 주소는 **인자 이름이 달라도 · 검색어가 경로에 실려 있어도** 알아보고 검색칸에 대신 친다 (2026-10-13).

가격 조사 판(9B · 창 32K)을 걸음 순서로 읽었다. 검색 엔진으로 가려다 「지금은 그 차례가 아니다」에 막히자 모델은 가게의
검색 주소를 **지어서** 열었다:

     9  browser_open         가게/search/keyword/<검색어>           ok   ← 지어낸 주소(결과 목록이 아닌 화면)
    10  browser_open_result  rank 1                                  ✗ stale_result_list
    11  browser_snapshot                                             ok
    12  browser_open         다른 가게/search/keyword/<검색어>       ✗ page_not_found
    14  local_write_document                                              ← 두 가게를 빈 칸으로 두고 표를 씀

「주소를 조립해 오면 도구가 검색칸에 쳐 넣는다」(08-13)가 이미 있는데 안 돌았다 — 그물이 인자 이름 아홉 개만 알았기 때문이다.
운영 기록의 주소 열기 3,592번에 옛 그물과 새 그물을 나란히 댔다: 옛 그물이 잡던 252번은 그대로, 새로 36번
(`SearchKey` · `searchKeyword` · `searchText` · `kwd` · `searchterm` · `srchWord` · 경로에 실린 검색어).

입구 판정(경로에 search 가 있거나 호스트가 search.*)은 그대로다 — 상세 페이지가 달고 다니는 `keyword=` 는 여전히 안 걸린다.
"""
from __future__ import annotations

from alture_jarvis.browser import BrowserWorker


class _Worker:
    _handmade_search_query = BrowserWorker._handmade_search_query
    _HANDMADE_SEARCH = BrowserWorker._HANDMADE_SEARCH
    _SEARCH_ENTRY_PATH = BrowserWorker._SEARCH_ENTRY_PATH
    _SEARCH_ENGINE_HOSTS = BrowserWorker._SEARCH_ENGINE_HOSTS
    _QUERY_KEYS = BrowserWorker._QUERY_KEYS


def _query(url: str) -> str:
    return _Worker()._handmade_search_query(url)


def test_a_parameter_whose_name_means_search_word_is_the_query() -> None:
    assert _query("https://www.shop.example/Search/SearchResult.aspx?SearchKey=무선 마우스") == "무선 마우스"
    assert _query("https://shop.example/Search/SearchResult.do?searchKeyword=무선+마우스") == "무선 마우스"
    assert _query("https://shop.example/search?searchText=무선%20마우스") == "무선 마우스"
    assert _query("https://search.shop.example/pc/total-search?kwd=무선%20마우스&tabId=TOTAL_SEARCH") == "무선 마우스"
    assert _query("https://www.store.example/site/search?searchTerm=wireless+mouse") == "wireless mouse"
    assert _query("https://www.books.example/Product/Search?searchTopId=7&srchWord=회계") == "회계"


def test_a_query_carried_in_the_path_is_the_query() -> None:
    assert _query("https://www.shop.example/search/keyword/무선+마우스+M650") == "무선 마우스 M650"
    assert _query("https://www.shop.example/search/keyword/%EB%AC%B4%EC%84%A0%20%EB%A7%88%EC%9A%B0%EC%8A%A4") == "무선 마우스"
    assert _query("https://market.example/search/책상") == "책상"


def test_a_route_under_search_is_not_a_query() -> None:
    """`/search/recruit` 같은 길 이름을 검색어로 치면 안 된다 — 한 낱말짜리 영문 조각은 길인지 검색어인지 가를 수 없다."""
    assert _query("https://www.jobs.example/zf_user/search/recruit") == ""
    assert _query("https://github.example/owner/repo/search") == ""
    assert _query("https://www.pets.example/pets/search/cats-for-adoption") == ""
    assert _query("https://archive.example/cdx/search/cdx?url=shop.example&limit=5") == ""


def test_parameters_that_only_mention_search_are_not_the_query() -> None:
    """`searchType` · `searchId` · `search_uuid` 는 검색어가 아니다 — 그 값을 검색칸에 치면 엉뚱한 것을 찾는다."""
    assert _query("https://www.shop.example/search?searchType=all&searchId=9f3a") == ""
    assert _query("https://www.jobs.example/zf_user/search/recruit?search_done=y&searchType=search&searchword=회계") == "회계"


def test_a_value_that_is_not_words_is_not_typed_into_a_search_box() -> None:
    """필터 묶음을 통째로 실은 인자(`searchQuery={"…"}`)는 검색어가 아니다."""
    assert _query('https://www.homes.example/for-rent/search/town/?searchQuery={"beds":2,"sort":"new"}') == ""
    assert _query("https://www.homes.example/search?searchQuery=%7B%22beds%22%3A2%7D") == ""


def test_a_detail_page_carrying_the_keyword_is_still_left_alone() -> None:
    assert _query("https://prod.shop.example/info/?pcode=91770953&keyword=무선마우스") == ""
    assert _query("https://www.shop.example/shop/item.do?SearchKey=무선마우스") == ""
    assert _query("https://www.shop.example/products/88412345") == ""


def test_the_known_names_keep_their_priority() -> None:
    """이름이 아홉 개 안에 있으면 그것이 먼저다 — 옛 판이 잡던 것은 값까지 그대로."""
    assert _query("https://search.shop.example/search?searchText=옛것&q=무선마우스") == "무선마우스"


def test_search_engines_are_still_left_alone() -> None:
    assert _query("https://www.google.com/search/keyword/무선+마우스") == ""
    assert _query("https://search.naver.com/search.naver?searchKeyword=무선") == ""
