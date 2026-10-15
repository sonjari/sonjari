"""사이트가 박아 둔 구조화 데이터를 읽는다 — 진짜 크로미움 + 요약 규칙 (2026-09-18)."""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis import structured_data as sd

BOOK_PAGE = """<!doctype html><html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":["Book","Product"],"name":"Do it! 점프 투 파이썬",
"image":"https://img/x.jpg","isbn":"9791163034735","numberOfPages":432,"datePublished":"2023-06-15",
"author":{"@type":"Person","name":"박응용"},"publisher":{"@type":"Organization","name":"이지스퍼블리싱","logo":"l.png"}}</script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}</script>
<meta property="og:title" content="Do it! 점프 투 파이썬"><meta property="og:price" content="18800">
</head><body><p>본문</p></body></html>"""

GRAPH_PAGE = """<!doctype html><html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"스토어"},
{"@type":"SoftwareApplication","name":"ChatGPT","author":{"@type":"Organization","name":"OpenAI"},
"aggregateRating":{"@type":"AggregateRating","ratingValue":"3.5","ratingCount":"104"},
"offers":{"@type":"Offer","price":"0","priceCurrency":"KRW"},"screenshot":["a.png","b.png"]}]}
</script></head><body></body></html>"""

# 다나와에서 본 고장 모양: 문자열 안 날것 줄바꿈 + 끝 쉼표
BROKEN_PAGE = """<!doctype html><html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"ATK VXE R1 SE+
유무선 마우스","offers":{"@type":"AggregateOffer","lowPrice":"39900","priceCurrency":"KRW",},}
</script></head><body></body></html>"""

EMPTY_PAGE = "<!doctype html><html><head><title>x</title></head><body>그냥 글</body></html>"


def test_summary_keeps_values_and_drops_noise() -> None:
    raw = {"blocks": [{"@type": ["Book", "Product"], "name": "책", "image": "x.jpg", "isbn": "9791163034735",
                       "numberOfPages": 432, "author": {"@type": "Person", "name": "박응용"}},
                      {"@type": "WebSite", "name": "사이트"}], "meta": {"og:price": "18800"}}
    out = sd.summarize(raw)
    fields = out["items"][0]["fields"]
    assert "isbn: 9791163034735" in fields and "numberOfPages: 432" in fields and "author: 박응용" in fields
    assert not any(f.startswith("image") for f in fields), "이미지 주소는 모델의 주의만 먹는다"
    assert len(out["items"]) == 1, "사이트 소개(WebSite)는 버린다"
    assert out["meta"] == {"og:price": "18800"}
    assert sd.summarize({"blocks": [], "meta": {}}) == {}


@pytest.fixture(scope="module")
def page():
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        page = browser.new_page()
        yield page
        browser.close()


def _read(worker, page, html: str) -> dict:
    page.set_content(html)
    return worker._structured_data(page)


@pytest.fixture()
def worker(tmp_path: Path):
    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig

    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))


def test_a_book_page_gives_isbn_and_pages_in_a_real_browser(worker, page) -> None:
    out = _read(worker, page, BOOK_PAGE)
    fields = out["items"][0]["fields"]
    assert "isbn: 9791163034735" in fields and "numberOfPages: 432" in fields
    assert "publisher: 이지스퍼블리싱" in fields
    assert out["meta"]["og:price"] == "18800"


def test_a_graph_page_gives_rating_and_author(worker, page) -> None:
    out = _read(worker, page, GRAPH_PAGE)
    assert len(out["items"]) == 1
    fields = out["items"][0]["fields"]
    assert "aggregateRating.ratingValue: 3.5" in fields and "author: OpenAI" in fields
    assert "offers.price: 0" in fields


def test_a_broken_block_is_read_leniently(worker, page) -> None:
    out = _read(worker, page, BROKEN_PAGE)
    fields = out["items"][0]["fields"]
    assert any(f.startswith("name: ATK VXE R1 SE+") for f in fields) and "offers.lowPrice: 39900" in fields


def test_nothing_structured_gives_nothing(worker, page) -> None:
    assert _read(worker, page, EMPTY_PAGE) == {}


def test_extract_through_the_agent_door_carries_structured_data_and_the_note(worker, page, monkeypatch) -> None:
    page.set_content(BOOK_PAGE.replace("<p>본문</p>", "<article><p>" + "본문 문장입니다. " * 40 + "</p></article>"))
    monkeypatch.setattr(worker, "_sweep_for_lazy_content", lambda _page: None)
    result = worker._extract_with_data(page, {})
    assert "9791163034735" in str(result["structured_data"])
    assert "structured_data" in result["instruction"]
