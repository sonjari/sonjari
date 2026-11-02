"""이름 없는 누르기 하나로 보여 준 절차 전체를 버리지 않는다 (2026-10-30 · 대표 PC 10-29 00:47 `/레시피`).

대표가 보여 준 순서(감사 기록 77033): click · fill · press · nav · click · nav · … → 「2번째 걸음(click)의 요소를 다시 찾을 이름이
기록에 없습니다」로 레시피 전체를 거절했다. 첫 누르기는 검색칸에 치려고 누른 것인데, 누른 곳이 칸이 아니라 **칸을 감싼 상자**라
「칸을 누른 것은 걸음이 아니다」 거르개를 비켜 갔다. 상자에는 이름도 셀렉터도 없다.

고침 둘:
- 기록기 — 글 칸을 품은 상자 · 글 칸에 붙은 이름표를 누른 것은 걸음으로 적지 않는다(진짜 크로미움으로 본다).
- 변환 — 그래도 남은 이름 없는 누르기: 바로 뒤가 글 채우기면 뺀다(채우기가 그 칸을 스스로 잡는다) · 바로 뒤가 페이지 이동이면
  「그 주소 열기」로 바꾼다(사람이 간 곳은 그 주소다) · 둘 다 아니면 예전처럼 거절한다(빼면 다른 절차가 된다).
"""

from __future__ import annotations

import http.server
import threading
from functools import partial
from pathlib import Path

import pytest

from alture_jarvis.demo_recorder import steps_from_demo
from alture_jarvis.recipe_from_run import DraftRefused, draft_from_run

HOME = """<html><head><meta charset="utf-8"><title>가게</title>
<style>.box{padding:30px;border:1px solid #888;width:400px} .box input{width:200px}</style></head><body>
<form action="/results.html"><div class="box" id="wrap-98123"><span class="icon"></span><input name="q" placeholder="상품 검색"></div></form>
<label for="memo">메모</label><input id="memo" type="text">
<a href="/item.html" class="thumb"><img alt="" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="80" height="80"></a>
</body></html>"""
RESULTS = """<html><head><meta charset="utf-8"><title>결과</title></head><body>결과</body></html>"""


@pytest.fixture()
def shop(tmp_path: Path):
    (tmp_path / "index.html").write_text(HOME, encoding="utf-8")
    (tmp_path / "results.html").write_text(RESULTS, encoding="utf-8")
    (tmp_path / "item.html").write_text(RESULTS, encoding="utf-8")
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


@pytest.fixture()
def browser_page(shop: str, tmp_path: Path):
    playwright_api = pytest.importorskip("playwright.sync_api")
    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig

    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(5000)
            page.goto(shop + "/index.html")
            worker._context, worker._page = context, page
            yield worker, page, shop
        finally:
            browser.close()


def test_clicking_the_box_around_a_search_field_is_not_a_step(browser_page) -> None:
    worker, page, shop = browser_page
    worker._wire_demo()
    worker._demo.start(page.url)

    page.click(".box", position={"x": 8, "y": 8})   # 칸이 아니라 칸을 감싼 상자의 빈 곳
    page.click('[placeholder="상품 검색"]')
    page.keyboard.type("닌텐도 스위치 2")
    page.keyboard.press("Enter")
    page.wait_for_url("**/results.html?q=*")
    page.wait_for_timeout(300)

    kinds = [event["kind"] for event in worker._demo.stop()]
    assert "click" not in kinds, kinds


def test_clicking_the_label_of_a_text_field_is_not_a_step(browser_page) -> None:
    worker, page, _shop = browser_page
    worker._wire_demo()
    worker._demo.start(page.url)

    page.click("text=메모")
    page.keyboard.type("안녕")
    page.keyboard.press("Tab")
    page.wait_for_timeout(300)

    kinds = [event["kind"] for event in worker._demo.stop()]
    assert "click" not in kinds and "fill" in kinds, kinds


