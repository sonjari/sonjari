"""만든 화면을 계산으로 잰다 — 글자가 덮였나 · 가로로 삐져나갔나 · 그림이 깨졌나 (2026-10-11).

쇼핑몰 과제 둘째 판(e936d144)의 실제 결함을 그대로 옮긴 페이지로 잰다: 품절 막이 `position: absolute; inset: 0` 인데
부모에 기준이 없어 첫 화면 전체를 덮었다. 손자리는 그 페이지를 열어 읽고 눌렀지만 글자로만 봐서 몰랐다.

양방향 표본이다 — 잡아야 하는 페이지와 **멀쩡한데 비슷하게 생긴** 페이지(붙어 다니는 머리띠 · 열린 대화 상자 · 글자 옆 배지 ·
고친 뒤의 같은 페이지)를 같이 본다. 틀린 경고는 모델을 엉뚱한 데로 보낸다.
"""
from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.layout_probe import LAYOUT_PROBE_JS, MAX_SCREENS, is_local_page, layout_issues, layout_note

BASE = """
<style>
  body { margin: 0; font: 16px/1.6 sans-serif; background: #faf5ee; color: #3a2e28; }
  header { position: sticky; top: 0; background: #faf5ee; padding: 14px 24px; border-bottom: 1px solid #ddd; }
  .hero { padding: 60px 24px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: 24px; }
  .card { border: 1px solid #ddd; border-radius: 12px; overflow: hidden; }
  .product-img { height: 180px; background: #f4e4e0; %(anchor)s }
  .soldout { position: absolute; inset: 0; background: rgba(250, 245, 238, .75); display: grid; place-items: center; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 99px; background: #eee; font-size: 12px; }
</style>
<header><a href="#">달다</a> <a href="#">상품</a> <a href="#">장바구니</a></header>
<section class="hero">
  <h1>오븐에서 갓 나와 지금 막 싸서 보냅니다.</h1>
  <p>오늘 들어온 재료만으로 소량 굽습니다. 품절이면 그건 끝.</p>
  <p>더 굽지 않고, 내일 다시 만납니다.</p>
</section>
<section class="grid">
  <article class="card"><div class="product-img"></div><h3>헤이즐넛 크루아상 <span class="badge">시그니처</span></h3><p>겉은 바삭, 속은 촉촉하게.</p></article>
  <article class="card"><div class="product-img"><span class="soldout">품절</span></div><h3>바나나브레드</h3><p>오늘 분은 다 나갔습니다.</p></article>
</section>
"""
BROKEN = BASE % {"anchor": ""}                      # 부모에 기준이 없다 — 막이 문서 전체를 덮는다
FIXED = BASE % {"anchor": "position: relative;"}    # 한 줄 넣은 뒤


def _probe(html: str, *, width: int = 800, height: int = 600, before: str = "") -> dict[str, Any]:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(html)
            if before:
                page.evaluate(before)
            found = page.evaluate(LAYOUT_PROBE_JS, MAX_SCREENS)
            found["scroll_after"] = page.evaluate("window.scrollY")
            return found
        finally:
            browser.close()


# --- 잡아야 하는 것 ---------------------------------------------------------------

def test_the_veil_that_covered_the_whole_first_screen_is_found() -> None:
    found = _probe(BROKEN)

    assert found["covered"], found
    top = found["covered"][0]
    assert top["by"] == "span.soldout" and top["position"] == "absolute" and top["anchored_to_page"] is True
    assert top["count"] >= 3 and top["samples"], "덮인 글의 본보기를 같이 준다(문서 순서로 앞의 셋)"
    lines = layout_issues(found)
    assert len(lines) == 1 and "span.soldout" in lines[0] and "문서 전체" in lines[0] and "덮고 있다" in lines[0]
    assert layout_note(lines).startswith("⚠ 화면 검사")


def test_the_same_page_after_the_one_line_fix_is_clean() -> None:
    found = _probe(FIXED)

    assert found["covered"] == [] and layout_issues(found) == []
    assert layout_note([]) == ""


def test_a_page_wider_than_the_screen_is_reported_with_what_sticks_out() -> None:
    html = FIXED + '<div class="banner" style="width: 1400px; height: 40px; background: #ccc">넓은 띠</div>'

    found = _probe(html)

    assert found["overflow"]["by_px"] >= 500 and "div.banner" in found["overflow"]["elements"]
    assert any("가로로 밀린다" in line and "div.banner" in line for line in layout_issues(found))


def test_an_image_that_did_not_load_is_counted() -> None:
    found = _probe(FIXED + '<img src="data:image/png;base64,AAAA" width="40" height="40" alt="">')

    assert found["broken_images"] == 1 and any("그림 1개" in line for line in layout_issues(found))


