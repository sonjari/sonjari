"""갔다고 그 사이트에서 읽은 것은 아니다.

2026-08-13. 오늘 가장 위험한 고장. "다나와에서 무선마우스 상위 3개"에 자비스는
**실제로 갔고, 실제로 읽었고, 값도 진짜였다.** 그런데 다른 가게 값이었다.

    browser_search       search.naver.com
    browser_open_result  prod.danawa.com/bridge/loadingBridgePowerShopping.php   ← 광고 브리지
    browser_extract      smartstore.naver.com/actto/products/...                 ← 여기서 읽음

창 제목이 내내 "행복쇼핑의 시작 ! 다나와 (가격비교)"로 찍혀서 로그만 봐서는 정상으로
보였다. 지어낸 답보다 이게 더 나쁘다 — 근거가 실재해서 검증을 안 하게 된다.

핵심은 **이동과 읽기를 가르는 것**이다. 브리지 '열기'는 다나와였고 '읽기'만 딴 데였다.
열기까지 세면 이 고장은 안 잡힌다.

그리고 판정하려면 "다나와 = danawa.com"을 알아야 하는데, 그 표가
`plan.SITE_ALIASES` 여덟 줄 하드코딩이었다 — 다나와·쿠팡·교보문고가 없어서 **대조가
아예 안 돌았다.** 여덟 곳 밖에서는 범용이 아니었다는 뜻이라, 표를 자비스가 스스로
채우게 했다(`site_atlas`).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from alture_jarvis.agent import named_sources, site_reads
from alture_jarvis.site_atlas import MIN_PAGES, SEED, SiteAtlas, registrable


def _read(url: str, title: str, tool: str = "browser_extract") -> dict[str, Any]:
    return {"tool": tool, "ok": True, "evidence": {"url": url, "title": title}}


# ── 주소 표 ──────────────────────────────────────────────────────────────────


def test_seeded_names_are_known_from_the_start() -> None:
    """한글 이름과 영문 주소가 안 겹치는 곳은 제목만으로는 영원히 못 배운다."""
    atlas = SiteAtlas(None)
    assert atlas.host_for("깃허브") == "github.com"
    assert "깃허브" in SEED


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("search.kyobobook.co.kr", "kyobobook.co.kr"),
        ("prod.danawa.com", "danawa.com"),
        ("www.coupang.com", "coupang.com"),
        ("job.gwangyang.go.kr", "gwangyang.go.kr"),
    ],
)
def test_it_finds_the_registrable_domain(host: str, expected: str) -> None:
    """`co.kr` 을 모르면 `kyobobook.co.kr` 이 `co.kr` 이 된다."""
    assert registrable(host) == expected


def test_one_page_is_not_enough() -> None:
    """제목 한 번으로 확정하면 '상담'·'블로그'가 naver.com 이 된다(실측)."""
    atlas = SiteAtlas(None)
    atlas.learn("골리", "https://www.goli.example/a", "골리 (가격비교)")
    assert atlas.host_for("골리") == ""


def test_two_pages_confirm_it() -> None:
    atlas = SiteAtlas(None)
    atlas.learn("골리", "https://www.goli.example/a", "골리 (가격비교)")
    atlas.learn("골리", "https://www.goli.example/b", "골리 (가격비교)")
    assert atlas.host_for("골리") == "goli.example"
    assert MIN_PAGES == 2


def test_a_word_that_points_at_two_places_is_not_a_site() -> None:
    """"광양"은 `gwangyang.go.kr` 과 `jobkorea.co.kr` 양쪽에서 나왔다 — 지명이라 그렇다.

    한 장짜리 증거만 갈려도 입을 다문다. 130 판 재현에서 "광양"이 한 도메인만
    보이던 시점에 확정돼 버렸고, 그 위에서 판정 셋이 틀렸다. 나중에 애매해졌지만
    **틀린 판정은 이미 나간 뒤였다.**
    """
    # 2026-10-08: 제목 「광양시 채용」은 이제 「광양」을 가르치지 않는다(이름이 조각의 머리 낱말과 같아야 한다).
    #   여기서는 「두 곳에 걸리면 입을 다문다」를 보려고, 머리에 그 낱말이 오는 제목을 쓴다.
    atlas = SiteAtlas(None)
    atlas.learn("광양", "https://job.gwangyang.go.kr/1", "광양 채용 안내")
    atlas.learn("광양", "https://job.gwangyang.go.kr/2", "광양 채용 안내")
    assert atlas.host_for("광양") == "gwangyang.go.kr"
    atlas.learn("광양", "https://www.jobkorea.co.kr/x", "광양 생산직 채용")
    assert atlas.host_for("광양") == ""


def test_search_results_never_teach_it_anything() -> None:
    """질의어가 제목에 그대로 들어간다: "골리 무선마우스 : 네이버 검색"."""
    atlas = SiteAtlas(None)
    for i in range(3):
        atlas.learn("골리", f"https://search.naver.com/x?q={i}", "골리 무선마우스 : 네이버 검색")
    assert atlas.host_for("골리") == ""


def test_a_passing_page_cannot_overwrite_a_seeded_name() -> None:
    atlas = SiteAtlas(None)
    for i in range(3):
        atlas.learn("크몽", f"https://ads.example.com/{i}", "크몽 외주 광고")
    assert atlas.host_for("크몽") == "kmong.com"


def test_it_survives_a_broken_file(tmp_path: Any) -> None:
    """표가 깨졌다고 자비스가 멈추면 안 된다. 씨앗만으로 계속 간다."""
    broken = tmp_path / "site_atlas.json"
    broken.write_text("{not json", encoding="utf-8")
    assert SiteAtlas(broken).host_for("크몽") == "kmong.com"


def test_what_it_learns_is_written_where_a_person_can_read_it(tmp_path: Any) -> None:
    path = tmp_path / "site_atlas.json"
    atlas = SiteAtlas(path)
    atlas.learn("골리", "https://www.goli.example/a", "골리 (가격비교)")
    atlas.learn("골리", "https://www.goli.example/b", "골리 (가격비교)")
    assert "goli.example" in json.loads(path.read_text(encoding="utf-8"))["seen"]["골리"]


# ── 호스트 잠금 ──────────────────────────────────────────────────────────────


def _atlas_knowing_danawa() -> SiteAtlas:
    atlas = SiteAtlas(None)
    atlas.learn("다나와", "https://prod.danawa.com/a", "다나와 (가격비교)")
    atlas.learn("다나와", "https://prod.danawa.com/b", "다나와 (가격비교)")
    return atlas


def test_the_bridge_that_sent_it_to_another_store() -> None:
    """오늘 실제로 일어난 그대로다."""
    steps = [
        {
            "tool": "browser_open_result",
            "ok": True,
            "evidence": {
                "url": "https://prod.danawa.com/bridge/loadingBridgePowerShopping.php",
                "title": "행복쇼핑의 시작 ! 다나와 (가격비교) - Danawa.com",
            },
        },
        _read("https://smartstore.naver.com/actto/products/7655009823", "엑토 ... BTM-12 : 엑토"),
    ]
    on_site, off_site = site_reads("다나와", steps, _atlas_knowing_danawa())
    assert not on_site, "브리지를 '연 것'은 읽은 것이 아니다"
    assert off_site == ["https://smartstore.naver.com/actto/products/7655009823"]


def test_reading_on_the_named_site_passes() -> None:
    steps = [_read("https://prod.danawa.com/info/?pcode=1", "무선마우스 - 다나와")]
    on_site, off_site = site_reads("다나와", steps, _atlas_knowing_danawa())
    assert on_site and not off_site


def test_a_name_it_does_not_know_is_never_judged() -> None:
    """모르면 침묵한다. 처음엔 제목으로 직접 판정했는데 130 판 중 21 판이 걸렸고
    절반이 오탐이었다 — "깃허브"가 github.com 을 못 알아보고, "광양에서"·
    "드라이브에서"·"이런데에서"까지 사이트로 셌다."""
    steps = [_read("https://blog.naver.com/x", "아무 글")]
    assert site_reads("광양", steps, SiteAtlas(None)) == ([], [])


def test_the_words_that_used_to_be_mistaken_for_sites() -> None:
    """이 이름들은 표가 비어 있으므로 판정 대상이 아니다 — 그게 요점이다."""
    atlas = SiteAtlas(None)
    for word in ("광양", "드라이브", "이런데"):
        assert not atlas.knows(word)


def test_named_sources_still_finds_the_real_ones() -> None:
    assert named_sources("다나와에서 무선마우스 상위 3개 알려줘") == ["다나와"]
