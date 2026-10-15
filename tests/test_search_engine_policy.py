"""기본 엔진은 구글, 국내 이야기는 네이버 — 그리고 화면은 한 장이 아니다.

2026-08-12 실측으로 전제가 뒤집혔다. 예전 지식은 "빙·구글은 상시 차단"이라 국내는
네이버, 해외는 빙이었다. 그런데 그 차단은 **Playwright 가 띄운 크롬**(자동화 모드)
에서 잰 것이었다. 진짜 크롬에 붙기 시작하자 같은 질의로:

    구글    ok · 결과 8건 · 폴백 없음   (langchain.com 등 영어권 원문)
    빙      여전히 막힘 → 네이버 폴백
    네이버  ok

쿠팡과 정확히 같은 이야기다 — 사이트가 아니라 우리가 문제였다.

같이 못 박는 것: 스크롤·더보기가 **순서에 없어서** 8판 내내 한 번도 안 불렸다.
도구가 있는데 안 쓰는 병을 오늘만 세 번 만났다(드라이브 읽기·사이트 검색·스크롤).
"""

from __future__ import annotations

from alture_jarvis.agent import AGENT_SYSTEM_PROMPT
from alture_jarvis.browser import BrowserWorker

_pick = BrowserWorker._search_engines


def test_english_and_technical_go_to_google() -> None:
    assert _pick("AI agent framework 2026", "auto")[0] == "google"
    assert _pick("playwright cdp attach", "auto")[0] == "google"


def test_korean_everyday_questions_go_to_naver() -> None:
    """국내 이야기(후기·업체·지역·제도)는 네이버가 낫다."""
    assert _pick("여수 순천 광양 회계 채용 공고", "auto")[0] == "naver"
    assert _pick("제주도 3박4일 경비 후기", "auto")[0] == "naver"


def test_bing_is_no_longer_a_default_anywhere() -> None:
    """빙은 아직 막힌다. 폴백으로만 남긴다."""
    for query in ("AI agent framework", "여수 채용", "playwright"):
        assert _pick(query, "auto")[0] != "bing"


def test_google_falls_back_to_naver_not_bing() -> None:
    assert _pick("anything", "google") == ["google", "naver"]
    assert _pick("아무거나", "naver") == ["naver", "google"]


def test_an_explicit_choice_is_respected() -> None:
    """사람이 콕 집으면 그대로 간다 — 막혀도 그 사실이 증거에 남는다."""
    assert _pick("여수 채용", "bing")[0] == "bing"


def test_the_prompt_no_longer_tells_the_model_to_avoid_google() -> None:
    assert "Google을 기본값으로 사용하지 마라" not in AGENT_SYSTEM_PROMPT
    assert "기본은 Google이다" in AGENT_SYSTEM_PROMPT


def test_the_prompt_puts_scrolling_into_the_routine() -> None:
    """실측 8판에서 스크롤·더보기가 한 번도 안 불렸다. 순서에 없으면 안 쓴다."""
    assert "browser_load_more" in AGENT_SYSTEM_PROMPT
    assert "browser_scroll" in AGENT_SYSTEM_PROMPT
    assert "반드시" in AGENT_SYSTEM_PROMPT
