"""지목한 가게는 처음부터 가게로 안다 — 11번가 · G마켓 (2026-10-12 저녁).

이어지는 질문을 재다 나왔다(공식 9B · 창 32K · 같은 대화의 둘째 질문):

    「그거 11번가에서는 얼마야?」      계획에 「11번가에서 하기」가 없었다 → 웹 검색 결과만 읽다 「11번가 값은 못 찾았다」
    「아까 그거 11번가 값도 알려줘」    계획이 비었다 → 찾지 않고 5초 만에, 낮에 다른 판에서 읽은 값을 기억에서 꺼내 답했다
    「그 제품 G마켓 가격도 찾아봐」     개발 PC 는 써 보며 배워 알고 있어서 됐다 — 새로 깐 PC 는 모른다

「한 판은 잘하고 다음 질문에서 무너진다」의 한 갈래였다: 첫 질문은 길고 또렷해서 길을 찾지만, 짧은 둘째 질문은 가게 이름
하나에 기대는데 그 이름을 몰랐다. 같은 문장의 다나와 · 쿠팡은 알아봤다.
"""

from __future__ import annotations

import pytest

from alture_jarvis import serp
from alture_jarvis.plan import extract
from alture_jarvis.site_atlas import SEED


def _sites(prompt: str) -> list[tuple[str, ...]]:
    return [tuple(item.target) for item in extract(prompt) if item.kind == "site"]


@pytest.mark.parametrize(("prompt", "host"), [
    ("그거 11번가에서는 얼마야?", "11st.co.kr"),
    ("아까 그거 11번가 값도 알려줘", "11st.co.kr"),
    ("11번가에서 가상 마우스 최저가 알려줘", "11st.co.kr"),
    ("그 제품 G마켓 가격도 찾아봐", "gmarket.co.kr"),
    ("그거 지마켓에서는 얼마야?", "gmarket.co.kr"),
    ("How much is it on 11st?", "11st.co.kr"),
    ("Check the price on Gmarket too", "gmarket.co.kr"),
])
def test_a_short_follow_up_that_names_the_shop_gets_the_shop(prompt: str, host: str) -> None:
    assert _sites(prompt) == [(host,)], prompt


def test_the_neighbours_that_already_worked_still_do_and_numbers_are_not_shops() -> None:
    assert _sites("그거 다나와에서는 얼마야?") == [("danawa.com",)]
    assert _sites("그거 쿠팡에서는 얼마야?") == [("coupang.com",)]
    assert _sites("오늘 11시에 11번 버스 타야 해") == []
    assert SEED["11번가"] == "11st.co.kr" and SEED["G마켓"] == SEED["지마켓"] == "gmarket.co.kr"


def test_the_ad_centre_link_beside_naver_ads_is_not_a_result() -> None:
    """4B 판이 네이버 검색 1번(「네이버 광고주센터: 검색광고 소개」)을 열어 읽고 멈췄다."""
    rows = [
        {"href": "https://ads.naver.com/sa", "text": "네이버 광고주센터: 검색광고 소개"},
        {"href": "https://www.11st.co.kr/products/9000000001", "text": "가상 게임기 2 본체 700,000원"},
        {"href": "https://prod.danawa.com/info/?pcode=90000001", "text": "가상 게임기 2 본체 : 다나와 가격비교"},
    ]
    urls = [item.as_dict()["url"] for item in serp.collect_results(rows, limit=10, visited=[])]
    assert len(urls) == 2 and all("ads.naver.com" not in url for url in urls)
    assert urls[0].startswith("https://www.11st.co.kr/products/"), "남은 것의 순서는 화면 그대로"
