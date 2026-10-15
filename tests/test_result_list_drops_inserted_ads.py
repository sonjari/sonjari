"""결과 목록 **안에** 끼워 넣은 광고·이벤트는 항목이 아니다 — 실제 크로미움으로 (2026-09-18).

당근마켓 「책상」 목록 40개 중 8개가 ader.naver.com·adoffice.11st.co.kr 광고였고 **1번이 광고**였다.
YES24 「파이썬」 2위는 event.yes24.com 분철 서비스, 다나와는 event.danawa.com 하나가 상품 사이에 있었다.
광고가 같은 생김새의 칸을 빌려 쓰니 묶음 고르기로는 못 가른다 — 목적지로 가른다.

반대쪽도 잰다: 검색엔진 결과처럼 원래 딴 사이트로 가는 목록, 같은 사이트의 여러 칸짜리 하위 목록(다나와 장터)은
**한 개도 안 잃어야** 한다. 판정이 `location.host` 를 쓰니 set_content(about:blank)가 아니라 주소를 가로채 띄운다.
"""

from __future__ import annotations

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from alture_jarvis.browser import BrowserWorker  # noqa: E402


def _card(href: str, title: str) -> str:
    return (f'<li class="card"><a class="title" href="{href}">{title}</a>'
            f'<a class="shop" href="{href}">가게 이름</a></li>')


SHOP_PAGE = "<!doctype html><html><head><meta charset='utf-8'></head><body><main><ul class='list'>" + "".join([
    _card("https://ader.naver.com/v1/AbCdEf123", "조이 시리즈 책상 조명 109,000원 광고"),
    *[_card(f"https://www.shop.co.kr/kr/buy-sell/desk-{i}/", f"원목 책상 {i}번 30,000원 한남동 3일 전") for i in range(1, 5)],
    _card("https://event.shop.co.kr/bookBindService", "분철 서비스 이벤트 안내 바로가기"),
    *[_card(f"https://www.shop.co.kr/kr/buy-sell/desk-{i}/", f"원목 책상 {i}번 30,000원 한남동 3일 전") for i in range(5, 9)],
    _card("https://analytics.adoffice.11st.co.kr/act/click/v1/landing", "접이식 테이블 침대책상 광고 상품"),
    *[_card(f"https://mall.shop.co.kr/sale/{i}", f"장터 매물 {i}번 미개봉 새 상품 10,000원") for i in range(1, 4)],
    *[_card(f"https://www.shop.co.kr/kr/buy-sell/desk-{i}/", f"원목 책상 {i}번 30,000원 한남동 3일 전") for i in range(9, 14)],
]) + "</ul></main></body></html>"

SERP_PAGE = "<!doctype html><html><head><meta charset='utf-8'></head><body><main><ul class='results'>" + "".join(
    _card(href, f"파이썬 책 추천 글 제목 번호 {n} 입니다")
    for n, href in enumerate([
        "https://blog.search.co.kr/user1/1", "https://news.example.com/article/2", "https://cafe.search.co.kr/club/3",
        "https://www.other.org/python/4", "https://blog.search.co.kr/user2/5", "https://docs.python.org/3/6",
    ], 1)
) + "</ul></main></body></html>"


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield launched
        launched.close()


def _rows_at(browser, url: str, html: str) -> list[dict]:
    page = browser.new_page(viewport={"width": 1280, "height": 2400})
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
    page.goto(url)
    rows = page.evaluate(BrowserWorker._RESULT_LIST_JS) or []
    page.close()
    return rows


def test_ads_and_a_lone_event_link_are_dropped_from_a_shop_list(browser) -> None:
    rows = _rows_at(browser, "https://www.shop.co.kr/kr/buy-sell/s/?search=desk", SHOP_PAGE)
    hrefs = [r["href"] for r in rows]
    assert not any("ader.naver.com" in h or "adoffice.11st" in h for h in hrefs), hrefs
    assert not any("event.shop.co.kr" in h for h in hrefs), hrefs
    assert "desk-1" in hrefs[0], f"1번은 진짜 매물이어야 한다: {hrefs[:3]}"
    # 여러 칸짜리 같은 사이트 하위 목록(다나와 장터 꼴)은 목록의 일부다.
    assert sum(1 for h in hrefs if "mall.shop.co.kr" in h) == 6, hrefs
    assert sum(1 for h in hrefs if "/buy-sell/desk-" in h) == 26


def test_a_search_engine_list_keeps_every_outside_result(browser) -> None:
    rows = _rows_at(browser, "https://search.search.co.kr/search?query=python", SERP_PAGE)
    assert len(rows) == 12, [r["href"] for r in rows]


def _ad_card(n: int) -> str:
    # 광고 칸의 모양 — 보이는 글자는 광고주 주소, 링크는 전부 중계 주소. 카드 하나가 링크를 여럿 낸다.
    href = f"https://ads.portal.co.kr/v1/token{n}"
    return (f'<li class="ad"><a href="{href}">광고주 {n} 교육 브랜드 대상 수상</a>'
            f'<a href="{href}">advertiser{n}.com</a>'
            f'<a href="{href}?x=1">이벤트 무료 체험 신청하기 바로가기</a>'
            f'<a href="{href}?x=2">수강 후기 보러가기 상세 안내</a></li>')


def _organic(n: int) -> str:
    # 보통 결과 — 보이는 주소와 가는 곳이 같은 사이트
    return (f'<div class="res"><a href="https://site{n}.org/python/book">파이썬 책 추천 글 제목 번호 {n}\nsite{n}.org›python</a>'
            f'<span>본문 요약</span></div>')


PORTAL_PAGE = ("<!doctype html><html><head><meta charset='utf-8'></head><body><main>"
               "<ul class='ads'>" + "".join(_ad_card(i) for i in range(1, 6)) + "</ul>"
               "<section class='organic'>" + "".join(_organic(i) for i in range(1, 6)) + "</section>"
               "</main></body></html>")


def test_a_block_of_ads_showing_advertiser_addresses_is_not_the_result_list(browser) -> None:
    rows = _rows_at(browser, "https://search.portal.co.kr/search?query=python", PORTAL_PAGE)
    hrefs = [r["href"] for r in rows]
    assert hrefs and not any("ads.portal.co.kr" in h for h in hrefs), hrefs[:4]
    assert sum(1 for h in hrefs if "/python/book" in h) == 5, "보이는 주소와 가는 곳이 같은 보통 결과는 그대로여야 한다"
