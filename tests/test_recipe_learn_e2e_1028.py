"""`/레시피` 끝에서 끝까지 — 진짜 크로미움 (2026-10-28).

시험 가게(이 PC 의 정적 페이지)에서 **사람 손처럼**(Playwright 의 실제 입력) 치고 누른 것을 → 배우기 → 한 번 그대로 돌려 보기(진짜 레시피 엔진 ·
진짜 브라우저 일꾼 스레드) → 저장 → 저장한 레시피로 다시 돌리기까지. 운영 크롬(9222)에는 붙지 않는다 — 시험이 직접 띄운 헤드리스 크로미움이다.

일꾼(`BrowserWorker`)의 Playwright 는 **자기 스레드**에서 만든 것이어야 한다(다른 스레드에서 만든 페이지를 일꾼이 만지면 greenlet 오류).
그래서 크로미움도 사람 동작도 `worker._submit` 으로 일꾼 스레드 안에서 한다.
"""

from __future__ import annotations

import http.server
import json
import threading
from functools import partial
from pathlib import Path

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.self_talk import SelfContext, SelfTalk
from alture_jarvis.site_recipes import SiteRecipeTools

HOME = """<html><head><meta charset="utf-8"><title>가게</title></head><body>
<form action="/results.html"><input name="q" placeholder="상품 검색" data-jarvis-ref="j1"></form>
<a href="/plain.html" data-jarvis-ref="j2">그냥 링크</a>
<input type="password" name="pw" placeholder="비밀번호">
</body></html>"""
RESULTS = """<html><head><meta charset="utf-8"><title>결과</title></head><body>
<a href="/results.html?sort=low" data-testid="sort-low">낮은 가격순</a></body></html>"""


@pytest.fixture()
def shop(tmp_path: Path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text(HOME, encoding="utf-8")
    (tmp_path / "site" / "results.html").write_text(RESULTS, encoding="utf-8")
    (tmp_path / "site" / "plain.html").write_text("<html><body>끝</body></html>", encoding="utf-8")
    (tmp_path / "site" / "form.html").write_text(
        '<html><head><meta charset="utf-8"></head><body><form action="/results.html">'
        '<input name="q" placeholder="위키 검색"><button type="submit">검색</button></form></body></html>', encoding="utf-8")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:  # noqa: D401
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(tmp_path / "site")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


@pytest.fixture()
def worker(tmp_path: Path):
    sync_api = pytest.importorskip("playwright.sync_api")
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o",
                          documents_dir=tmp_path / "docs", site_recipe_dir=tmp_path / "builtin",
                          browser_read_only=False, demo_allow_local=True)
    browser_worker = BrowserWorker(config)
    held: dict = {}

    def boot() -> None:
        playwright = sync_api.sync_playwright().start()
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception:
            playwright.stop()
            raise
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(5000)
        browser_worker._context, browser_worker._page = context, page
        held.update(playwright=playwright, browser=browser)

    try:
        browser_worker._submit(boot, 60, operation="test_boot")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"chromium not usable: {exc}")
    try:
        yield browser_worker
    finally:
        def shut() -> None:
            held["browser"].close()
            held["playwright"].stop()

        try:
            browser_worker._submit(shut, 30, operation="test_shutdown")
        except Exception:  # noqa: BLE001
            pass


def _on_worker(worker: BrowserWorker, function) -> None:
    worker._submit(function, 60, operation="test_human")


def _person_searches_and_sorts(worker: BrowserWorker, shop: str) -> None:
    """사람 손: 가게를 열고 · 검색칸에 치고 Enter · 낮은 가격순을 누른다. 비밀번호 칸도 만진다(기록되면 안 된다)."""
    def act() -> None:
        page = worker._current_page()
        page.goto(shop + "/index.html")
        page.click('[placeholder="비밀번호"]')
        page.keyboard.type("hunter2")
        page.click('[placeholder="상품 검색"]')
        page.keyboard.type("닌텐도 스위치 2")
        page.keyboard.press("Enter")
        page.wait_for_url("**/results.html?q=*")
        page.click("text=낮은 가격순")
        page.wait_for_url("**sort=low")
        page.wait_for_timeout(300)

    _on_worker(worker, act)


