"""사람이 한 번 해 보이면 레시피 초안 (2026-10-20 · 확장 설계 P2 · T8 「배우기」).

P0 실측(설계 §10): 잘 해낸 판에서 나온 누르는 절차는 2,623판 중 14개 · 재생 1/14 — 누르는 절차는 사람이 보여 줘야 생긴다.
여기서는 진짜 크로미움에서 사람 손처럼 치고 누르고(Playwright 의 실제 입력 → 페이지의 진짜 사건), 기록기가 그것을
요소 단위로 적어 **판 기록과 같은 출구**(`draft_from_run`)로 초안이 되는지 본다.
"""

from __future__ import annotations

import http.server
import threading
from functools import partial
from pathlib import Path

import pytest

from alture_jarvis.demo_recorder import DemoRecorder, steps_from_demo
from alture_jarvis.recipe_from_run import DraftRefused, draft_from_run
from alture_jarvis.site_recipes import SiteRecipe

HOME = """<html><head><meta charset="utf-8"><title>가게</title></head><body>
<form action="/results.html"><input name="q" placeholder="상품 검색"></form><input type="password" name="pw" placeholder="비밀번호">
<select id="cat"><option>전체</option><option>노트북</option></select>
</body></html>"""
RESULTS = """<html><head><meta charset="utf-8"><title>결과</title></head><body>
<a href="/results.html?sort=low" data-testid="sort-low">낮은 가격순</a>
</body></html>"""


@pytest.fixture()
def shop(tmp_path: Path):
    (tmp_path / "index.html").write_text(HOME, encoding="utf-8")
    (tmp_path / "results.html").write_text(RESULTS, encoding="utf-8")
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


def _as_if_on_a_real_site(steps: list[dict], shop: str) -> list[dict]:
    """시험 가게는 이 PC 주소라 변환기가 거절한다(시험 주소는 레시피가 아니다) — 같은 기록을 진짜 사이트 주소로 바꿔 넣는다."""
    import json

    return json.loads(json.dumps(steps).replace(shop, "https://shop.example-mall.kr"))


def test_a_person_types_presses_enter_and_sorts_and_it_becomes_a_draft(browser_page) -> None:
    worker, page, shop = browser_page
    worker._wire_demo()
    worker._demo.start(page.url)

    page.click('[placeholder="상품 검색"]')
    page.keyboard.type("닌텐도 스위치 2")
    page.keyboard.press("Enter")
    page.wait_for_url("**/results.html?q=*")
    page.click("text=낮은 가격순")
    page.wait_for_url("**sort=low")
    page.wait_for_timeout(300)

    events = worker._demo.stop()
    kinds = [event["kind"] for event in events]
    assert kinds.count("fill") == 1 and "press" in kinds and kinds.count("click") == 1, "검색칸을 누른 손동작은 걸음이 아니다"

    draft = draft_from_run("가게에서 최저가", _as_if_on_a_real_site(steps_from_demo(events, worker._demo.start_url), shop))
    action = draft["actions"]["from_run"]
    dos = [step["do"] for step in action["steps"]]
    assert dos[:2] == ["open", "dismiss"] and "fill" in dos and "press" in dos and dos[-1] == "click"
    assert draft["_slots"] == {"query": "닌텐도 스위치 2"}
    fill = next(step for step in action["steps"] if step["do"] == "fill")
    assert '[placeholder="상품 검색"]' in draft["targets"][fill["target"]]
    click = action["steps"][-1]
    assert '[data-testid="sort-low"]' in draft["targets"][click["target"]] and click["expect"] == {"kind": "url_changes"}
    assert action["risk"] == "L2", "누르는 걸음이 있으면 저장에 사람 승인이 든다"
    SiteRecipe(Path("demo.json"), draft)


def test_password_typing_is_counted_but_never_recorded(browser_page) -> None:
    worker, page, _shop = browser_page
    worker._wire_demo()
    worker._demo.start(page.url)
    page.click('[placeholder="비밀번호"]')
    page.keyboard.type("hunter2")
    page.click('[placeholder="상품 검색"]')
    page.wait_for_timeout(300)
    events = worker._demo.stop()
    assert worker._demo.secrets_skipped == 1
    assert "hunter2" not in str(events)


def test_nothing_is_recorded_outside_start_and_stop(browser_page) -> None:
    worker, page, _shop = browser_page
    worker._wire_demo()
    page.click('[placeholder="상품 검색"]')
    page.keyboard.type("시작 전")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    worker._demo.start(page.url)
    assert worker._demo.stop() == []


