"""`/레시피` — 해 보여서 가르치기 (2026-10-28 대표 결정).

앱 대화창에서 `/레시피`(영어판 `/recipe`) 한 단어를 치면 모델을 부르지 않고 바로 배우기. 배운 뒤에는 저장 전에 **한 번 그대로 돌려 보고**
걸음마다 확인이 맞으면 「검증된 레시피」, 아니면 어디서 틀렸는지 보여 준다. 레시피 파일에는 검증 상태와 쓴 횟수 · 성공 수가 남고,
레시피를 고를 때 검증된 것이 먼저 나온다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.demo_recorder import DemoRecorder, describe_event
from alture_jarvis.recipe_from_run import DraftRefused, demo_recipe, draft_from_run
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.self_talk import SelfContext, SelfTalk
from alture_jarvis.site_recipes import SiteRecipeTools

EVENTS = [
    {"kind": "fill", "selectors": ['[placeholder="상품 검색"]'], "field": "상품 검색", "value": "닌텐도 스위치 2", "url": "https://www.danawa.com/", "at": 1.0},
    {"kind": "press", "key": "Enter", "selectors": ['[placeholder="상품 검색"]'], "url": "https://www.danawa.com/", "at": 2.0},
    {"kind": "nav", "url": "https://search.danawa.com/dsearch.php?query=x", "at": 2.5},
    {"kind": "click", "selectors": ['[data-testid="sort-low"]', 'text="낮은 가격순"'], "label": "낮은 가격순", "url": "https://search.danawa.com/dsearch.php?query=x", "at": 5.0},
    {"kind": "nav", "url": "https://search.danawa.com/dsearch.php?query=x&sort=low", "at": 5.5},
]


class _Browser:
    def __init__(self, events=EVENTS, start_url: str = "https://www.danawa.com/") -> None:
        self.events, self.started, self.start_url = events, 0, start_url

    def start_demo(self) -> dict:
        self.started += 1
        return {"action": "demo_started", "url": self.start_url}

    def stop_demo(self) -> dict:
        return {"events": self.events, "start_url": self.start_url, "secrets_skipped": 0}


class _Runtime:
    _start_demo = JarvisRuntime._start_demo
    _stop_demo = JarvisRuntime._stop_demo

    def __init__(self, events=EVENTS) -> None:
        self.browser = _Browser(events)


class _Rig:
    """대화 한 벌 — 가짜 브라우저 · 돌려 보기 대역 · 저장소 · 화면 알림 기록."""

    def __init__(self, *, replay=None, verdict: dict | None = None, lang: str = "ko", clock=None) -> None:
        self.talk = SelfTalk(clock) if clock else SelfTalk()
        self.runtime = _Runtime()
        self.saved: list[dict] = []
        self.events: list[tuple[str, dict]] = []
        self.replayed: list[dict] = []
        self.verdict = verdict if verdict is not None else {"ok": True, "total": 3, "failed_at": None, "reason": "", "rows": []}
        self.lang = lang
        self.replay_on = True if replay is None else replay

    def _replay(self, recipe: dict) -> dict:
        self.replayed.append(recipe)
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict

    def ctx(self, *, replay: bool | None = None, start: bool = True) -> SelfContext:
        use_replay = self.replay_on if replay is None else replay
        return SelfContext(
            version=lambda: "x", lang=lambda: self.lang, current_eyes=lambda: {}, apply_eyes=lambda on: {}, summary=lambda: {},
            save_recipe=lambda recipe: self.saved.append(recipe) or {"saved": True, "name": recipe["name"]},
            forget_recipe=lambda name: {"removed": True}, decline_recipe=lambda name: None,
            start_demo=self.runtime._start_demo if start else None, stop_demo=self.runtime._stop_demo,
            replay_demo=self._replay if use_replay else None,
            notify=lambda event, payload: self.events.append((event, payload)),
        )

    def say(self, text: str, session: str = "s") -> dict | None:
        return self.talk.intercept(text, session, self.ctx())

    def teach(self, session: str = "s") -> dict:
        assert self.say("/레시피 다나와 최저가", session)["kind"] == "demo_started"
        return self.say("다 했어", session)


# ── 슬래시 문 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("typed", ["/레시피", "/recipe", "/RECIPE", "  /레시피  ", "/레시피 다나와 최저가"])
def test_the_slash_door_starts_learning_without_asking_the_model(typed: str) -> None:
    rig = _Rig()
    reply = rig.say(typed)
    assert reply and reply["kind"] == "demo_started" and rig.runtime.browser.started == 1
    assert [button["say"] for button in reply["buttons"]] == ["다 했어", "배우기 취소"]


def test_the_name_after_the_command_becomes_the_recipe_label_with_its_case() -> None:
    rig = _Rig()
    rig.say("/recipe Danawa Lowest Price")
    rig.say("다 했어")
    assert rig.talk._state("s").demo_pending["recipe"]["actions"]["from_demo"]["description"] == "Danawa Lowest Price"


@pytest.mark.parametrize("typed", ["/레시피를 알려줘", "/레시피를", "레시피 시작", "/recipes", "/레시피쿠팡", "/other", "/"])
def test_a_plain_sentence_that_only_looks_like_the_command_is_not_taken(typed: str) -> None:
    rig = _Rig()
    assert rig.say(typed) is None and rig.runtime.browser.started == 0


def test_without_a_browser_the_slash_door_says_so_instead_of_falling_to_the_model() -> None:
    rig = _Rig()
    reply = rig.talk.intercept("/레시피", "s", rig.ctx(start=False))
    assert reply and reply["kind"] == "demo_unavailable" and "쓸 수 없" in reply["answer"]


def test_asking_again_while_learning_keeps_what_was_recorded() -> None:
    """또 시작하면 기록기가 비워져 지금까지의 걸음이 사라진다 — 시작하지 않고 지금 상태를 말한다."""
    rig = _Rig()
    rig.say("/레시피")
    for again in ("/레시피", "배우기 시작", "/recipe 다른 일"):
        reply = rig.say(again)
        assert reply["kind"] == "demo_already" and "다 했어" in reply["answer"]
    assert rig.runtime.browser.started == 1, "기록기를 다시 시작하지 않았다"
    assert rig.talk.demo_session() == "s"


def test_another_conversation_cannot_restart_the_one_recorder() -> None:
    rig = _Rig()
    rig.say("/레시피", "a")
    reply = rig.say("/레시피", "b")
    assert reply["kind"] == "demo_already" and reply["buttons"] == [] and "다른 대화" in reply["answer"]
    assert rig.runtime.browser.started == 1


def test_the_screen_hears_start_and_end() -> None:
    rig = _Rig()
    rig.say("/레시피 가게")
    assert rig.events[0][0] == "demo_started" and rig.events[0][1]["label"] == "가게"
    rig.say("배우기 취소")
    assert rig.events[-1] == ("demo_ended", {"outcome": "cancelled"})


# ── 저장 전에 한 번 해 보기 ────────────────────────────────────────────────────
def test_after_done_it_lists_what_it_learned_and_offers_to_try_it_once() -> None:
    rig = _Rig()
    ready = rig.teach()
    assert ready["kind"] == "demo_ready" and ready["stage"] == "review"
    assert ready["answer"].startswith("이렇게 배웠습니다.\n배운 것: 다나와 최저가 · ")
    assert "「낮은 가격순」 을 누른다" in ready["answer"] and "확인: 주소가 바뀐다" in ready["answer"]
    assert [button["label"] for button in ready["buttons"]] == ["한 번 해 볼게요", "검증 없이 저장", "버리기"]
    assert rig.saved == [] and rig.replayed == [], "해 보기도 저장도 사람이 고르기 전에는 없다"


def test_a_passing_try_makes_a_verified_recipe_only_when_the_person_says_save() -> None:
    rig = _Rig()
    rig.teach()
    verified = rig.say("한 번 해 볼게요")
    assert verified["kind"] == "demo_verified" and "검증됐습니다" in verified["answer"] and "3개" in verified["answer"]
    assert [button["label"] for button in verified["buttons"]] == ["저장", "버리기"]
    assert rig.saved == [], "검증이 맞아도 저장은 사람의 말 뒤에"
    saved = rig.say("저장")
    assert saved["kind"] == "recipe_saved" and "검증된 레시피로 저장했습니다" in saved["answer"]
    recipe = rig.saved[0]
    assert recipe["verification"]["state"] == "verified" and recipe["verification"]["steps"] == 3
    assert recipe["usage"] == {"runs": 0, "succeeded": 0}


def test_a_failing_try_says_where_it_went_wrong_and_never_saves_on_a_plain_yes() -> None:
    rig = _Rig(verdict={"ok": False, "total": 4, "failed_at": 3, "reason": "기대한 변화가 화면에 나타나지 않았습니다", "rows": []})
    rig.teach()
    failed = rig.say("응")
    assert failed["kind"] == "demo_failed" and "3번째 걸음에서 틀렸습니다" in failed["answer"] and "앞 2걸음은 맞았습니다" in failed["answer"]
    assert [button["label"] for button in failed["buttons"]] == ["다시 보여 주기", "그래도 저장", "버리기"]
    choice = rig.say("응")
    assert choice["kind"] == "demo_choice" and rig.saved == [], "틀린 레시피는 맨 「응」으로 저장하지 않는다"
    saved = rig.say("그래도 저장")
    assert saved["kind"] == "recipe_saved" and "미검증으로 저장했습니다" in saved["answer"]
    assert rig.saved[0]["verification"]["state"] == "unverified" and rig.saved[0]["verification"]["failed_at"] == 3


def test_show_again_after_a_failure_starts_a_fresh_lesson_with_the_same_name() -> None:
    rig = _Rig(verdict={"ok": False, "total": 3, "failed_at": 2, "reason": "x", "rows": []})
    rig.teach()
    rig.say("한 번 해 볼게요")
    again = rig.say("다시 보여 줄게")
    assert again["kind"] == "demo_started" and rig.runtime.browser.started == 2
    assert rig.talk._state("s").demo_label == "다나와 최저가" and not rig.talk._state("s").demo_pending


def test_a_replay_that_blows_up_is_reported_as_wrong_not_swallowed() -> None:
    rig = _Rig(verdict=RuntimeError("browser gone"))
    rig.teach()
    failed = rig.say("한 번 해 볼게요")
    assert failed["kind"] == "demo_failed" and "browser gone" in failed["answer"]


def test_save_without_checking_stays_marked_unverified() -> None:
    rig = _Rig()
    rig.teach()
    saved = rig.say("검증 없이 저장")
    assert saved["kind"] == "recipe_saved" and rig.replayed == []
    assert rig.saved[0]["verification"]["state"] == "unverified" and "미검증으로" in saved["answer"]


def test_discard_throws_the_lesson_away_and_nothing_is_left_to_save() -> None:
    rig = _Rig()
    rig.teach()
    assert rig.say("버려")["kind"] == "demo_discarded"
    assert rig.say("저장") is None and rig.saved == []


def test_an_unrelated_remark_does_not_lose_a_fresh_lesson_but_a_bare_yes_is_no_longer_taken() -> None:
    """방금 가르친 것을 딴소리 한 번에 잃으면 안 된다 — 다만 엉뚱한 대화 끝의 「응」이 크롬을 눌러 돌려 보면 안 된다."""
    rig = _Rig()
    rig.teach()
    assert rig.say("오늘 날씨 어때?") is None
    assert rig.say("응") is None and rig.replayed == [], "맨 「응」은 바로 앞 말이 그 질문일 때만"
    again = rig.say("한 번 해 볼게요")
    assert again["kind"] == "demo_verified", "또렷이 말하면 언제든 받는다"


def test_a_long_remark_also_disarms_the_bare_yes() -> None:
    rig = _Rig()
    rig.teach()
    rig.say("지난주에 시킨 보고서를 다시 정리해서 표로 만들어 주고 요약도 한 줄 붙여 줘")
    assert rig.say("응") is None and rig.replayed == []


def test_a_lesson_waiting_too_long_expires() -> None:
    now = [1000.0]
    rig = _Rig(clock=lambda: now[0])
    rig.teach()
    now[0] += 3 * 60 * 60
    assert rig.say("한 번 해 볼게요") is None and rig.replayed == []


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_every_button_sends_words_the_door_understands(lang: str) -> None:
    """단추는 사람이 친 말과 **같은 문**으로 들어간다 — 단추가 보내는 말을 문이 못 알아들으면 눌러도 아무 일이 없다."""
    def each(make) -> None:
        rig = _Rig(lang=lang, verdict={"ok": False, "total": 3, "failed_at": 2, "reason": "x", "rows": []})
        reply = make(rig)
        assert reply["buttons"], reply["kind"]
        for button in reply["buttons"]:
            fresh = _Rig(lang=lang, verdict=rig.verdict)
            prepared = make(fresh)
            assert fresh.say(button["say"]) is not None, (reply["kind"], button)
            del prepared

    each(lambda rig: rig.say("/recipe x"))
    each(lambda rig: (rig.say("/recipe x"), rig.say("done" if lang == "en" else "다 했어"))[1])
    each(lambda rig: (rig.teach(), rig.say("try it once" if lang == "en" else "한 번 해 볼게요"))[1])
    ok = _Rig(lang=lang)
    ok.teach()
    verified = ok.say("try it once" if lang == "en" else "한 번 해 볼게요")
    for button in verified["buttons"]:
        again = _Rig(lang=lang)
        again.teach()
        again.say("try it once" if lang == "en" else "한 번 해 볼게요")
        assert again.say(button["say"]) is not None, button


def test_without_a_try_hand_the_old_save_question_is_kept() -> None:
    """돌려 볼 손이 없는 문맥(시험 · 크롬이 꺼진 PC)은 예전처럼 곧바로 「저장할까요?」."""
    rig = _Rig(replay=False)
    rig.say("/레시피")
    ready = rig.say("다 했어")
    assert ready["answer"].endswith("(응 / 아니)") and "buttons" not in ready
    assert rig.say("응")["kind"] == "recipe_saved"


def test_a_refused_lesson_offers_to_show_again() -> None:
    rig = _Rig()
    rig.runtime = _Runtime([{"kind": "click", "selectors": ['text="메뉴"'], "label": "메뉴", "url": "https://a.co.kr/", "at": 1.0}])
    rig.runtime.browser.start_url = "https://a.co.kr/"
    rig.say("/레시피")
    refused = rig.say("다 했어")
    assert refused["kind"] == "demo_refused" and "`/레시피`" in refused["answer"]
    assert refused["buttons"][0]["label"] == "다시 보여 주기"
    assert rig.say(refused["buttons"][0]["say"])["kind"] == "demo_started"


# ── 레시피 이름 · 이 PC 주소 ─────────────────────────────────────────────────────
def _draft(url: str = "https://www.danawa.com/", allow_local: bool = False):
    from alture_jarvis.demo_recorder import steps_from_demo

    base = url.rstrip("/")
    events = [{**event, "url": event["url"].replace("https://search.danawa.com", base).replace("https://www.danawa.com", base)}
              if event.get("url") else event for event in EVENTS]
    return draft_from_run("x", steps_from_demo(events, url), allow_local=allow_local)


def test_a_second_lesson_on_the_same_site_does_not_overwrite_the_first() -> None:
    draft = _draft()
    first = demo_recipe(draft, "최저가 보기", {})
    assert first["name"] == "danawa_demo"
    other = demo_recipe(draft, "리뷰 보기", {first["name"]: "최저가 보기"})
    assert other["name"] == "danawa2_demo" and other["name"].endswith("_demo")
    third = demo_recipe(draft, "배송비 보기", {first["name"]: "최저가 보기", other["name"]: "리뷰 보기"})
    assert third["name"] == "danawa3_demo"


def test_showing_the_same_job_again_replaces_the_old_lesson() -> None:
    draft = _draft()
    again = demo_recipe(draft, "최저가 보기", {"danawa_demo": "최저가 보기", "danawa2_demo": "리뷰 보기"})
    assert again["name"] == "danawa_demo"


def test_the_values_shown_are_kept_for_trying_it_again() -> None:
    assert demo_recipe(_draft(), "x", {})["_slots"] == {"query": "닌텐도 스위치 2"}


def test_this_pc_addresses_are_refused_unless_the_test_switch_is_on() -> None:
    with pytest.raises(DraftRefused, match="이 PC"):
        _draft("http://127.0.0.1:8080/")
    local = _draft("http://127.0.0.1:8080/", allow_local=True)
    assert local["name"] == "local" and "127.0.0.1" in local["hosts"]


def test_the_runtime_names_a_new_lesson_around_the_ones_already_saved(tmp_path: Path) -> None:
    class _Fake(_Runtime):
        def __init__(self) -> None:
            super().__init__()
            recipe = demo_recipe(_draft(), "최저가 보기", {})
            self.site_recipes = type("R", (), {"recipes": {"danawa_demo": type("X", (), {"actions": recipe["actions"]})()}})()
            self.audits: list = []
            self.store = type("S", (), {"add_audit": lambda _s, *a: self.audits.append(a)})()

    fake = _Fake()
    out = JarvisRuntime._stop_demo(fake, "리뷰 보기")
    assert out["recipe"]["name"] == "danawa2_demo"
    kinds = fake.audits[0][2]
    assert kinds["kinds"] == {"fill": 1, "press": 1, "nav": 2, "click": 1}, "멈출 때 사건 종류가 남는다(값은 없이)"
    assert "닌텐도" not in json.dumps(fake.audits, ensure_ascii=False)


# ── 기록기: 화면 알림 · 이동 · 띠 단추 ─────────────────────────────────────────
def test_the_recorder_tells_the_screen_each_step_without_the_typed_text() -> None:
    told: list[dict] = []
    recorder = DemoRecorder(clock=lambda: 1.0)
    recorder.listener = told.append
    recorder.start("https://a.kr/")
    recorder.on_event({"kind": "fill", "field": "상품 검색", "value": "비밀스러운 검색어", "url": "https://a.kr/x/y?q=1", "selectors": ["#a"]})
    recorder.on_navigation("https://a.kr/z")
    recorder.on_event({"kind": "click", "label": "로그인", "url": "https://a.kr/z", "selectors": ["#b"]})
    assert [(item["n"], item["kind"], item["name"], item["where"]) for item in told] == [
        (1, "fill", "상품 검색", "a.kr/x/y"), (2, "click", "로그인", "a.kr/z")], "이동은 걸음이 아니라 알리지 않는다"
    assert "비밀스러운" not in json.dumps(told, ensure_ascii=False)
    assert recorder.recent_steps()[-1]["name"] == "로그인" and len(recorder.recent_steps()) == 2


def test_the_page_can_tell_a_new_document_itself_and_it_merges_with_the_python_side() -> None:
    recorder = DemoRecorder(clock=lambda: 2.0)
    recorder.start("https://a.kr/")
    recorder.on_event({"kind": "nav_dom", "url": "https://a.kr/next"})
    recorder.on_navigation("https://a.kr/next")
    assert [event["kind"] for event in recorder.events] == ["nav"], "같은 주소가 두 길로 와도 한 줄"
    recorder.on_event({"kind": "nav_dom", "url": "chrome://newtab"})
    assert len(recorder.events) == 1
    recorder.stop()
    recorder.on_event({"kind": "nav_dom", "url": "https://a.kr/after"})
    assert len(recorder.events) == 1, "멈춘 뒤에는 받지 않는다"


def test_a_press_followed_only_by_a_page_side_nav_still_becomes_a_recipe_step() -> None:
    """운영 크롬에서 press 뒤 이동이 안 적혀 레시피로 못 옮긴 자리(지금판_시험.md ③) — 페이지가 알린 주소만 있어도 확인 조건이 선다."""
    from alture_jarvis.demo_recorder import steps_from_demo

    recorder = DemoRecorder(clock=lambda: 3.0)
    recorder.start("https://ko.wikipedia.org/wiki/대문")
    recorder.on_event({"kind": "fill", "selectors": ['[name="search"]'], "field": "검색", "value": "로봇", "url": "https://ko.wikipedia.org/wiki/대문"})
    recorder.on_event({"kind": "press", "key": "Enter", "selectors": ['[name="search"]'], "field": "검색", "url": "https://ko.wikipedia.org/wiki/대문"})
    recorder.on_event({"kind": "nav_dom", "url": "https://ko.wikipedia.org/wiki/로봇"})
    draft = draft_from_run("위키 검색", steps_from_demo(recorder.stop(), recorder.start_url))
    press = next(step for step in draft["actions"]["from_run"]["steps"] if step["do"] == "press")
    assert press["expect"] == {"kind": "url_changes"}


def test_the_bar_buttons_reach_the_runtime_only_while_recording() -> None:
    heard: list[str] = []
    recorder = DemoRecorder(clock=lambda: 4.0)
    recorder.control_handler = heard.append
    recorder.on_control("stop")
    assert heard == [], "기록 중이 아니면 단추를 받지 않는다"
    recorder.start("https://a.kr/")
    recorder.on_control("stop")
    recorder.on_control("cancel")
    recorder.on_control("rm -rf")
    assert heard == ["stop", "cancel"]
    assert recorder.state()["lang"] == "ko"


def test_describe_event_hides_values() -> None:
    assert describe_event({"kind": "fill", "field": "검색", "value": "비밀", "url": "https://a.kr/"}) == {"kind": "fill", "name": "검색", "where": "a.kr"}


def test_the_bar_button_asks_the_conversation_that_is_learning() -> None:
    class _R:
        _on_demo_control = JarvisRuntime._on_demo_control

        def __init__(self) -> None:
            self.self_talk = SelfTalk()
            self.queued: list[tuple] = []

        def resolve_session_id(self, session: str) -> str:
            return session

        def enqueue(self, kind: str, title: str, payload: dict) -> dict:
            self.queued.append((kind, title, payload))
            return {"id": "j"}

    runtime = _R()
    runtime._on_demo_control("stop")
    assert runtime.queued == [], "배우는 대화가 없으면 아무 일도 안 한다"
    runtime.self_talk._state("room-1").demo_label = "가게"
    runtime._on_demo_control("stop")
    runtime._on_demo_control("cancel")
    runtime._on_demo_control("other")
    assert [(kind, title, payload["prompt"], payload["session_id"], payload["origin"]) for kind, title, payload in runtime.queued] == [
        ("chat", "다 했어", "다 했어", "room-1", "workspace"), ("chat", "배우기 취소", "배우기 취소", "room-1", "workspace")]


def test_the_screen_can_ask_where_the_lesson_stands() -> None:
    class _R:
        demo_state = JarvisRuntime.demo_state

        def __init__(self) -> None:
            self.self_talk = SelfTalk()
            self.browser = type("B", (), {"_demo": DemoRecorder(clock=lambda: 1.0)})()

    runtime = _R()
    assert runtime.demo_state() == {"on": False, "label": "", "steps": []}
    runtime.self_talk._state("room").demo_label = "가게"
    runtime.browser._demo.start("https://a.kr/")
    runtime.browser._demo.on_event({"kind": "click", "label": "담기", "url": "https://a.kr/p", "selectors": ["#x"]})
    state = runtime.demo_state()
    assert state["on"] and state["label"] == "가게" and state["steps"] == [{"n": 1, "kind": "click", "name": "담기", "where": "a.kr/p"}]


# ── 저장 전 돌려 보기 · 검증 상태 · 쓴 횟수 · 순서 ─────────────────────────────────
class FakeWorker:
    def __init__(self, *, verified: Any = True, fail_find: str = "") -> None:
        self.calls: list[tuple[str, dict]] = []
        self.verified, self.fail_find = verified, fail_find

    def execute(self, action: str, arguments: dict | None = None) -> dict:
        arguments = dict(arguments or {})
        self.calls.append((action, arguments))
        if action == "browser_open":
            return {"url": arguments.get("url", "")}
        if action == "browser_find_selector":
            if self.fail_find and self.fail_find in arguments["selectors"][0]:
                raise RuntimeError("selector_not_found")
            return {"ref": "j9", "selector": arguments["selectors"][0], "frame": "main"}
        if action in {"browser_click", "browser_press"}:
            result: dict[str, Any] = {"verification": {"status": "verified" if self.verified else "unknown", "evidence": "url:a->b"}}
            if self.verified is not None:
                result["verified"] = self.verified
            return result
        if action == "browser_dismiss_dialog":
            return {"dialog_count": 0}
        return {}

    execute_trusted = execute


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                        documents_dir=tmp_path / "docs", site_recipe_dir=tmp_path / "builtin")


def _lesson(name_label: str = "최저가 보기") -> dict:
    return demo_recipe(_draft(), name_label, {})


def test_replay_reports_every_step_and_is_verified_only_when_all_checks_pass(tmp_path: Path) -> None:
    worker = FakeWorker(verified=True)
    tools = SiteRecipeTools(_config(tmp_path), worker)
    told: list[dict] = []
    result = tools.replay_unsaved(_lesson(), progress=told.append)
    assert result["ok"] and result["total"] == 4 and result["failed_at"] is None
    assert [row["ok"] for row in result["rows"]] == [True, True, True, True]
    assert [(row["n"], row["ok"]) for row in told] == [(1, None), (1, True), (2, None), (2, True), (3, None), (3, True), (4, None), (4, True)]
    opens = [args["url"] for action, args in worker.calls if action == "browser_open"]
    assert opens == ["https://www.danawa.com/"]
    fills = [args["value"] for action, args in worker.calls if action == "browser_fill"]
    assert fills == ["닌텐도 스위치 2"], "보여 주신 그 말로 다시 해 본다"


@pytest.mark.parametrize("verified, expected", [(False, "기대한 변화가 화면에 나타나지 않았습니다"), (None, "확인 결과를 읽지 못했습니다")])
def test_a_check_that_failed_or_could_not_be_read_is_not_a_pass(tmp_path: Path, verified: Any, expected: str) -> None:
    tools = SiteRecipeTools(_config(tmp_path), FakeWorker(verified=verified))
    result = tools.replay_unsaved(_lesson())
    assert not result["ok"] and result["failed_at"] == 3 and expected in result["reason"]
    assert len(result["rows"]) == 3, "첫 틀린 걸음에서 멈춘다"


def test_a_missing_element_stops_the_replay_and_names_the_step(tmp_path: Path) -> None:
    tools = SiteRecipeTools(_config(tmp_path), FakeWorker(fail_find="sort-low"))
    result = tools.replay_unsaved(_lesson())
    assert not result["ok"] and result["failed_at"] == 4 and "selector_not_found" in result["reason"]
    assert "낮은 가격순" in result["rows"][-1]["text"]


def test_the_replay_cannot_leave_the_hosts_the_recipe_declared(tmp_path: Path) -> None:
    lesson = _lesson()
    lesson["actions"]["from_demo"]["steps"][0]["url"] = "https://evil.example.org/"
    tools = SiteRecipeTools(_config(tmp_path), FakeWorker())
    result = tools.replay_unsaved(lesson)
    assert not result["ok"] and result["failed_at"] == 1 and "허용되지 않은 주소" in result["reason"]


def test_saved_lessons_count_their_runs_and_listing_puts_verified_first(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tools = SiteRecipeTools(config, FakeWorker())
    good, shaky = _lesson("검증된 일"), _lesson("미검증 일")
    good["name"], shaky["name"] = "zzz_demo", "aaa_demo"  # 이름 순서로는 미검증이 앞이다
    good["verification"] = {"state": "verified", "checked_at": 1.0, "steps": 4}
    shaky["verification"] = {"state": "unverified", "checked_at": 0, "steps": 0, "reason": "not_tried"}
    for lesson in (good, shaky):
        tools.save_learned({**lesson, "usage": {"runs": 0, "succeeded": 0}})
    listing = tools.list_actions()["sites"]
    assert [site["site"] for site in listing] == ["zzz_demo", "aaa_demo"], "검증된 것이 먼저"
    assert listing[0]["verification"] == "verified" and listing[1]["verification"] == "unverified"
    described = "".join(item["function"].get("description", "") for item in tools.ollama_tools if item["function"]["name"] == "site_run")
    assert described.index("zzz_demo") < described.index("aaa_demo") and "aaa_demo(from_demo) [미검증]" in described

    assert tools.run({"site": "zzz_demo", "action": "from_demo", "params": {"query": "x"}})["status"] == "done"
    tools.worker.verified = False
    assert tools.run({"site": "zzz_demo", "action": "from_demo", "params": {"query": "x"}})["status"] == "unverified"
    stored = json.loads((config.user_recipes_dir / "zzz_demo.json").read_text(encoding="utf-8"))
    assert stored["usage"]["runs"] == 2 and stored["usage"]["succeeded"] == 1 and stored["usage"]["last_at"] > 0
    assert stored["verification"]["state"] == "verified", "쓴 횟수만 센다 — 검증 상태는 사람이 다시 해 볼 때만 바뀐다"
    assert tools.list_actions()["sites"][0]["usage"] == {"runs": 2, "succeeded": 1}


def test_reviewed_recipes_that_ship_with_sonjari_are_never_written_to(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    data = {"name": "shop", "hosts": ["a.test"], "urls": {"home": "https://a.test/"}, "targets": {},
            "actions": {"look": {"risk": "L0", "steps": [{"do": "open", "url_key": "home"}]}}}
    path = builtin / "shop.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    tools = SiteRecipeTools(_config(tmp_path), FakeWorker())
    assert tools.run({"site": "shop", "action": "look"})["status"] == "done"
    assert path.read_text(encoding="utf-8") == before
    assert tools.recipes["shop"].rank == 0 and "verification" not in tools.list_actions()["sites"][0]
