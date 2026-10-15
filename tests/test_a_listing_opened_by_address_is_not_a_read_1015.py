"""검색 주소를 `browser_open` 으로 직접 연 **목록 화면**은 「직접 열어 읽은 글」이 아니다 (2026-10-15).

10-15 운영 판 ba5d9277(레딧 r/ollama 다섯 주제 · 주제마다 글 2개 = 10): 손자리가 검색 주소
(`/r/ollama/search/?q=…`)를 `browser_open` 으로 직접 열고 `browser_extract` 로 읽었다. 검색 도구가 아니라서 목록으로
안 잡혀, 목록 화면 4곳 + 글 8개 = 「12개 읽음」으로 10을 넘겼고 다섯째 주제는 열지도 않은 채 판이 닫혔다.

지키는 약속(`plan.pages_results_were_opened_from`):
- 읽는 도구가 **글 목록을 돌려준** 화면(증거의 `listing` 칸 — 도구가 「이건 목록」이라고 말한 것)은 목록이다.
- 주소 모양으로 가르지 않는다(사이트마다 다르다) — `listing` 이 없으면 지금 그대로 읽은 글이다.
"""

from __future__ import annotations

from alture_jarvis.plan import pages_results_were_opened_from

SEARCH = "https://www.reddit.com/r/ollama/search/?q=num_ctx&sort=comments&t=year"
POST = "https://www.reddit.com/r/ollama/comments/1obh5ex/building_powerful_ai/"


def _step(tool: str, url: str, **extra) -> dict:
    return {"tool": tool, "ok": True, "evidence": {"url": url, **extra}}


def test_a_search_page_opened_by_address_whose_reading_returned_a_listing_is_a_listing() -> None:
    steps = [
        _step("browser_open", SEARCH, action="opened"),
        _step("browser_extract", SEARCH, listing=[{"title": "a", "num_comments": 3, "url": POST}]),
        _step("browser_open", POST, action="opened"),
        _step("browser_extract", POST, post_comments=[{"author": "x"}]),
    ]
    assert pages_results_were_opened_from(steps) == {SEARCH}


def test_a_page_read_without_a_listing_stays_a_read() -> None:
    steps = [
        _step("browser_open", SEARCH, action="opened"),
        _step("browser_extract", SEARCH, listing=[]),
        _step("browser_open", POST, action="opened"),
        _step("browser_extract", POST),
    ]
    assert pages_results_were_opened_from(steps) == set()


def test_a_failed_reading_does_not_mark_a_listing() -> None:
    steps = [{"tool": "browser_extract", "ok": False, "evidence": {"url": SEARCH, "listing": [{"title": "a"}]}}]
    assert pages_results_were_opened_from(steps) == set()