def test_a_veil_further_down_the_page_is_found_too() -> None:
    tall = FIXED.replace('<section class="grid">', '<div style="height: 900px"></div><section class="grid">')
    html = tall + (
        '<section style="padding: 24px"><h2>오시는 길</h2><p>골목 끝 두 번째 집입니다.</p><p>화요일은 쉽니다.</p>'
        '<div style="position: absolute; left: 0; right: 0; height: 400px; margin-top: -200px; background: rgba(0,0,0,.4)"></div></section>'
    )

    found = _probe(html)

    assert found["screens"] >= 2 and found["covered"], found
    assert found["scroll_after"] == 0, "훑은 뒤에는 원래 자리로 돌아온다"


# --- 멀쩡한데 비슷하게 생긴 것 -----------------------------------------------------

def test_a_sticky_header_over_scrolled_text_is_not_a_cover() -> None:
    html = FIXED + "".join(f"<p style='padding: 0 24px'>본문 문단 {i} — 아래로 길게 이어지는 글입니다.</p>" for i in range(60))

    found = _probe(html)

    assert found["screens"] >= 2 and found["covered"] == []


def test_an_open_dialog_covering_the_page_is_not_reported() -> None:
    html = FIXED + (
        '<div role="dialog" aria-modal="true" style="position: fixed; inset: 0; background: rgba(0,0,0,.5)">'
        '<div style="margin: 80px auto; width: 300px; background: #fff; padding: 20px"><h2>상세</h2><p>헤이즐넛 크루아상</p>'
        "<button>담기</button></div></div>"
    )

    found = _probe(html)

    assert found["covered"] == [] and layout_issues(found) == []


def test_a_small_badge_next_to_text_is_not_a_cover() -> None:
    html = FIXED + (
        '<p style="position: relative; padding: 24px">새로 나온 메뉴를 소개합니다'
        '<span style="position: absolute; left: 30px; top: 26px; width: 18px; height: 18px; background: red; border-radius: 9px"></span></p>'
    )

    assert _probe(html)["covered"] == []


def test_hidden_and_offscreen_things_are_ignored() -> None:
    html = FIXED + (
        '<aside style="position: fixed; top: 0; right: 0; width: 360px; height: 100%; transform: translateX(105%); background: #fff">'
        "<h2>장바구니</h2><p>비어 있어요</p><button>주문하기</button></aside>"
        '<p style="display: none">숨긴 글</p>'
    )

    found = _probe(html)

    assert found["covered"] == [] and found["overflow"] is None


# --- 줄로 옮기기 · 어디서 재는가 ----------------------------------------------------

def test_only_pages_on_this_pc_are_measured() -> None:
    for url in ("http://127.0.0.1:54513/index.html", "http://localhost:5173/", "file:///C:/work/index.html", "http://shop.localhost/"):
        assert is_local_page(url), url
    for url in ("https://www.danawa.com/", "https://example.com/localhost", "", "about:blank"):
        assert not is_local_page(url), url


def test_garbage_in_gives_no_lines() -> None:
    assert layout_issues(None) == [] and layout_issues({}) == [] and layout_issues({"covered": [{"count": 1}]}) == []


# --- 페이지 열기에 걸려 있는가 ------------------------------------------------------

class _FakePage:
    def __init__(self, url: str, found: Any) -> None:
        self.url, self._found, self.asked = url, found, 0

    def evaluate(self, script: str, *args: Any) -> Any:
        self.asked += 1
        if isinstance(self._found, Exception):
            raise self._found
        return self._found


_VEIL = {"covered": [{"by": "span.soldout", "width": 735, "height": 914, "position": "absolute", "anchored_to_page": True,
                      "count": 6, "samples": ["오븐에서 갓 나와"]}], "overflow": None, "broken_images": 0}


def _worker() -> Any:
    from alture_jarvis.browser import BrowserWorker

    return object.__new__(BrowserWorker)


def test_a_local_page_is_measured_when_opened_and_a_site_is_not() -> None:
    local, site = _FakePage("http://127.0.0.1:54513/index.html", _VEIL), _FakePage("https://www.danawa.com/", _VEIL)

    assert any("span.soldout" in line for line in _worker()._layout_check(local)) and local.asked == 1
    assert _worker()._layout_check(site) == [] and site.asked == 0, "남의 사이트에는 계산을 돌리지도 않는다"


def test_a_probe_that_breaks_never_breaks_the_open() -> None:
    assert _worker()._layout_check(_FakePage("http://localhost:5173/", RuntimeError("frame detached"))) == []


def test_opening_puts_the_finding_at_the_front_of_what_the_model_reads() -> None:
    import inspect

    from alture_jarvis.browser import BrowserWorker

    source = inspect.getsource(BrowserWorker._open)
    assert "layout_lines = self._layout_check(page)" in source
    assert source.index("_layout_probe.layout_note(layout_lines)") < source.index('marks.pop("date_instruction"'), "맨 앞에 세운다"
