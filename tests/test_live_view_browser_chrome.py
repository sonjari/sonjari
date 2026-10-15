"""브라우저 무대 3차 — 평소 쓰던 브라우저처럼(주소창·뒤로/앞으로·탭·고르기 상자·알림창·파일 고르기, 2026-09-26).

진짜 크롬 E2E 는 시험용 온텔릭으로 따로 돌렸다(인수인계 「09-26」). 여기서는 규칙을 못 박는다.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.live_view import LiveView, normalize_address


class _Recorder:
    """`_send` 대역 — 보낸 것을 적고, 물어본 것에는 정해 둔 답을 준다."""

    def __init__(self, answers: dict[str, dict] | None = None) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.answers = answers or {}

    def __call__(self, method, params=None, **_kwargs):
        self.sent.append((method, params or {}))
        return self.answers.get(method)


def _view(answers: dict[str, dict] | None = None) -> tuple[LiveView, _Recorder]:
    worker = SimpleNamespace(_connected=True, _page=None, _cdp_port_in_use=9222,
                             config=SimpleNamespace(browser_cdp_port=9222), _human_took_over=None)
    view = LiveView(worker)
    view._watch = lambda: None  # type: ignore[method-assign]
    recorder = _Recorder(answers)
    view._send = recorder  # type: ignore[method-assign]
    view._ws = object()  # 연결된 무대
    view._frame = {"seq": 1, "jpeg": b"x", "css_width": 1280.0, "css_height": 800.0}
    return view, recorder


def test_the_address_bar_opens_addresses_and_searches_everything_else():
    assert normalize_address("danawa.com") == "https://danawa.com"
    assert normalize_address("https://www.naver.com/") == "https://www.naver.com/"
    assert normalize_address("부산 날씨").startswith("https://search.naver.com/search.naver?query=")
    assert normalize_address("   ") == ""


def test_the_address_bar_is_never_a_script_door():
    """주소창이 `javascript:`·`file:` 을 열면 스크립트 실행·로컬 파일 열람 문이 된다 — 검색어로 본다."""
    for risky in ("javascript:alert(1)", "file:///C:/Windows/win.ini", "chrome://settings"):
        assert normalize_address(risky).startswith("https://search.naver.com/"), risky


def test_back_uses_the_real_history_entry_and_takes_control():
    view, sent = _view({"Page.getNavigationHistory": {"currentIndex": 2, "entries": [
        {"id": 11, "url": "https://a", "title": "A"}, {"id": 12, "url": "https://b", "title": "B"},
        {"id": 13, "url": "https://c", "title": "C"}]}})
    assert view.navigate("back")["ok"]
    assert ("Page.navigateToHistoryEntry", {"entryId": 12}) in sent.sent
    assert view.human_in_control(), "버튼을 누르는 것도 넘겨받기다"
    assert not view.navigate("forward")["ok"], "맨 끝에서 앞으로는 없다"


def test_reload_and_go():
    view, sent = _view()
    view.navigate("reload")
    view.navigate("go", "danawa.com")
    methods = [method for method, _ in sent.sent]
    assert "Page.reload" in methods
    assert ("Page.navigate", {"url": "https://danawa.com"}) in sent.sent


def test_a_dialog_is_shown_only_while_a_human_holds_the_browser():
    """온텔릭이 일하는 중의 알림창은 온텔릭 규칙(기본 취소)이 답한다 — 무대에 그리면 사람이 헛눌린다."""
    view, _ = _view()
    view._on_page_event("Page.javascriptDialogOpening", {"type": "confirm", "message": "정말 삭제하시겠습니까?"})
    assert view.nav_state()["dialog"] is None
    view.take_control()
    assert view.nav_state()["dialog"]["message"] == "정말 삭제하시겠습니까?"


def test_answering_the_dialog_goes_to_chrome():
    view, sent = _view()
    view.take_control()
    view._on_page_event("Page.javascriptDialogOpening", {"type": "prompt", "message": "이름?", "defaultPrompt": ""})
    assert view.answer_dialog(True, "박가람")["ok"]
    assert ("Page.handleJavaScriptDialog", {"accept": True, "promptText": "박가람"}) in sent.sent
    assert view.nav_state()["dialog"] is None


def test_handing_back_never_leaves_a_dialog_hanging():
    """사람이 답 안 한 알림창을 두고 돌려주면 페이지가 멈추고 온텔릭 다음 걸음이 매달린다 — 취소로 닫는다."""
    view, sent = _view()
    view.take_control()
    view._on_page_event("Page.javascriptDialogOpening", {"type": "confirm", "message": "나갈까요?"})
    view.release_control("button")
    assert ("Page.handleJavaScriptDialog", {"accept": False}) in sent.sent


def test_the_agents_dialog_handler_leaves_it_to_the_human_while_they_hold_the_browser():
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._dialog_policy = None
    view, _ = _view()
    worker.live_view = view
    view.take_control()
    handlers = []
    page = SimpleNamespace(on=lambda _name, handler: handlers.append(handler))
    worker._watch_dialogs(page)
    answered = []
    dialog = SimpleNamespace(message="정말?", type="confirm", accept=lambda *_: answered.append("accept"),
                             dismiss=lambda: answered.append("dismiss"))
    handlers[0](dialog)
    assert answered == [], "사람이 쥔 동안 온텔릭이 알림창에 답했다"
    assert worker._last_dialog["left_to_human"] is True


def test_a_click_on_a_select_box_returns_its_options_instead_of_clicking():
    options = {"options": [{"text": "인기순", "disabled": False}, {"text": "낮은 가격순", "disabled": False}],
               "selected": 0, "rect": {"x": 640, "y": 200, "w": 128, "h": 40}}
    view, sent = _view({"Runtime.evaluate": {"result": {"value": json.dumps(options)}}})
    result = view.input({"kind": "mouse", "type": "down", "x": 0.5, "y": 0.25, "button": "left", "clickCount": 1})
    assert result["select"]["options"][1]["text"] == "낮은 가격순"
    assert result["select"]["rect"] == {"x": 0.5, "y": 0.25, "w": 0.1, "h": 0.05}
    assert not any(method == "Input.dispatchMouseEvent" for method, _ in sent.sent), "크롬의 목록 창을 열면 화면 밖에 떠서 안 보인다"


def test_picking_an_option_sets_the_page_value():
    view, sent = _view({"Runtime.evaluate": {"result": {"value": True}}})
    assert view.input({"kind": "select", "index": 1})["ok"]
    script = next(params["expression"] for method, params in sent.sent if method == "Runtime.evaluate")
    assert "selectedIndex = 1" in script and "'change'" in script


def test_file_upload_uses_the_files_the_human_picked():
    view, sent = _view({"DOM.setFileInputFiles": {}})
    view._on_page_event("Page.fileChooserOpened", {"mode": "selectSingle", "backendNodeId": 42})
    assert view.nav_state()["file_chooser"] is None, "넘겨받기 전에는 무대에 안 그린다"
    view.take_control()
    assert view.nav_state()["file_chooser"]["mode"] == "selectSingle"
    assert view.set_files(["C:/a.pdf", "C:/b.pdf"])["count"] == 1, "하나만 받는 칸에 둘을 넣지 않는다"
    assert ("DOM.setFileInputFiles", {"files": ["C:/a.pdf"], "backendNodeId": 42}) in sent.sent


def test_switching_tabs_follows_the_human_and_handing_back_returns_to_the_agents_tab():
    view, sent = _view()
    view._tabs = [{"id": "A", "title": "다나와", "url": "https://a", "agent": True},
                  {"id": "B", "title": "상세", "url": "https://b", "agent": False}]
    assert view.switch_tab("B")["ok"]
    assert ("Target.activateTarget", {"targetId": "B"}) in sent.sent
    assert view._view_override == "B"
    view.release_control("button")
    assert view._view_override == "", "돌려주면 온텔릭이 일하는 탭을 다시 본다"
    assert not view.switch_tab("Z")["ok"]


def test_every_new_endpoint_is_behind_the_token():
    from pathlib import Path

    api = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "api.py").read_text(encoding="utf-8")
    for path in ("/v1/browser/live/state", "/v1/browser/live/nav", "/v1/browser/live/tab",
                 "/v1/browser/live/dialog", "/v1/browser/live/files"):
        line = next(row for row in api.splitlines() if f'"{path}"' in row)
        assert "require_token" in line, path


def test_page_events_keep_the_address_and_loading_bar_honest():
    view, _ = _view()
    view._on_page_event("Page.frameNavigated", {"frame": {"id": "main", "url": "https://prod.danawa.com/info"}})
    view._on_page_event("Page.frameStartedLoading", {"frameId": "child"})
    assert view.nav_state()["loading"] is False, "하위 프레임 로딩으로 막대가 돌면 안 된다"
    view._on_page_event("Page.frameStartedLoading", {"frameId": "main"})
    assert view.nav_state()["loading"] is True
    view._on_page_event("Page.frameStoppedLoading", {"frameId": "main"})
    state = view.nav_state()
    assert state["loading"] is False and state["url"] == "https://prod.danawa.com/info"
    assert time.time() > 0


def test_clicks_are_measured_against_the_picture_the_human_saw():
    """창 크기가 바뀌는 사이에는 화면의 그림(옛 크기)과 마지막 장(새 크기)이 다르다 — 사람이 본 그림의 크기로 잰다."""
    view, sent = _view()
    view._frame = {"seq": 9, "jpeg": b"x", "css_width": 1280.0, "css_height": 905.0}
    view.input({"kind": "mouse", "type": "move", "x": 0.5, "y": 0.5, "button": "none", "fw": 1280, "fh": 752})
    _, params = sent.sent[-1]
    assert params["y"] == 376, "옛 그림(752) 기준 가운데여야 한다"


def test_handing_back_after_switching_tabs_brings_the_agents_tab_to_the_front():
    """앞 탭만 창 크기를 따라간다 — 온텔릭 탭을 뒤에 두면 크기가 안 맞아 무대 좌표가 어긋났다(E2E)."""
    view, sent = _view()
    view._tabs = [{"id": "A", "title": "다나와", "url": "https://a", "agent": True},
                  {"id": "B", "title": "상세", "url": "https://b", "agent": False}]
    view.switch_tab("B")
    view.release_control("button")
    assert sent.sent[-1] == ("Target.activateTarget", {"targetId": "A"})