class _Home:
    """대화 한 벌에 붙는 진짜 부품들 — 운영 본체의 같은 함수로 시작 · 끝 · 돌려 보기를 한다."""

    _start_demo = JarvisRuntime._start_demo
    _stop_demo = JarvisRuntime._stop_demo
    _replay_demo = JarvisRuntime._replay_demo
    _wire_demo_recorder = JarvisRuntime._wire_demo_recorder
    _demo_notify = JarvisRuntime._demo_notify
    _on_demo_control = JarvisRuntime._on_demo_control

    def resolve_session_id(self, session: str) -> str:
        return session

    def enqueue(self, kind: str, title: str, payload: dict) -> dict:
        self.queued.append((kind, title, payload["prompt"]))
        return {"id": "j"}

    def __init__(self, worker: BrowserWorker, config: JarvisConfig) -> None:
        self.browser = worker
        self.config = config
        self.site_recipes = SiteRecipeTools(config, worker)
        self.heard: list[tuple[str, dict]] = []
        self.audits: list = []
        self.queued: list = []
        self.store = type("S", (), {"add_audit": lambda _s, *args: self.audits.append(args)})()
        self.events = type("E", (), {"publish": lambda _e, name, payload: self.heard.append((name, payload))})()
        self.self_talk = SelfTalk()

    def ctx(self) -> SelfContext:
        return SelfContext(
            version=lambda: "x", lang=lambda: "ko", current_eyes=lambda: {}, apply_eyes=lambda on: {}, summary=lambda: {},
            save_recipe=self.site_recipes.save_learned, forget_recipe=self.site_recipes.forget_learned, decline_recipe=lambda name: None,
            start_demo=self._start_demo, stop_demo=self._stop_demo, replay_demo=self._replay_demo, notify=self._demo_notify,
        )

    def say(self, text: str) -> dict:
        reply = self.self_talk.intercept(text, "room", self.ctx())
        assert reply is not None, f"문이 못 알아들은 말: {text}"
        return reply


