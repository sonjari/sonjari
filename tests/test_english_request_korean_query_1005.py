"""영어로 시킨 판에서 모델이 검색어를 한국어로 옮겨 넣으면 한 번 돌려보낸다 (2026-10-05 9B · 영어 화면).

「Find 3 recent blog posts about running local LLMs on a 12GB GPU …」에 모델이 `engine=naver · tab=blog ·
query=12GB GPU 로컬 LLM 실행 방법` 으로 갔고, 영어 사용자에게 네이버 블로그 셋을 요약해 줬다. 영어 도구 설명을 고쳐 다시 재도
3판 중 3판 그대로였다 — 안내문은 안 먹는다. 그 자리에서 이유를 말하고 한 번 돌려보낸다.
"""
from __future__ import annotations

import inspect

from alture_jarvis.agent import SEARCH_QUERY_TRANSLATED, BrowserAgent, _search_query_was_translated

ENGLISH = "Find 3 recent blog posts about running local LLMs on a 12GB GPU and summarize each in one line with its URL"
KOREAN_QUERY = {"engine": "naver", "limit": 15, "query": "12GB GPU 로컬 LLM 실행 방법 블로그", "tab": "blog"}


def test_an_english_request_with_a_korean_query_is_turned_back_once():
    assert _search_query_was_translated("browser_search", KOREAN_QUERY, ENGLISH, []) is True


def test_the_second_time_it_goes_through():
    """영어로 물으면서 한국어 자료를 원하는 사람도 있다 — 모델이 다시 같은 검색을 부르면 그대로 보낸다."""
    steps = [{"tool": "browser_search", "ok": False, "error": SEARCH_QUERY_TRANSLATED}]
    assert _search_query_was_translated("browser_search", KOREAN_QUERY, ENGLISH, steps) is False


def test_it_does_not_touch_what_is_not_a_translation():
    english_query = {"query": "running local LLMs on a 12GB GPU blog"}
    assert _search_query_was_translated("browser_search", english_query, ENGLISH, []) is False
    # 한국어로 시킨 판 — 한국어 검색어는 당연하다.
    assert _search_query_was_translated("browser_search", KOREAN_QUERY, "12GB 그래픽카드로 로컬 LLM 돌리는 블로그 글 찾아줘", []) is False
    # 요청에 한글이 한 글자라도 있으면(「교보문고 reviews」) 모델이 옮긴 것이 아니다.
    assert _search_query_was_translated("browser_search", {"query": "교보문고 파이썬 책 후기"}, "Find reviews of 교보문고 python books", []) is False
    # 사이트 안 검색·다른 도구는 이 규칙이 아니다.
    assert _search_query_was_translated("browser_site_search", KOREAN_QUERY, ENGLISH, []) is False
    assert _search_query_was_translated("browser_open", {"url": "https://example.com"}, ENGLISH, []) is False


def test_the_refusal_says_it_is_not_a_permission_problem_and_what_to_do():
    source = inspect.getsource(BrowserAgent)
    at = source.index("_search_query_was_translated(name, arguments, prompt, steps)")
    block = source[at: at + 900]
    assert "SEARCH_QUERY_TRANSLATED" in block
    assert "Not a permission problem" in block and "English query" in block and "call it again exactly as it is" in block
