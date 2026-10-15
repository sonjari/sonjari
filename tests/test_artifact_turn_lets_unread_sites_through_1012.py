"""「파일 만들 차례」에서도 아직 안 읽은 사이트로 가는 손은 받는다 (2026-10-12).

가격 조사 · 공식 9B · 창 32K 세 판이 가게 하나나 둘만 읽고 끝났다. 모델이 첫 가게를 읽고 「이제 11번가를 보겠습니다」
처럼 말만 한 번 하자 차례가 걸렸고, 방금 연 11번가의 검색이 `not_this_stage` 로 되돌아갔다. 같은 날 앞선 세 판은
다나와와 11번가를 되풀이해 읽다 걸음을 다 썼다. 문이 새 땅과 헌 땅을 가르지 않았다.

걸음의 모양은 그 판들의 기록 그대로다(도구 · 성공 여부 · 인자 · `evidence.url`). 주소의 번호는 지어낸 것이다.
"""
from __future__ import annotations

import inspect
from typing import Any

from alture_jarvis import agent
from alture_jarvis.plan_nudges import _goes_to_unread_site, _site_of

DANAWA_LIST = "https://search.danawa.com/dsearch.php?k1=%EA%B0%80&module=goods&act=dispMain"
DANAWA_ITEM = "https://prod.danawa.com/info/?pcode=90000001"
ST11_HOME = "https://www.11st.co.kr/"
ST11_LIST = "https://search.11st.co.kr/pc/total-search?kwd=%EA%B0%80"
ST11_ITEM = "https://www.11st.co.kr/products/9000000001"
GMARKET_HOME = "https://www.gmarket.co.kr/"
NAVER_SEARCH = "https://search.naver.com/search.naver?query=%EA%B0%80"


def _step(tool: str, landed: str = "", /, *, ok: bool = True, **arguments: Any) -> dict[str, Any]:
    """`landed` 는 그 걸음 뒤의 화면 주소(`evidence.url`) — 인자의 `url`(모델이 준 것)과 다를 수 있다."""
    return {"tool": tool, "ok": ok, "arguments": arguments, "evidence": {"url": landed} if landed and ok else {}}


def _read_danawa() -> list[dict[str, Any]]:
    return [
        _step("browser_search", NAVER_SEARCH, query="가상 상품"),
        _step("browser_open", "https://www.danawa.com/", url="https://www.danawa.com"),
        _step("browser_site_search", DANAWA_LIST, query="가상 상품"),
        _step("browser_open_result", DANAWA_ITEM, rank=1),
        _step("browser_extract", DANAWA_ITEM),
    ]


def test_sites_are_told_apart_by_the_shop_not_the_subdomain() -> None:
    assert _site_of(DANAWA_LIST) == _site_of(DANAWA_ITEM) == "danawa.com"
    assert _site_of(ST11_LIST) == _site_of(ST11_ITEM) == "11st.co.kr"
    # 검색엔진의 결과 화면은 사이트가 아니다.
    assert _site_of(NAVER_SEARCH) == "" and _site_of("https://www.google.com/search?q=x") == "" and _site_of("") == ""


def test_the_next_shop_is_let_in_and_walked_until_its_first_read() -> None:
    """89931d82 의 모양: 다나와를 읽고 → 11번가를 열고 → 그 검색이 거절됐다."""
    steps = _read_danawa()
    assert _goes_to_unread_site("browser_open", {"url": "https://www.11st.co.kr"}, steps)
    steps.append(_step("browser_open", ST11_HOME, url="https://www.11st.co.kr"))
    assert _goes_to_unread_site("browser_site_search", {"query": "가상 상품"}, steps)
    steps.append(_step("browser_site_search", ST11_LIST, query="가상 상품"))
    assert _goes_to_unread_site("browser_open_result", {"rank": 1}, steps)
    steps.append(_step("browser_open_result", ST11_ITEM, rank=1))
    assert _goes_to_unread_site("browser_extract", {}, steps)
    steps.append(_step("browser_extract", ST11_ITEM))
    # 읽었으면 그 사이트는 닫힌다 — 더 뒤지는 손은 예전처럼 막힌다.
    for hand in ("browser_extract", "browser_read", "browser_page_data", "browser_site_search", "browser_open_result", "browser_snapshot"):
        assert not _goes_to_unread_site(hand, {}, steps), hand
    # 셋째 가게는 또 받는다.
    assert _goes_to_unread_site("browser_open", {"url": GMARKET_HOME}, steps)