def test_taught_by_hand_tried_once_saved_and_run_again(worker: BrowserWorker, shop: str, tmp_path: Path) -> None:
    home = _Home(worker, worker.config)
    started = home.say("/레시피 가게 최저가")
    assert started["kind"] == "demo_started", started
    assert home.heard[0][0] == "demo_started" and home.heard[0][1]["label"] == "가게 최저가"

    _person_searches_and_sorts(worker, shop)

    steps_told = [payload for name, payload in home.heard if name == "demo_step"]
    assert [item["kind"] for item in steps_told] == ["fill", "press", "click"], "비밀번호 칸은 센 수만 남고 걸음으로 안 적힌다"
    assert [item["n"] for item in steps_told] == [1, 2, 3]
    assert "닌텐도" not in json.dumps(steps_told, ensure_ascii=False) and "hunter2" not in json.dumps(steps_told)

    ready = home.say("다 했어")
    assert ready["kind"] == "demo_ready" and ready["stage"] == "review"
    assert "비밀번호 · 파일 칸 1곳은 적지 않았습니다" in ready["answer"] and "hunter2" not in ready["answer"]
    assert "「낮은 가격순」 을 누른다" in ready["answer"]
    recorded_kinds = home.audits[0][2]["kinds"]
    assert recorded_kinds.get("nav", 0) >= 2, "누른 뒤의 이동도 적혔다"

    # 한 번 그대로 돌려 본다 — 다른 화면에서 시작해도 레시피가 스스로 가게를 열고 같은 말을 넣는다.
    _on_worker(worker, lambda: worker._current_page().goto("about:blank"))
    verified = home.say("한 번 해 볼게요")
    assert verified["kind"] == "demo_verified", verified["answer"]
    assert "걸음 4개를 그대로 돌렸고 확인이 모두 맞았습니다" in verified["answer"]
    names = [name for name, _ in home.heard]
    assert names.count("demo_replay_started") == 1 and names[-1] == "demo_replay_done"
    steps = [payload for name, payload in home.heard if name == "demo_replay_step"]
    assert [step["ok"] for step in steps if step["ok"] is not None] == [True, True, True, True]
    assert worker._page.url.endswith("sort=low"), "돌려 본 끝 화면"

    saved = home.say("저장")
    assert saved["kind"] == "recipe_saved" and "검증된 레시피로 저장했습니다" in saved["answer"]
    path = Path(saved["path"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["verification"]["state"] == "verified" and stored["usage"] == {"runs": 0, "succeeded": 0}
    assert "hunter2" not in path.read_text(encoding="utf-8")

    # 저장한 레시피로 같은 일을 다시 — 레시피 엔진(site_run)이 그대로 돈다.
    name = stored["name"]
    _on_worker(worker, lambda: worker._current_page().goto("about:blank"))
    outcome = home.site_recipes.run({"site": name, "action": "from_demo", "params": {"query": "마우스"}})
    assert outcome["status"] == "done" and len(outcome["steps"]) == 5  # 열기 · 쿠키 창 치우기 · 입력 · Enter · 누르기
    assert "q=%EB%A7%88%EC%9A%B0%EC%8A%A4" in worker._page.url or "sort=low" in worker._page.url
    again = json.loads(path.read_text(encoding="utf-8"))
    assert again["usage"]["runs"] == 1 and again["usage"]["succeeded"] == 1


def test_when_the_page_changes_after_teaching_the_try_says_which_step_broke(worker: BrowserWorker, shop: str, tmp_path: Path) -> None:
    home = _Home(worker, worker.config)
    home.say("/레시피")
    _person_searches_and_sorts(worker, shop)
    home.say("다 했어")
    # 가게가 바뀌었다 — 「낮은 가격순」 링크가 사라진 결과 화면.
    (tmp_path / "site" / "results.html").write_text("<html><head><meta charset='utf-8'></head><body>비었음</body></html>", encoding="utf-8")
    failed = home.say("한 번 해 볼게요")
    assert failed["kind"] == "demo_failed" and "4번째 걸음에서 틀렸습니다" in failed["answer"]
    assert [button["label"] for button in failed["buttons"]] == ["다시 보여 주기", "그래도 저장", "버리기"]
    assert home.say("응")["kind"] == "demo_choice"
    saved = home.say("그래도 저장")
    stored = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))
    assert stored["verification"]["state"] == "unverified" and stored["verification"]["failed_at"] == 4


# ── 키 누르기의 확인 조건 · 띠 단추 ────────────────────────────────────────────────
def test_a_key_press_checks_its_expectation_like_a_click(worker: BrowserWorker, shop: str) -> None:
    def act() -> dict:
        page = worker._current_page()
        page.goto(shop + "/index.html")
        page.fill('[placeholder="상품 검색"]', "마우스")
        moved = worker._press(page, {"ref": "j1", "key": "Enter", "expect": {"kind": "url_changes"}})
        page.goto(shop + "/index.html")
        still = worker._press(page, {"ref": "j2", "key": "Shift", "expect": {"kind": "url_changes"}, "verify_timeout_ms": 600})
        page.goto(shop + "/index.html")
        plain = worker._press(page, {"ref": "j1", "key": "a"})
        return {"moved": moved, "still": still, "plain": plain}

    out = worker._submit(act, 60, operation="test_press")
    assert out["moved"]["verified"] is True
    assert out["still"]["verified"] is False, "아무 일도 안 일어난 키 누르기를 맞다고 하지 않는다"
    assert "verified" not in out["plain"], "expect 를 안 주면 예전 그대로"