def test_a_pick_from_a_list_refuses_instead_of_silently_dropping() -> None:
    events = [{"kind": "select", "value": "노트북", "url": "https://shop.example-mall.kr/", "at": 1.0}]
    with pytest.raises(DraftRefused, match="고르기"):
        steps_from_demo(events, "https://shop.example-mall.kr/")


def test_a_navigation_right_after_a_click_is_that_clicks_result_not_an_open() -> None:
    events = [
        {"kind": "click", "selectors": ['text="노트북"'], "label": "노트북", "url": "https://a.kr/", "at": 1.0},
        {"kind": "nav", "url": "https://a.kr/c/notebook", "at": 2.0},
        {"kind": "nav", "url": "https://a.kr/typed-by-hand", "at": 30.0},
    ]
    steps = steps_from_demo(events, "https://a.kr/")
    assert [step["tool"] for step in steps] == ["browser_open", "browser_click", "browser_open"]
    assert steps[1]["evidence"]["url"] == "https://a.kr/c/notebook"


def test_the_recorder_ignores_events_when_not_recording() -> None:
    recorder = DemoRecorder(clock=lambda: 5.0)
    recorder.on_event({"kind": "click"})
    recorder.on_navigation("https://a.kr/")
    assert recorder.events == []
    recorder.start("https://a.kr/")
    recorder.on_event({"kind": "click", "selectors": ["#a"]})
    recorder.on_event({"kind": "secret"})
    assert recorder.stop() == [{"kind": "click", "selectors": ["#a"], "at": 5.0}] and recorder.secrets_skipped == 1


# ── 대화로 배우기 ──────────────────────────────────────────────────────────────
from alture_jarvis.runtime import JarvisRuntime  # noqa: E402
from alture_jarvis.self_talk import SelfContext, SelfTalk  # noqa: E402

DEMO_EVENTS = [
    {"kind": "fill", "selectors": ['[placeholder="상품 검색"]'], "field": "상품 검색", "value": "닌텐도 스위치 2", "url": "https://www.danawa.com/", "at": 1.0},
    {"kind": "press", "key": "Enter", "selectors": ['[placeholder="상품 검색"]'], "url": "https://www.danawa.com/", "at": 2.0},
    {"kind": "nav", "url": "https://search.danawa.com/dsearch.php?query=x", "at": 2.5},
    {"kind": "click", "selectors": ['[data-testid="sort-low"]', 'text="낮은 가격순"'], "label": "낮은 가격순", "url": "https://search.danawa.com/dsearch.php?query=x", "at": 5.0},
    {"kind": "nav", "url": "https://search.danawa.com/dsearch.php?query=x&sort=low", "at": 5.5},
]


class _Browser:
    def __init__(self, events, start_url: str = "https://www.danawa.com/") -> None:
        self.events, self.started, self.start_url = events, 0, start_url

    def start_demo(self) -> dict:
        self.started += 1
        return {"action": "demo_started"}

    def stop_demo(self) -> dict:
        return {"events": self.events, "start_url": self.start_url, "secrets_skipped": 1}


class _Runtime:
    _start_demo = JarvisRuntime._start_demo
    _stop_demo = JarvisRuntime._stop_demo

    def __init__(self, events, start_url: str = "https://www.danawa.com/") -> None:
        self.browser = _Browser(events, start_url)


def _ctx(runtime: _Runtime, saved: list) -> SelfContext:
    return SelfContext(
        version=lambda: "x", lang=lambda: "ko", current_eyes=lambda: {}, apply_eyes=lambda on: {}, summary=lambda: {},
        save_recipe=lambda recipe: saved.append(recipe) or {"saved": True, "name": recipe["name"]},
        forget_recipe=lambda name: {"removed": True}, decline_recipe=lambda name: None,
        start_demo=runtime._start_demo, stop_demo=runtime._stop_demo,
    )


def test_learning_by_conversation_from_start_to_save() -> None:
    talk, runtime, saved = SelfTalk(), _Runtime(DEMO_EVENTS), []
    started = talk.intercept("배우기 시작: 다나와 최저가", "s", _ctx(runtime, saved))
    assert started["kind"] == "demo_started" and runtime.browser.started == 1
    ready = talk.intercept("다 했어", "s", _ctx(runtime, saved))
    assert ready["kind"] == "demo_ready" and ready["name"] == "danawa_demo"
    text = ready["answer"]
    assert text.startswith("배운 것: 다나와 최저가 · ") and "확인: 주소가 바뀐다" in text and "「낮은 가격순」 을 누른다" in text
    assert "비밀번호 · 파일 칸 1곳은 적지 않았습니다" in text and text.endswith("(응 / 아니)")
    assert talk.intercept("응", "s", _ctx(runtime, saved))["kind"] == "recipe_saved"
    assert saved[0]["actions"]["from_demo"]["risk"] == "L2" and saved[0]["name"] == "danawa_demo"


