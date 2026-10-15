"""검색 목록 화면을 읽은 것은 「직접 열어 읽은 N개」가 아니다 (2026-10-08 실기 — 사람인 판).

「공고 3개의 고용형태와 마감일」에 계획이 「3개 이상 직접 열어 읽기 — 3개 읽음」으로 충족을 찍었는데, 연 상세는 하나뿐이었다
(그것도 다른 지역 공고). 검색 목록 화면을 읽은 것 둘이 「읽은 출처」로 세어져 3이 됐고, 「목표 달성」이 켜져 모델이 맞는
공고의 상세를 막 열기 시작한 걸음에서 판이 닫혔다.

목록인지 상세인지는 주소나 낱말로 알 수 없다. 도구가 말해 준다 — 검색 · 사이트 안 검색 · 검색 레시피 · 더 불러오기가
**도착한** 화면이 목록이다. 「결과를 열기 직전에 서 있던 화면」으로 잡았던 처음 두 규칙은 운영 판에 대 보니 틀렸다
(충족 739판 중 689판 · 그다음 61판을 뒤집었다 — 상세를 읽고 곧바로 다음 결과를 열면 서 있던 곳은 상세다).
마지막 규칙으로 뒤집히는 운영 판은 7판이고, 거기서 목록으로 잡힌 주소는 전부 검색 화면이었다.

읽기 근거를 따로 따지는 요구에만 건다. 목록이 답인 요구(답에 N개면 충족)는 그대로다.
"""
from __future__ import annotations

from typing import Any

from alture_jarvis import plan
from alture_jarvis.plan import Requirement, pages_results_were_opened_from

_LIST_A = "https://jobs.example/search?word=a"
_LIST_B = "https://jobs.example/search?word=b"


def _step(tool: str, url: str = "", ok: bool = True, **evidence: Any) -> dict[str, Any]:
    return {"tool": tool, "ok": ok, "evidence": {"url": url, **evidence}}


def _detail(n: int) -> str:
    return f"https://jobs.example/view?id={n}"


def test_where_a_search_tool_lands_is_a_listing() -> None:
    steps = [_step("browser_site_search", _LIST_A), _step("browser_read", _LIST_A),
             _step("browser_open_result", _detail(1)), _step("browser_extract", _detail(1))]
    assert pages_results_were_opened_from(steps) == {_LIST_A}


def test_a_search_recipe_that_reports_no_address_lands_where_the_next_look_is() -> None:
    steps = [_step("site_run", action="search_jobs_in_region"), _step("browser_read", _LIST_A),
             _step("site_run", action="search_jobs_in_region"), _step("browser_snapshot", _LIST_B)]
    assert pages_results_were_opened_from(steps) == {_LIST_A, _LIST_B}


def test_opening_a_result_right_after_the_recipe_does_not_make_the_detail_a_listing() -> None:
    steps = [_step("site_run", action="search_jobs_in_region"),
             _step("browser_open_result", _detail(1)), _step("browser_extract", _detail(1))]
    assert pages_results_were_opened_from(steps) == set()


def test_a_detail_from_which_the_next_result_is_opened_stays_a_detail() -> None:
    """처음 두 규칙이 틀린 자리 — 상세 1번을 읽고 곧바로 결과 2번을 연다."""
    steps = [_step("browser_site_search", _LIST_A),
             _step("browser_open_result", _detail(1)), _step("browser_extract", _detail(1)),
             _step("browser_open_result", _detail(2)), _step("browser_extract", _detail(2)),
             _step("browser_open", _detail(3)), _step("browser_extract", _detail(3)),
             _step("browser_open_result", _detail(4))]
    assert pages_results_were_opened_from(steps) == {_LIST_A}


def test_a_page_where_more_was_loaded_is_a_listing_and_a_non_search_recipe_is_not() -> None:
    steps = [_step("browser_open", _LIST_A), _step("browser_load_more", _LIST_A),
             _step("site_run", action="open_my_page"), _step("browser_read", _detail(9))]
    assert pages_results_were_opened_from(steps) == {_LIST_A}


_GROUNDED = Requirement("count", "3개 이상 직접 열어 읽기", 3, True)
_LISTED = Requirement("count", "3개 이상 목록으로 담기", 3, False, "", "", True)
_ANSWER = "| 회사 | 형태 |\n|---|---|\n| 가 | 정규직 |\n| 나 | 정규직 |\n| 다 | 계약직 |\n"

_TWO_LISTINGS_ONE_DETAIL = [
    _step("site_run", action="search_jobs_in_region"), _step("browser_read", _LIST_A),
    _step("browser_open_result", _detail(1)), _step("browser_extract", _detail(1)),
    _step("site_run", action="search_jobs_in_region"), _step("browser_read", _LIST_B),
]
_READ = [_LIST_A, _detail(1), _LIST_B]


def test_two_listings_and_one_detail_are_not_three_details() -> None:
    (_req, met, saw), = plan.check([_GROUNDED], sources=_READ, steps=_TWO_LISTINGS_ONE_DETAIL, answer=_ANSWER)
    assert met is False
    assert "1개 읽음" in saw and "목록 화면 2곳은 세지 않음" in saw


def test_three_details_are_three_details() -> None:
    steps = [_step("browser_site_search", _LIST_A)]
    for n in (1, 2, 3):
        steps += [_step("browser_open_result", _detail(n)), _step("browser_extract", _detail(n))]
    (_req, met, saw), = plan.check([_GROUNDED], sources=[_detail(1), _detail(2), _detail(3)], steps=steps, answer=_ANSWER)
    assert met is True and "세지 않음" not in saw


def test_a_listing_request_is_still_met_by_the_listing() -> None:
    """목록이 답인 요구는 건드리지 않는다 — 답에 N개면 충족이다."""
    (_req, met, _saw), = plan.check([_LISTED], sources=[_LIST_A], steps=_TWO_LISTINGS_ONE_DETAIL[:2], answer=_ANSWER)
    assert met is True