def test_the_bar_buttons_reach_the_runtime_and_are_not_recorded_as_steps(worker: BrowserWorker, shop: str) -> None:
    heard: list[str] = []

    def act() -> dict:
        page = worker._current_page()
        page.goto(shop + "/index.html")
        worker._wire_demo()
        worker._demo.control_handler = heard.append
        worker._demo.lang = "ko"
        worker._demo.start(page.url)
        worker._demo_badge(True)
        page.wait_for_timeout(200)
        texts = page.evaluate("() => Array.from(document.querySelectorAll('#sonjari-demo-badge button')).map(b => b.textContent)")
        style = page.evaluate("() => document.getElementById('sonjari-demo-badge').getAttribute('style')")
        page.click('#sonjari-demo-badge [data-role="done"]')
        page.click('#sonjari-demo-badge [data-role="cancel"]')
        page.click('[placeholder="상품 검색"]')  # 띠가 있어도 아래 페이지는 그대로 눌린다
        page.wait_for_timeout(300)
        events = worker._demo.stop()
        worker._demo_badge(False)
        return {"texts": texts, "style": style, "events": events,
                "gone": page.evaluate("() => !document.getElementById('sonjari-demo-badge')")}

    out = worker._submit(act, 60, operation="test_bar")
    assert out["texts"] == ["다 했어", "취소"] and "pointer-events:none" in out["style"]
    assert heard == ["stop", "cancel"]
    assert out["events"] == [], "띠 단추를 누른 것은 걸음이 아니다(검색칸을 누른 것도 걸음이 아니다)"
    assert out["gone"]


def test_the_bar_speaks_english_when_the_app_does(worker: BrowserWorker, shop: str) -> None:
    def act() -> str:
        page = worker._current_page()
        page.goto(shop + "/index.html")
        worker._wire_demo()
        worker._demo.lang = "en"
        worker._demo.start(page.url)
        worker._demo_badge(True)
        page.wait_for_timeout(200)
        text = page.evaluate("() => document.getElementById('sonjari-demo-badge').textContent")
        worker._demo.stop()
        worker._demo_badge(False)
        return text

    text = worker._submit(act, 60, operation="test_bar_en")
    assert "Sonjari is learning" in text and "Done" in text and "Cancel" in text


def test_enter_in_a_form_field_is_one_step_not_enter_plus_a_phantom_click_on_the_submit_button(worker: BrowserWorker, shop: str) -> None:
    """칸에서 Enter 를 치면 브라우저가 제출 단추에 스스로 누르기를 한 번 더 보낸다(암묵적 제출). 운영 위키 시험에서 이것이 걸음으로 적혀
    Enter 바로 뒤에 이동이 없어 레시피로 못 옮겼다 — 사건 순서 nav · fill · press · click · nav. 사람이 진짜 마우스로 단추를 누른 것은 그대로 적는다."""
    def act() -> dict:
        page = worker._current_page()
        worker._wire_demo()
        page.goto(shop + "/form.html")
        worker._demo.start(page.url)
        page.fill('[placeholder="위키 검색"]', "로봇")
        page.press('[placeholder="위키 검색"]', "Enter")
        page.wait_for_url("**/results.html?q=*")
        page.wait_for_timeout(300)
        by_enter = [event["kind"] for event in worker._demo.stop()]
        page.goto(shop + "/form.html")
        worker._demo.start(page.url)
        page.fill('[placeholder="위키 검색"]', "로봇")
        page.click("button")  # 진짜 마우스로 단추를 누른다
        page.wait_for_url("**/results.html?q=*")
        page.wait_for_timeout(300)
        by_mouse = [event["kind"] for event in worker._demo.stop()]
        return {"by_enter": by_enter, "by_mouse": by_mouse}

    out = worker._submit(act, 60, operation="test_implicit_submit")
    assert out["by_enter"] == ["fill", "press", "nav"], out
    assert out["by_mouse"] == ["fill", "click", "nav"], out
