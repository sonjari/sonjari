"""판정기가 못 가르는 사이트의 **상세 주소 표식** (2026-10-05 9B 판 — arXiv 목록 · 네이버 뉴스 섹션).

arXiv 에서 순위 1·2·3 이 「본문으로 건너뛰기」·날짜 넘김 링크를 열었고, 네이버 뉴스에서 순위 2번이 「24개의 관련뉴스 더보기」였다.
판정기 규칙을 바꾸는 실험은 얼린 표본(다나와·잡코리아·교보)을 깨뜨려 되돌렸다 — 그 두 사이트만 자료로 적는다.
"""
from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis import result_links
from alture_jarvis.browser import BrowserWorker

FOLDER = Path(__file__).resolve().parents[1] / "recipes" / "result_links"


def test_every_file_says_where_it_was_checked():
    files = sorted(FOLDER.glob("*.json"))
    assert files, "표식 파일이 하나도 없다 — 폴더가 사라지면 이 시험이 조용히 통과하면 안 된다"
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["hosts"] and raw["detail_url_contains"], path.name
        assert raw.get("why") and raw.get("checked"), f"{path.name}: 왜 적었고 어디서 확인했는지가 없다"


def test_known_sites_and_their_subdomains():
    assert result_links.markers_for("arxiv.org") == ["/abs/"]
    assert result_links.markers_for("www.arxiv.org") == ["/abs/"]
    assert result_links.markers_for("export.arxiv.org") == ["/abs/"]
    assert result_links.markers_for("news.naver.com") == ["/article/"]


def test_an_unknown_site_is_not_filtered():
    # 네이버 검색·블로그는 뉴스가 아니다 — 호스트가 정확히 맞을 때만.
    for host in ("search.naver.com", "naver.com", "blog.naver.com", "github.com", ""):
        assert result_links.markers_for(host) == [], host


def test_the_marks_keep_only_the_items_in_screen_order():
    """9B 판에서 실제로 순위가 됐던 것들: 건너뛰기 · 날짜 넘김 · (그 뒤에야) 논문."""
    wide = [
        {"rank": 1, "title": "Skip to main content", "url": "https://arxiv.org/list/cs.CL/recent#content"},
        {"rank": 2, "title": "Mon, 5 Oct 2026", "url": "https://arxiv.org/list/cs.CL/recent?skip=0&show=50"},
        {"rank": 3, "title": "arXiv:2610.03695", "url": "https://arxiv.org/abs/2610.03695"},
        {"rank": 4, "title": "pdf", "url": "https://arxiv.org/pdf/2610.03695"},
        {"rank": 5, "title": "Adithya Bhaskar", "url": "https://arxiv.org/search/cs?searchtype=author&query=Bhaskar,+A"},
        {"rank": 6, "title": "arXiv:2610.03625", "url": "https://arxiv.org/abs/2610.03625"},
    ]
    kept = BrowserWorker._filter_reviewed_results(wide, result_links.markers_for("arxiv.org"), limit=15)
    assert [(item["rank"], item["url"].rsplit("/", 1)[-1]) for item in kept] == [(1, "2610.03695"), (2, "2610.03625")]


def test_the_cluster_link_is_not_an_article():
    listed = [
        {"rank": 1, "title": "누리호, 7일 우주로", "url": "https://n.news.naver.com/mnews/article/001/0016356223"},
        {"rank": 2, "title": "24\n개의 관련뉴스 더보기", "url": "https://news.naver.com/cluster/c_202609291210_00000018/section/105?oid=001"},
        {"rank": 3, "title": "은행권 턴 해킹", "url": "https://n.news.naver.com/mnews/article/421/0009210003"},
    ]
    kept = BrowserWorker._filter_reviewed_results(listed, result_links.markers_for("news.naver.com"), limit=15)
    assert [item["title"] for item in kept] == ["누리호, 7일 우주로", "은행권 턴 해킹"]
    assert [item["rank"] for item in kept] == [1, 2]


def test_danawa_search_keeps_product_pages_and_drops_the_ad_bridge():
    """2026-10-11 가격 조사 판 둘: 순위 1번이 다른 가게로 넘어가는 광고 링크였다 — 다나와 줄에 다른 가게 값이 적혔다."""
    assert result_links.markers_for("search.danawa.com") == ["prod.danawa.com/info"]
    # 다나와의 다른 화면(첫 화면 · 상품 페이지)은 검색 결과가 아니다.
    assert result_links.markers_for("www.danawa.com") == [] and result_links.markers_for("prod.danawa.com") == []
    listed = [
        {"rank": 1, "title": "무선 마우스 특가", "url": "https://prod.danawa.com/bridge/go_link_goods.php?cate_c1=861&cmpny_c=EE128&link_prod_c=1"},
        {"rank": 2, "title": "가상 무선 마우스 M3 (정품)", "url": "https://prod.danawa.com/info/?pcode=1000001&keyword=x&cate=112787"},
        {"rank": 3, "title": "가상 무선 마우스 M2", "url": "https://prod.danawa.com/info?pcode=1000002"},
    ]
    kept = BrowserWorker._filter_reviewed_results(listed, result_links.markers_for("search.danawa.com"), limit=15)
    assert [item["title"] for item in kept] == ["가상 무선 마우스 M3 (정품)", "가상 무선 마우스 M2"]
    assert [item["rank"] for item in kept] == [1, 2]