def test_done_means_nothing_when_not_learning_and_cancel_throws_it_away() -> None:
    talk, runtime, saved = SelfTalk(), _Runtime(DEMO_EVENTS), []
    assert talk.intercept("다 했어", "s", _ctx(runtime, saved)) is None, "기록 중이 아닐 때의 「다 했어」는 평소 말이다"
    talk.intercept("배우기 시작", "s", _ctx(runtime, saved))
    assert talk.intercept("배우기 취소", "s", _ctx(runtime, saved))["kind"] == "demo_cancelled"
    assert talk.intercept("응", "s", _ctx(runtime, saved)) is None and saved == []


def test_a_demo_that_cannot_become_a_recipe_says_why() -> None:
    talk, saved = SelfTalk(), []
    runtime = _Runtime([{"kind": "click", "selectors": ['text="메뉴"'], "label": "메뉴", "url": "https://a.co.kr/", "at": 1.0}], "https://a.co.kr/")
    talk.intercept("배우기 시작", "s", _ctx(runtime, saved))
    refused = talk.intercept("다 했어", "s", _ctx(runtime, saved))
    assert refused["kind"] == "demo_refused" and "바뀐 것" in refused["answer"]


def test_a_task_request_that_mentions_learning_is_not_taken_over() -> None:
    talk, runtime, saved = SelfTalk(), _Runtime(DEMO_EVENTS), []
    assert talk.intercept("배우기 시작하는 법 알려줘", "s", _ctx(runtime, saved)) is None
    assert runtime.browser.started == 0


def test_the_receipt_for_a_shown_procedure_says_where_it_stopped() -> None:
    ok = [{"tool": "site_run", "ok": True, "arguments": {"site": "danawa_demo"}, "evidence": {"status": "done", "steps": ["a", "b", "c"]}}]
    assert JarvisRuntime._learned_recipe_receipt(ok) == "\n\n— 보여 주신 절차(「danawa」)대로 돌렸습니다 · 확인 모두 ✓"
    stopped = [{"tool": "site_run", "ok": True, "arguments": {"site": "danawa_demo"}, "evidence": {"status": "unverified", "steps": ["a", "b", "c"]}}]
    assert "3번째 걸음에서 멈췄습니다" in JarvisRuntime._learned_recipe_receipt(stopped)


def _badge(page) -> str:
    return page.evaluate("() => (document.getElementById('sonjari-demo-badge') || {}).textContent || ''")


def test_the_red_bar_shows_learning_counts_steps_survives_navigation_and_goes_away(browser_page) -> None:
    """대표(10-20): 「배우는 중인지 아닌지 사용자가 우째 아노 · 손자리는 크롬을 따로 쓰는데」 — 그 창에만 띠, 걸음 수가 오른다."""
    worker, page, _shop = browser_page
    worker._wire_demo()
    assert _badge(page) == "", "기록 전에는 띠가 없다"
    worker._demo.start(page.url)
    worker._demo_badge(True)
    assert "배우는 중 · 0걸음" in _badge(page)
    page.click('[placeholder="상품 검색"]')
    page.keyboard.type("닌텐도")
    page.keyboard.press("Enter")
    page.wait_for_url("**/results.html?q=*")
    page.wait_for_function("() => (document.getElementById('sonjari-demo-badge') || {}).textContent")
    assert "배우는 중 · 2걸음" in _badge(page), "새 페이지에도 띠가 다시 뜨고 채우기 · Enter 두 걸음이 보인다"
    page.click("text=낮은 가격순")
    page.wait_for_url("**sort=low")
    page.wait_for_function("() => ((document.getElementById('sonjari-demo-badge') || {}).textContent || '').includes('3걸음')")
    worker._demo.stop()
    worker._demo_badge(False)
    assert _badge(page) == ""


# ── 막혔을 때 살짝 묻기 ─────────────────────────────────────────────────────────
from alture_jarvis.recipe_from_run import demo_offer_text, stuck_on_a_site  # noqa: E402