def test_a_real_button_is_still_a_step(browser_page) -> None:
    """역방향 — 이름 없는 그림 링크를 누른 것은 여전히 걸음으로 적힌다(지울지 말지는 변환이 정한다)."""
    worker, page, _shop = browser_page
    worker._wire_demo()
    worker._demo.start(page.url)

    page.click("a.thumb")
    page.wait_for_url("**/item.html")
    page.wait_for_timeout(300)

    kinds = [event["kind"] for event in worker._demo.stop()]
    assert "click" in kinds, kinds


SITE = "https://shop.example-mall.kr"


def _nameless_click(at: float) -> dict:
    return {"kind": "click", "selectors": [], "label": "", "url": SITE + "/", "at": at}


def _fill(at: float) -> dict:
    return {"kind": "fill", "selectors": ['[placeholder="상품 검색"]'], "field": "상품 검색", "value": "닌텐도", "url": SITE + "/", "at": at}


def _press(at: float) -> dict:
    return {"kind": "press", "key": "Enter", "selectors": ['[placeholder="상품 검색"]'], "field": "상품 검색", "url": SITE + "/", "at": at}


def test_the_founders_order_becomes_a_draft() -> None:
    """대표 판의 앞부분 그대로: 이름 없는 누르기 → 채우기 → Enter → 이동 → 이름 없는 그림 링크 → 이동."""
    events = [
        _nameless_click(1.0), _fill(2.0), _press(3.0),
        {"kind": "nav", "url": SITE + "/search?q=%EB%8B%8C%ED%85%90%EB%8F%84", "at": 3.5},
        {**_nameless_click(9.0), "url": SITE + "/search?q=%EB%8B%8C%ED%85%90%EB%8F%84"},
        {"kind": "nav", "url": SITE + "/item/777", "at": 9.6},
    ]
    steps = steps_from_demo(events, SITE + "/")
    assert [step["tool"] for step in steps] == ["browser_open", "browser_fill", "browser_press", "browser_open"]
    assert steps[-1]["evidence"]["url"] == SITE + "/item/777"
    draft = draft_from_run("최저가 상품 열기", steps)
    assert [step["do"] for step in draft["actions"]["from_run"]["steps"]][-1] == "open"


def test_a_nameless_click_that_changes_nothing_still_refuses() -> None:
    """역방향 — 이동도 없고 채우기 앞도 아닌 이름 없는 누르기(펼침 단추 같은 것)는 빼면 다른 절차가 된다. 예전처럼 거절."""
    events = [
        _nameless_click(1.0),
        {"kind": "click", "selectors": ['text="노트북"'], "label": "노트북", "url": SITE + "/", "at": 2.0},
        {"kind": "nav", "url": SITE + "/c/notebook", "at": 2.5},
    ]
    with pytest.raises(DraftRefused, match="2번째 걸음"):
        draft_from_run("노트북 칸 열기", steps_from_demo(events, SITE + "/"))


# ── 10-30 밤 두 번째 실패: 이름 없는 글 칸(감사 78132 · click · fill · press · nav …) ──────────────

BARE = """<html><head><meta charset="utf-8"><title>bare</title></head><body>
<form action="/results.html"><input id="x-91234" type="text"></form></body></html>"""


def test_a_field_with_no_name_is_found_by_its_shape(browser_page) -> None:
    """단서(testid · id · name · 안내문 · aria-label)가 하나도 없는 칸 — 페이지에 하나뿐이면 그 모양으로 적는다."""
    worker, page, shop = browser_page
    page.set_content(BARE)
    worker._wire_demo()
    worker._demo.start(page.url)
    page.click("input")
    page.keyboard.type("닌텐도")
    page.keyboard.press("Tab")
    page.wait_for_timeout(300)
    fills = [event for event in worker._demo.stop() if event["kind"] == "fill"]
    assert fills and fills[0]["selectors"] == ['input[type="text"]'], fills