def test_gmarket_ad_cards_share_the_item_address_and_one_parameter_tells_them_apart():
    """2026-10-12 G마켓 검색 결과: 광고 묶음 7장이 상품과 같은 주소 꼴(`item.gmarket.co.kr/Item?goodscode=`)에 `buyboxtype=ad` 만
    더 붙어 있었다(`recipes/result_links/gmarket.json`). 「이 꼴만 센다」로는 못 가른다 — 「이 꼬리는 뺀다」가 있어야 한다."""
    marks = result_links.markers_for("www.gmarket.co.kr")
    assert marks == ["item.gmarket.co.kr/Item", "!buyboxtype=ad"]
    listed = [
        {"rank": 1, "title": "가상 게임기 2 본체 묶음(광고)", "url": "https://item.gmarket.co.kr/Item?goodscode=9000000001&buyboxtype=ad&utparam-url=%7B%22a%22%3A1%7D"},
        {"rank": 2, "title": "가상 게임기 2 본체", "url": "https://item.gmarket.co.kr/Item?goodscode=9000000002&utparam-url=%7B%22a%22%3A1%7D"},
        {"rank": 3, "title": "배너", "url": "https://ad.esmplus.com/CPC/Main?x=1"},
        {"rank": 4, "title": "베스트", "url": "https://www.gmarket.co.kr/n/best"},
        {"rank": 5, "title": "가상 게임기 2 본체 세트", "url": "https://item.gmarket.co.kr/Item?goodscode=9000000003"},
    ]
    kept = BrowserWorker._filter_reviewed_results(listed, marks, limit=15)
    assert [(item["rank"], item["title"]) for item in kept] == [(1, "가상 게임기 2 본체"), (2, "가상 게임기 2 본체 세트")]


def test_the_ad_tail_survives_the_road_that_builds_the_ranks():
    """빼는 표식은 순위를 만드는 길이 그 꼬리를 남겨 줘야 일한다 — 주소를 다듬는 자리가 지우면 조용히 헛돈다."""
    from alture_jarvis.serp import collect_results

    rows = [
        {"href": "https://item.gmarket.co.kr/Item?goodscode=9000000001&buyboxtype=ad&utparam-url=%7B%22a%22%3A1%7D", "text": "가상 게임기 2 본체 묶음 100,000원"},
        {"href": "https://item.gmarket.co.kr/Item?goodscode=9000000002&utparam-url=%7B%22a%22%3A1%7D", "text": "가상 게임기 2 본체 200,000원"},
    ]
    urls = [item.as_dict()["url"] for item in collect_results(rows, limit=10, visited=[])]
    assert len(urls) == 2 and "buyboxtype=ad" in urls[0] and "buyboxtype=ad" not in urls[1]


def test_an_exclusion_works_without_a_wanted_mark_and_plain_marks_are_unchanged():
    listed = [
        {"rank": 1, "title": "가", "url": "https://example.test/p/1?kind=ad"},
        {"rank": 2, "title": "나", "url": "https://example.test/p/2"},
        {"rank": 3, "title": "다", "url": "https://example.test/about"},
    ]
    assert [item["title"] for item in BrowserWorker._filter_reviewed_results(listed, ["!kind=ad"], limit=15)] == ["나", "다"]
    assert [item["title"] for item in BrowserWorker._filter_reviewed_results(listed, ["/p/"], limit=15)] == ["가", "나"]
    assert [item["title"] for item in BrowserWorker._filter_reviewed_results(listed, ["/p/", "!kind=ad"], limit=15)] == ["나"]
    # 표식이 없으면 아무것도 거르지 않는다 · 느낌표 하나짜리는 표식이 아니다.
    assert len(BrowserWorker._filter_reviewed_results(listed, [], limit=15)) == 3
    assert len(BrowserWorker._filter_reviewed_results(listed, ["!"], limit=15)) == 3


def test_11st_search_keeps_product_pages_and_drops_the_ad_cards():
    """2026-10-12 창 32K 의 9B 판: 「검색 결과 열기」가 광고 묶음의 조립 PC 를 열어 읽었다 — 찾던 것은 게임기였다.
    그날 그 화면을 직접 열어 보니 광고 카드는 광고 주소로, 진짜 상품은 상품 주소로 갔다(`recipes/result_links/11st.json`)."""
    assert result_links.markers_for("search.11st.co.kr") == ["www.11st.co.kr/products/"]
    # 11번가의 다른 화면(첫 화면 · 상품 페이지)은 검색 결과가 아니다.
    assert result_links.markers_for("www.11st.co.kr") == [] and result_links.markers_for("11st.co.kr") == []
    listed = [
        {"rank": 1, "title": "가상 조립PC 게이밍 데스크탑 본체", "url": "https://action.adoffice.11st.co.kr/act/click/v1/landing/clickdata/compress?p=abc"},
        {"rank": 2, "title": "가상상점", "url": "https://shop.11st.co.kr/stores/100001"},
        {"rank": 3, "title": "가상 게임기 2 본체 단품", "url": "https://www.11st.co.kr/products/9000000001?trTypeCd=PW24&trCtgrNo=585021"},
        {"rank": 4, "title": "가상 게임기 2 본체 세트", "url": "https://www.11st.co.kr/products/9000000002"},
    ]
    kept = BrowserWorker._filter_reviewed_results(listed, result_links.markers_for("search.11st.co.kr"), limit=15)
    assert [item["title"] for item in kept] == ["가상 게임기 2 본체 단품", "가상 게임기 2 본체 세트"]
    assert [item["rank"] for item in kept] == [1, 2]