def test_going_back_to_a_shop_already_read_stays_refused() -> None:
    """3fe1a676 의 모양: 다나와 → 11번가 → 다나와 → 11번가 … 를 되풀이했다."""
    steps = _read_danawa() + [
        _step("browser_open", ST11_HOME, url="https://www.11st.co.kr"),
        _step("browser_site_search", ST11_LIST, query="가상 상품"),
        _step("browser_open_result", ST11_ITEM, rank=1),
        _step("browser_extract", ST11_ITEM),
    ]
    assert not _goes_to_unread_site("browser_open", {"url": "https://www.danawa.com"}, steps)
    assert not _goes_to_unread_site("browser_open", {"url": DANAWA_ITEM}, steps)
    assert not _goes_to_unread_site("browser_open", {"url": ST11_LIST}, steps)
    # 되돌아가 거기서 찾는 손도 마찬가지다.
    steps.append(_step("browser_open", "https://www.danawa.com/", url="https://www.danawa.com"))
    assert not _goes_to_unread_site("browser_site_search", {"query": "가상 상품"}, steps)


def test_web_search_and_search_engine_results_are_not_new_ground() -> None:
    steps = _read_danawa()
    assert not _goes_to_unread_site("browser_search", {"query": "가상 상품 최저가"}, steps)
    steps.append(_step("browser_search", NAVER_SEARCH, query="가상 상품 최저가"))
    assert not _goes_to_unread_site("browser_open_result", {"rank": 1}, steps), "검색엔진 결과에서 여는 것은 「더 찾기」다"
    assert not _goes_to_unread_site("browser_open", {"url": NAVER_SEARCH}, steps)


def test_a_failed_step_does_not_move_where_we_are_or_count_as_a_read() -> None:
    steps = _read_danawa() + [
        _step("browser_open", ST11_HOME, url="https://www.11st.co.kr"),
        _step("browser_extract", ST11_HOME, ok=False),
        _step("browser_open", GMARKET_HOME, ok=False, url=GMARKET_HOME),
    ]
    # 11번가는 아직 못 읽었고(읽기가 실패했다), 실패한 열기는 자리를 옮기지 않는다 — 지금 자리는 11번가다.
    assert _goes_to_unread_site("browser_extract", {}, steps)
    assert _goes_to_unread_site("browser_site_search", {"query": "가상 상품"}, steps)


def test_other_hands_and_empty_addresses_are_not_let_through() -> None:
    steps = _read_danawa()
    for hand in ("browser_click", "browser_type", "local_run_project_command", "site_run"):
        assert not _goes_to_unread_site(hand, {"url": GMARKET_HOME}, steps), hand
    assert not _goes_to_unread_site("browser_open", {}, steps)
    assert not _goes_to_unread_site("browser_open", None, steps)
    assert not _goes_to_unread_site("browser_site_search", {}, [])


def test_the_refusal_asks_this_and_not_on_the_last_turn() -> None:
    source = inspect.getsource(agent)
    refusal = source[source.index("elif stage_hands is not None and name not in stage_hands and not ("):]
    refusal = refusal[:refusal.index("and not _deletes_own_file(name, arguments, steps):")]
    assert "or (not deliver_turn_used and _goes_to_unread_site(name, arguments, steps))" in refusal