def test_a_nameless_search_field_becomes_opening_the_search_address() -> None:
    events = [
        _nameless_click(1.0),
        {"kind": "fill", "selectors": [], "field": "", "value": "닌텐도", "url": SITE + "/", "at": 2.0},
        {"kind": "press", "key": "Enter", "selectors": [], "field": "", "url": SITE + "/", "at": 3.0},
        {"kind": "nav", "url": SITE + "/search?q=%EB%8B%8C%ED%85%90%EB%8F%84", "at": 3.4},
    ]
    steps = steps_from_demo(events, SITE + "/")
    assert [step["tool"] for step in steps] == ["browser_open", "browser_site_search"]
    draft = draft_from_run("닌텐도 검색", steps)
    opened = [step for step in draft["actions"]["from_run"]["steps"] if step["do"] == "open"]
    assert "{query}" in opened[-1]["url"], opened


def test_a_nameless_field_that_does_not_search_still_refuses() -> None:
    """역방향 — 친 글이 주소에 안 들어가면(검색이 아님) 바꾸지 않는다. 예전처럼 거절."""
    events = [
        {"kind": "fill", "selectors": [], "field": "", "value": "메모", "url": SITE + "/", "at": 2.0},
        {"kind": "press", "key": "Enter", "selectors": [], "field": "", "url": SITE + "/", "at": 3.0},
        {"kind": "nav", "url": SITE + "/saved", "at": 3.4},
    ]
    with pytest.raises(DraftRefused, match="fill"):
        draft_from_run("메모 저장", steps_from_demo(events, SITE + "/"))


# ── 10-30 밤: 배우기는 구글에서 시작 — 검색으로 거쳐 온 앞부분은 뗀다 ──────────────

def test_a_demo_that_starts_on_google_begins_at_the_site_reached() -> None:
    google = "https://www.google.com/"
    events = [
        {"kind": "fill", "selectors": ['textarea[name="q"]'], "field": "검색", "value": "알라딘", "url": google, "at": 1.0},
        {"kind": "press", "key": "Enter", "selectors": ['textarea[name="q"]'], "field": "검색", "url": google, "at": 2.0},
        {"kind": "nav", "url": "https://www.google.com/search?q=%EC%95%8C%EB%9D%BC%EB%94%98", "at": 2.4},
        {"kind": "click", "selectors": ['text="알라딘"'], "label": "알라딘", "url": "https://www.google.com/search?q=x", "at": 4.0},
        {"kind": "nav", "url": "https://www.aladin.co.kr/", "at": 4.5},
        {"kind": "fill", "selectors": ['[placeholder="검색어"]'], "field": "검색어", "value": "파이썬", "url": "https://www.aladin.co.kr/", "at": 6.0},
        {"kind": "press", "key": "Enter", "selectors": ['[placeholder="검색어"]'], "field": "검색어", "url": "https://www.aladin.co.kr/", "at": 7.0},
        {"kind": "nav", "url": "https://www.aladin.co.kr/search?q=%ED%8C%8C%EC%9D%B4%EC%8D%AC", "at": 7.4},
    ]
    steps = steps_from_demo(events, google)
    assert steps[0]["tool"] == "browser_open" and steps[0]["evidence"]["url"] == "https://www.aladin.co.kr/"
    draft = draft_from_run("알라딘 책 검색", steps)   # 여러 사이트를 오간 판으로 거절되지 않는다
    assert draft["actions"]["from_run"]["steps"][0]["url"].startswith("https://www.aladin.co.kr")


def test_a_demo_that_stays_on_google_is_left_as_it_is() -> None:
    google = "https://www.google.com/"
    events = [
        {"kind": "fill", "selectors": ['textarea[name="q"]'], "field": "검색", "value": "날씨", "url": google, "at": 1.0},
        {"kind": "press", "key": "Enter", "selectors": ['textarea[name="q"]'], "field": "검색", "url": google, "at": 2.0},
        {"kind": "nav", "url": "https://www.google.com/search?q=%EB%82%A0%EC%94%A8", "at": 2.4},
    ]
    steps = steps_from_demo(events, google)
    assert steps[0]["evidence"]["url"] == google and len(steps) == 3