def _stuck_trace(host: str = "www.musinsa.com", failures: int = 2, filter_unmet: bool = False) -> dict:
    steps = [{"tool": "browser_open", "ok": True, "evidence": {"url": f"https://{host}/"}}]
    steps += [{"tool": "browser_click", "ok": False, "error": "stale_element_ref", "evidence": {}} for _ in range(failures)]
    plan = {"items": [{"kind": "filter", "met": not filter_unmet}]} if filter_unmet else {"items": []}
    return {"completion_state": "partial", "answer": "못 했습니다", "agent_trace": {"steps": steps, "plan": plan}}


def test_a_run_stuck_on_clicks_names_the_site() -> None:
    assert stuck_on_a_site(_stuck_trace()) == "www.musinsa.com"
    assert stuck_on_a_site(_stuck_trace(failures=0, filter_unmet=True)) == "www.musinsa.com"
    assert stuck_on_a_site(_stuck_trace(failures=1)) == "", "한 번 실패는 막힘이 아니다"
    assert stuck_on_a_site({**_stuck_trace(), "completion_state": "complete"}) == ""
    assert stuck_on_a_site(_stuck_trace(host="127.0.0.1")) == ""
    assert stuck_on_a_site(_stuck_trace(host="www.google.com")) == ""


def test_the_offer_asks_without_moving_any_window() -> None:
    text = demo_offer_text("www.musinsa.com")
    assert "보여 주시겠어요? (응 / 아니)" in text and "앞으로" not in text


def test_yes_to_show_me_starts_learning_and_other_words_do_not() -> None:
    talk, runtime, saved = SelfTalk(), _Runtime(DEMO_EVENTS), []
    talk.offer_demo("s", "www.musinsa.com")
    reply = talk.intercept("응", "s", _ctx(runtime, saved))
    assert reply["kind"] == "demo_started" and runtime.browser.started == 1
    talk2, runtime2 = SelfTalk(), _Runtime(DEMO_EVENTS)
    talk2.offer_demo("s", "www.musinsa.com")
    assert talk2.intercept("다나와에서 마우스 찾아 줘", "s", _ctx(runtime2, saved)) is None
    assert talk2.intercept("응", "s", _ctx(runtime2, saved)) is None and runtime2.browser.started == 0


class _HintBrowser:
    def __init__(self) -> None:
        self.hints: list[tuple[str, str]] = []

    def show_hint(self, host: str, text: str) -> bool:
        self.hints.append((host, text))
        return True


class _OfferRuntime:
    RECIPE_OFFER_MAX = JarvisRuntime.RECIPE_OFFER_MAX
    _recipe_offers_path = JarvisRuntime._recipe_offers_path
    _recipe_offer_book = JarvisRuntime._recipe_offer_book
    _write_recipe_offer_book = JarvisRuntime._write_recipe_offer_book
    _declined_recipe_names = JarvisRuntime._declined_recipe_names
    _count_recipe_offer = JarvisRuntime._count_recipe_offer
    _show_me_offer = JarvisRuntime._show_me_offer

    def __init__(self, tmp_path: Path) -> None:
        from types import SimpleNamespace

        self.browser = _HintBrowser()
        self.config = SimpleNamespace(data_dir=tmp_path)


def test_the_runtime_asks_twice_at_most_and_only_puts_a_quiet_hint_on_the_page(tmp_path: Path) -> None:
    runtime = _OfferRuntime(tmp_path)
    stuck = _stuck_trace()
    trace = {**stuck["agent_trace"], "verification": {"completion_state": "partial"}}
    text, host = runtime._show_me_offer("못 했습니다", trace)
    assert host == "www.musinsa.com" and "보여 주시겠어요?" in text
    assert runtime.browser.hints and runtime.browser.hints[0][0] == "www.musinsa.com"
    runtime._show_me_offer("못 했습니다", trace)
    assert runtime._show_me_offer("못 했습니다", trace) == ("", ""), "같은 사이트는 두 번까지만"


def test_the_hint_never_blocks_clicks(browser_page) -> None:
    from alture_jarvis.recipe_from_run import HINT_JS

    _worker, page, _shop = browser_page
    assert page.evaluate(HINT_JS, "손자리가 여기서 막혔어요")
    style = page.evaluate("() => document.getElementById('sonjari-stuck-hint').getAttribute('style')")
    assert "pointer-events:none" in style
    page.click('[placeholder="상품 검색"]')  # 알림이 있어도 페이지는 그대로 눌린다
