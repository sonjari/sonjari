"""폼을 다루는 화면에서 브라우저 도구가 넘어진 다섯 자리 (2026-10-07 대표 실사용 · 진짜 크로미움 + 가짜).

채용 사이트 이력서를 고치던 한 시간에 나온 것들이다. 모델 둘(35B·26B)이 같은 자리에서 넘어졌다 — 도구 쪽이었다.

1. 「이력서 100% 완성」은 새 탭으로 열린다. 기다리는 고리가 `time.sleep` 이라 그 탭을 끝내 못 봤다.
2. `text_appears` 는 누르기 전부터 있던 글이면 무조건 「검증됨」이었다.
3. 찾기는 200개만 훑었다 — 요소 1,266개인 화면의 맨 아래 「자기소개서」를 「없다」고 했다.
4. 사이트 검색이 폼의 **학교 이름 칸**을 검색칸으로 골라 회사 이름을 쳐 넣었다.
5. 저장 안 된 입력이 있는 탭에서는 모든 이동이 `ERR_ABORTED` 였다(나가기 확인창을 우리가 취소로 닫았다).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

from alture_jarvis import browser as browser_module
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

playwright_api = pytest.importorskip("playwright.sync_api")

_ROWS = "".join(
    f"<div><input type='text' name='cert_name_{n}' placeholder='자격·교육명 {n}'><input type='text' name='cert_org_{n}'>"
    f"<select name='y{n}'><option>2026</option></select><button type='button'>위로</button>"
    f"<button type='button'>아래로</button><button type='button'>삭제</button></div>" for n in range(1, 201))

#: 이력서 수정 화면 — 위쪽에 학교 이름 검색칸, 요소 1,200개+, 맨 아래 자기소개서. 사이트 검색칸은 없다.
EDIT = f"""<!doctype html><html><body><h1>이력서 작성</h1><form id="resume">
<fieldset><legend>학력</legend><label for="HighSchool_Schl_Name_Search">고등학교</label>
<input type="text" id="HighSchool_Schl_Name_Search" name="HighSchool_Schl_Name_Search" placeholder="학교명 검색" value="한빛고등학교" style="width:320px"></fieldset>
<fieldset><legend>자격</legend>{_ROWS}</fieldset>
<fieldset><legend>자기소개서</legend><label for="selfintro_1">자기소개서 1 내용</label><textarea id="selfintro_1"></textarea></fieldset>
</form></body></html>"""

#: 같은 폼인데 머리에 **스스로 밝힌** 검색칸이 있다.
EDIT_WITH_SITE_SEARCH = EDIT.replace(
    "<h1>이력서 작성</h1>",
    "<header><form role='search' action='/search'><input type='search' name='q' placeholder='기업·공고 검색' style='width:300px'></form></header><h1>이력서 작성</h1>")

#: 평범한 화면 — type 도 role 도 없는 검색칸(이름으로만 알 수 있다)과 소식지 칸 하나.
HOME = """<!doctype html><html><body><form action="/search" method="get"><input type="text" name="keyword" placeholder="검색어를 입력하세요" style="width:300px"></form>
<main><h1>모의채용</h1><p>시험용 사이트</p></main><footer><input type="text" name="email" placeholder="소식지 이메일"></footer></body></html>"""

MYPAGE = """<!doctype html><html><body><h1>MY페이지</h1><p>이력서 관리</p>
<a id="go" href="/resume/edit" target="_blank">이력서 100% 완성</a></body></html>"""

RESULTS = """<!doctype html><html><body><h1>검색 결과 2건</h1><ol>
<li><a href="/company/c101">한솔정밀 — 기업 정보</a></li><li><a href="/company/c102">한솔테크 — 기업 정보</a></li></ol></body></html>"""

PAGES = {"/resume/edit": EDIT, "/resume/edit2": EDIT_WITH_SITE_SEARCH, "/": HOME, "/mypage": MYPAGE, "/search": RESULTS}


def _fulfill(route: Any) -> None:
    body = PAGES.get(urlparse(route.request.url).path, "<html><body>없음</body></html>")
    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)


@pytest.fixture(scope="module")
def chromium():
    with playwright_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield launched
        launched.close()


@pytest.fixture()
def context(chromium):
    made = chromium.new_context(viewport={"width": 1200, "height": 800})
    made.route("**/*", _fulfill)
    yield made
    made.close()


@pytest.fixture()
def worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))


def _open(context: Any, path: str) -> Any:
    page = context.new_page()
    page.goto("https://jobs.example.com" + path)
    return page


# ── 4. 사이트 검색칸 고르기 ────────────────────────────────────────────────────


def test_a_field_in_a_data_entry_form_is_not_the_site_search_box(context) -> None:
    """실제로 고른 칸이 `HighSchool_Schl_Name_Search` 였다 — 이름에 search, 넓고, 위쪽."""
    page = _open(context, "/resume/edit")

    assert page.evaluate(BrowserWorker._SITE_SEARCH_JS) is None
    assert page.locator("[data-jarvis-sitesearch]").count() == 0, "표시도 남기면 안 된다 — 그 표시가 글을 치는 자리다"


def test_a_declared_search_box_on_a_form_page_is_still_found(context) -> None:
    page = _open(context, "/resume/edit2")

    found = page.evaluate(BrowserWorker._SITE_SEARCH_JS)

    assert found is not None and "기업·공고 검색" in found["name"]
    assert page.locator("[data-jarvis-sitesearch]").get_attribute("name") == "q"


def test_an_ordinary_page_keeps_its_name_only_search_box(context) -> None:
    """거꾸로 — 폼이 아닌 화면의 검색칸(type·role 없이 이름만)은 예전처럼 잡는다."""
    page = _open(context, "/")

    found = page.evaluate(BrowserWorker._SITE_SEARCH_JS)

    assert found is not None and "검색어" in found["name"]


# ── 3. 찾기는 화면 전체를 본다 ──────────────────────────────────────────────────


def test_find_reaches_the_bottom_of_a_long_form(context, worker) -> None:
    page = _open(context, "/resume/edit")

    found = worker._find(page, {"query": "자기소개서"})

    assert found["match_count"] >= 1, found.get("instruction")
    assert found["scanned"] > 1000, "200개에서 멈추면 맨 아래 칸은 영영 「없다」"


# ── 1. 새 탭 따라가기 ───────────────────────────────────────────────────────────


def test_a_link_that_opens_a_new_tab_is_followed(context, worker, monkeypatch) -> None:
    page = _open(context, "/mypage")
    worker._context, worker._page = context, page
    monkeypatch.setattr(worker, "_bring_to_front", lambda *_a, **_k: None)
    monkeypatch.setattr(worker, "_maximize_window", lambda *_a, **_k: None)
    known = list(context.pages)

    page.click("#go")
    opened = worker._adopt_new_window(known)

    assert opened is not None, "새 탭이 열렸는데 못 봤다 — 원래 탭에 남아 「눌렀다」만 보고하던 자리"
    assert opened["url"].endswith("/resume/edit")
    assert worker._page is not page


class _FakePage:
    def __init__(self, url: str = "https://example.com/") -> None:
        self.url = url
        self.pumped = 0
        self.on_pump: Any = None

    def is_closed(self) -> bool:
        return False

    def wait_for_timeout(self, _ms: int) -> None:
        self.pumped += 1
        if self.on_pump:
            self.on_pump()

    def wait_for_load_state(self, *_a: Any, **_k: Any) -> None:
        return None

    def title(self) -> str:
        return "t"


class _Ctx:
    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages


def test_the_wait_pumps_events_instead_of_sleeping(worker, monkeypatch) -> None:
    """가짜로도 못 박는다 — 새 탭은 **이벤트가 돌 때만** 목록에 나타난다."""
    first, popup = _FakePage(), _FakePage("https://example.com/new")
    worker._context = _Ctx([first])
    worker._page = first
    monkeypatch.setattr(worker, "_bring_to_front", lambda *_a, **_k: None)
    monkeypatch.setattr(worker, "_maximize_window", lambda *_a, **_k: None)
    first.on_pump = lambda: worker._context.pages.append(popup) if popup not in worker._context.pages else None

    opened = worker._adopt_new_window([first], wait_ms=1000)

    assert first.pumped >= 1
    assert opened is not None and worker._page is popup


# ── 2. 「글이 나타난다」는 새로 나타나야 한다 ───────────────────────────────────


def test_text_that_was_already_there_proves_nothing() -> None:
    assert BrowserWorker._satisfied("text_appears", True, True) == ""
    assert BrowserWorker._satisfied("text_appears", False, True) == "text_present"
    assert BrowserWorker._satisfied("text_appears", False, False) == ""


# ── 5. 나가기가 막히면 새 탭에서 ────────────────────────────────────────────────

_ABORTED = 'Page.goto: net::ERR_ABORTED at https://www.google.com/search?q=x\nCall log:\n  - navigating to "…"'


def _refused(worker: BrowserWorker, *, kind: str = "beforeunload", accepted: Any = False, age: float = 0.2) -> None:
    worker._last_dialog = {"type": kind, "accepted": accepted, "at": browser_module.time.time() - age}


def test_leaving_was_refused_needs_both_the_error_and_the_prompt(worker) -> None:
    _refused(worker)
    assert worker._leaving_was_refused(RuntimeError(_ABORTED)) is True
    assert worker._leaving_was_refused(RuntimeError("page_not_found")) is False, "다른 실패는 이 길이 아니다"
    _refused(worker, kind="confirm")
    assert worker._leaving_was_refused(RuntimeError(_ABORTED)) is False
    _refused(worker, accepted=None)
    assert worker._leaving_was_refused(RuntimeError(_ABORTED)) is False, "사람에게 남겨 둔 창은 우리가 닫은 것이 아니다"
    _refused(worker, age=120)
    assert worker._leaving_was_refused(RuntimeError(_ABORTED)) is False, "한참 전 창은 이번 실패의 까닭이 아니다"
    worker._last_dialog = None
    assert worker._leaving_was_refused(RuntimeError(_ABORTED)) is False, "내려받기 주소도 ERR_ABORTED 다"


def test_a_blocked_open_is_retried_once_in_a_new_tab(worker, monkeypatch) -> None:
    held, fresh = _FakePage("https://jobs.example.com/resume/edit"), _FakePage("about:blank")
    worker._page = held
    calls: list[Any] = []

    def once(action: str, arguments: dict[str, Any], *, trusted: bool = False) -> dict[str, Any]:
        calls.append(worker._page)
        if worker._page is held:
            _refused(worker)
            raise RuntimeError(_ABORTED)
        return {"action": "opened", "url": arguments["url"]}

    monkeypatch.setattr(worker, "_execute_once", once)
    monkeypatch.setattr(worker, "_new_page", lambda **_k: fresh)

    result = worker._execute("browser_open", {"url": "https://example.com/company"})

    assert calls == [held, fresh], "앞 탭에서 한 번, 새 탭에서 한 번 — 그 이상은 아니다"
    assert worker._page is fresh
    assert result["opened_in_new_tab"] is True
    assert "저장 안 된 입력" in result["instruction"] and "browser_switch_tab" in result["instruction"]


def test_other_actions_are_not_moved_to_a_new_tab(worker, monkeypatch) -> None:
    """누르기·채우기는 **그 탭에서** 해야 하는 일이다 — 새 탭으로 옮기면 딴 화면을 누른다."""
    worker._page = _FakePage()

    def once(action: str, arguments: dict[str, Any], *, trusted: bool = False) -> dict[str, Any]:
        _refused(worker)
        raise RuntimeError(_ABORTED)

    monkeypatch.setattr(worker, "_execute_once", once)
    monkeypatch.setattr(worker, "_new_page", lambda **_k: pytest.fail("새 탭을 열면 안 된다"))

    with pytest.raises(RuntimeError, match="ERR_ABORTED"):
        worker._execute("browser_click", {"ref": "j1"})


# ── 벤치가 더 찾은 둘: 1,000번째 넘는 요소의 번호 · 잘린 스냅샷 ─────────────────


def test_a_ref_past_the_thousandth_element_can_be_used(context, worker) -> None:
    """찾기는 맞게 찾았는데(j1063) 그 번호를 받는 쪽이 세 자리까지만 받았다 — 채우기·누르기가 네 번 다 떨어졌다."""
    page = _open(context, "/resume/edit")
    found = worker._find(page, {"query": "자기소개서 1 내용"})
    ref = found["matches"][0]["ref"]
    assert len(ref) >= 5, f"이 시험은 네 자리 번호를 봐야 뜻이 있다: {ref}"

    locator = worker._ref_locator(page, ref)

    assert locator.get_attribute("id") == "selfintro_1"


def test_a_malformed_ref_is_still_rejected(context, worker) -> None:
    page = _open(context, "/")
    for bad in ("x12", "j", "j1234567", "j12; drop"):
        with pytest.raises(ValueError, match="invalid_element_ref"):
            worker._ref_locator(page, bad)


def test_a_cut_snapshot_says_so_and_points_to_find(context, worker) -> None:
    page = _open(context, "/resume/edit")

    shot = worker._snapshot(page, {})

    assert shot["more_elements"] > 800
    assert "browser_find" in shot["instruction"] and "스크롤하면" in shot["instruction"]


def test_a_whole_snapshot_says_nothing_extra(context, worker) -> None:
    page = _open(context, "/")

    assert "more_elements" not in worker._snapshot(page, {})


# ── 입력 폼에서 불린 사이트 검색은 새 탭의 첫 화면에서 한다 ─────────────────────


def test_site_search_called_on_a_form_runs_in_a_new_tab_and_leaves_the_form_alone(context, worker) -> None:
    """고치기 전: 학교 칸에 검색어. 한 번 고친 뒤: 「손으로 채워라」 안내를 따라 모델이 또 학교 칸에 넣음(벤치 B#1)."""
    form = _open(context, "/resume/edit")
    worker._context, worker._page = context, form

    result = worker._site_search(form, {"query": "한솔정밀"})

    assert result["opened_in_new_tab"] is True and "입력 폼" in result["instruction"]
    assert worker._page is not form and "/search" in worker._page.url
    assert not form.is_closed() and form.url.endswith("/resume/edit")
    assert form.locator("#HighSchool_Schl_Name_Search").input_value() == "한빛고등학교"


def test_when_the_front_page_has_no_search_either_the_error_does_not_tell_it_to_fill(context, worker, monkeypatch) -> None:
    monkeypatch.setitem(PAGES, "/", "<!doctype html><html><body><h1>첫 화면</h1><a href='/mypage'>MY페이지</a></body></html>")
    form = _open(context, "/resume/edit")
    worker._context, worker._page = context, form
    tabs_before = len(context.pages)

    with pytest.raises(RuntimeError, match="site_search_box_not_found") as caught:
        worker._site_search(form, {"query": "한솔정밀"})

    message = str(caught.value)
    assert "입력 폼" in message and "넣지 마라" in message
    assert "browser_fill 로 채워라" not in message, "그 안내를 따라 모델이 폼의 칸에 검색어를 넣었다"
    assert worker._page is form and len(context.pages) == tabs_before, "연 탭은 닫고 제자리로 돌아온다"


# ── 벤치 둘째 판이 찾은 것: 화면에 보이는 아래쪽 단추 · 「실제로 읽기」 채점 ──────

STICKY = EDIT.replace("</form></body></html>", """
<div style="position:fixed;left:0;right:0;bottom:0;background:#fff;padding:10px">
 <button type="button" id="btn_save">임시저장</button><button type="button" id="btn_submit">제출하기</button></div>
</form></body></html>""")


def test_a_button_on_screen_but_late_in_the_document_is_a_candidate(context, worker, monkeypatch) -> None:
    """화면 아래 고정 막대의 「임시저장」 — 문서 1,200번째라 그림 도구가 후보에 넣지 못했다(「후보 7개 중에 없습니다」)."""
    monkeypatch.setitem(PAGES, "/resume/sticky", STICKY)
    page = _open(context, "/resume/sticky")
    monkeypatch.setattr(worker, "_screenshot", lambda *_a, **_k: {"path": ""})

    shot = worker._annotate(page, {"limit": 60})

    from alture_jarvis.ui_vision import UiVision

    assert len(shot["candidates"]) <= 60, "그림에 그리는 번호는 그대로 60개까지다"
    assert len(shot["elements"]) <= 400, "훑기는 전부 하되, 내주는 목록은 모델 창을 덮지 않는다"
    picked = UiVision._by_name("임시저장 버튼", shot["elements"])
    assert picked is not None and picked["name"] == "임시저장", "화면에 있는 것은 이름으로 찾을 수 있어야 한다"
    assert worker._ref_locator(page, picked["ref"]).get_attribute("id") == "btn_save"


def test_entering_text_into_a_page_counts_as_having_looked_at_it() -> None:
    from alture_jarvis.plan import Requirement, check

    observe = [Requirement("observe", "근거가 되는 대상 실제로 읽기", "any")]
    filled = [{"tool": "browser_fill", "ok": True, "arguments": {"ref": "j4"}, "evidence": {}}]
    clicked = [{"tool": "browser_click", "ok": True, "arguments": {"ref": "j4"}, "evidence": {}}]

    assert check(observe, sources=[], steps=filled)[0][1] is True
    assert "직접 넣음" in check(observe, sources=[], steps=filled)[0][2]
    assert check(observe, sources=[], steps=clicked)[0][1] is False, "누르기만 한 판은 본 것으로 치지 않는다"
    assert check(observe, sources=[], steps=[{**filled[0], "ok": False}])[0][1] is False


# ── 벤치 셋째 판이 찾은 것: 칸의 이름 · 한 가지 번호 · 지금 보이는 것 먼저 ─────────

LABELLED = """<!doctype html><html><body><form>
<fieldset><legend>자기소개서</legend>
<label for="t1">자기소개서 1 제목</label><input type="text" id="t1">
<label for="c1">자기소개서 1 내용</label><textarea id="c1"></textarea>
<label for="t2">자기소개서 2 제목</label><input type="text" id="t2">
<label for="c2">자기소개서 2 내용</label><textarea id="c2" placeholder="1,000자 이내"></textarea>
</fieldset>
<label><input type="checkbox" id="agree"> 개인정보 수집에 동의합니다</label>
<label>지역 <select id="region"><option>서울</option><option>부산</option></select></label>
<span id="pay_label">희망 연봉</span><input type="text" id="pay" aria-labelledby="pay_label">
<input type="text" id="bare" placeholder="추천인 코드">
</form></body></html>"""


def _by_id(page: Any, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ids = page.evaluate(
        "() => Object.fromEntries(Array.from(document.querySelectorAll('[data-jarvis-ref]'))"
        ".map((e) => [e.getAttribute('data-jarvis-ref'), e.id]))")
    return {ids.get(row["ref"], ""): row for row in rows}


def test_a_field_is_named_by_its_own_label(context, worker, monkeypatch) -> None:
    """라벨이 붙은 빈 칸 여섯이 전부 묶음의 글을 빌려 같은 이름이었다 — 모델은 번호만 보고 둘째 칸에 썼다(3판 중 2판)."""
    monkeypatch.setitem(PAGES, "/labelled", LABELLED)
    page = _open(context, "/labelled")

    rows = _by_id(page, worker._snapshot(page, {})["elements"])

    assert rows["c1"]["name"] == "자기소개서 1 내용"
    assert rows["t1"]["name"] == "자기소개서 1 제목"
    assert rows["c2"]["name"] == "자기소개서 2 내용" and rows["c2"]["placeholder"] == "1,000자 이내"
    assert rows["agree"]["name"] == "개인정보 수집에 동의합니다"
    assert rows["region"]["name"] == "지역", "감싼 라벨에서 선택지 글은 뺀다"
    assert rows["pay"]["name"] == "희망 연봉"
    assert rows["bare"]["name"] == "추천인 코드" and "placeholder" not in rows["bare"], "라벨이 없으면 예전 그대로"


def test_find_returns_the_one_field_with_that_label(context, worker, monkeypatch) -> None:
    monkeypatch.setitem(PAGES, "/labelled", LABELLED)
    page = _open(context, "/labelled")

    found = worker._find(page, {"query": "자기소개서 1 내용"})

    assert [m["name"] for m in found["matches"]] == ["자기소개서 1 내용"]
    assert worker._find(page, {"query": "1,000자 이내"})["match_count"] == 1, "칸 안의 흐린 글로도 계속 찾는다"


def test_fill_says_which_field_it_filled(context, worker, monkeypatch) -> None:
    monkeypatch.setitem(PAGES, "/labelled", LABELLED)
    page = _open(context, "/labelled")
    ref = worker._find(page, {"query": "자기소개서 2 내용"})["matches"][0]["ref"]

    done = worker._fill(page, {"ref": ref, "value": "둘째 글"})

    assert done["field"] == "자기소개서 2 내용"
    assert page.evaluate("() => document.getElementById('c2').value") == "둘째 글"


def test_a_snapshot_holds_what_is_on_screen_first(context, worker, monkeypatch) -> None:
    """화면 아래 고정 막대의 「임시저장」 — 문서 1,200번째라 스냅샷에 없었고, 모델은 칸만 세 번 채우고 「저장했습니다」로 끝냈다."""
    monkeypatch.setitem(PAGES, "/resume/sticky", STICKY)
    page = _open(context, "/resume/sticky")

    top = worker._snapshot(page, {})
    names = [row["name"] for row in top["elements"]]

    assert "임시저장" in names and "제출하기" in names
    assert top["element_count"] <= 200, "모델에게 내주는 양은 늘지 않는다"
    assert top["on_screen_count"] >= 2 and top["more_elements"] > 800
    assert names.index("임시저장") < top["on_screen_count"], "줄인 목록에서는 화면에 보이는 것이 앞에 온다"
    assert not any("on_screen" in row or "capped" in row for row in top["elements"]), "속 표시는 내보내지 않는다"
    assert "자기소개서 1 내용" not in names, "아직 화면에 없다"

    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(150)

    assert "자기소개서 1 내용" in [row["name"] for row in worker._snapshot(page, {})["elements"]], "내려가면 그때 보이는 것이 담긴다"


LIST_THEN_BUTTON = "<!doctype html><html><body><ul>" + "".join(
    f"<li><a href='/p/{n}'>항목 {n}</a></li>" for n in range(1, 61)) + "</ul><button id='next'>다음 단계</button></body></html>"


def test_find_and_snapshot_give_the_same_number(context, worker, monkeypatch) -> None:
    """접는 스냅샷과 접지 않는 찾기가 번호를 다르게 셌다 — 찾기가 준 번호가 스냅샷 한 번에 죽거나 다른 것을 가리켰다."""
    monkeypatch.setitem(PAGES, "/list", LIST_THEN_BUTTON)
    monkeypatch.setitem(PAGES, "/resume/sticky", STICKY)
    for path, query, wanted in (("/list", "다음 단계", "next"), ("/resume/sticky", "임시저장", "btn_save")):
        page = _open(context, path)
        ref = worker._find(page, {"query": query})["matches"][0]["ref"]

        shot = worker._snapshot(page, {})

        assert worker._ref_locator(page, ref).get_attribute("id") == wanted, path
        assert ref in worker._ref_memory, "스냅샷이 내주지 않은 것도 이름을 기억한다"
        assert [row["ref"] for row in shot["elements"] if row["name"] == query] == [ref], path
    assert shot["element_count"] <= 200


def test_a_folded_list_still_says_how_many_it_folded(context, worker, monkeypatch) -> None:
    monkeypatch.setitem(PAGES, "/list", LIST_THEN_BUTTON)
    page = _open(context, "/list")

    shot = worker._snapshot(page, {})

    assert shot["list_more"] == 60 - worker.config.browser_snapshot_group_cap
    assert shot["element_count"] == worker.config.browser_snapshot_group_cap + 1
    assert "more_elements" not in shot, "접은 것은 「더 있다」가 아니라 「접었다」로 센다"


# ── 벤치 셋째 판: 스냅샷이 길목의 30,000자에서 잘렸다 ────────────────────────────


def test_a_snapshot_fits_what_the_model_is_given(context, worker, monkeypatch) -> None:
    """요소 200개 = 32,011자. 길목에서 앞 30,000자만 남아 「임시저장」(199번째)과 맨 끝의 안내문이 모델에게 안 갔다."""
    import json

    from alture_jarvis.agent import _TOOL_RESULT_MAX_CHARS, _bounded_tool_result

    monkeypatch.setitem(PAGES, "/resume/sticky", STICKY)
    page = _open(context, "/resume/sticky")

    shot = worker._snapshot(page, {})
    sent = _bounded_tool_result(json.dumps({"ok": True, "tool": "browser_snapshot", "result": shot}, ensure_ascii=False))

    assert len(sent) <= _TOOL_RESULT_MAX_CHARS and "잘렸다" not in sent, "스냅샷은 스스로 예산 안에 들어온다"
    assert '"임시저장"' in sent and "더 있다" in sent
    assert sent.index("더 있다") < sent.index('"elements"'), "안내는 목록 앞에 — 뒤가 잘려도 남는다"
    assert shot["more_elements"] + shot["element_count"] == worker._find(page, {"query": "임시저장"})["scanned"], "뺀 것은 센다"
    assert shot["element_count"] == 200, "뻔한 값을 빼서 200개가 예산 안에 든다"
    assert not any("frame_index" in row or row.get("disabled") is False for row in shot["elements"])


def test_the_snapshot_budget_leaves_room_under_the_cut() -> None:
    from alture_jarvis.agent import _TOOL_RESULT_MAX_CHARS

    assert browser_module._SNAPSHOT_CHAR_BUDGET + 3_000 <= _TOOL_RESULT_MAX_CHARS, "두 상한이 어긋나면 목록 뒤가 조용히 잘린다"


def test_fitting_keeps_document_order_when_everything_fits() -> None:
    rows = [{"ref": f"j{n}", "name": f"칸 {n}"} for n in range(1, 6)]

    kept, from_screen = browser_module._fit_snapshot(rows, {id(rows[4])}, 10, 10_000)

    assert kept == rows and from_screen == 0


def test_fitting_puts_what_is_on_screen_first_and_stops_at_the_budget() -> None:
    rows = [{"ref": f"j{n}", "name": "가" * 40} for n in range(1, 21)]
    on_screen = {id(rows[17]), id(rows[18])}

    kept, from_screen = browser_module._fit_snapshot(rows, on_screen, 200, 400)

    assert [row["ref"] for row in kept[:2]] == ["j18", "j19"] and from_screen == 2
    assert [row["ref"] for row in kept[2:]] == [f"j{n}" for n in range(1, len(kept) - 1)], "남는 자리는 문서 위쪽부터, 건너뛰지 않고"
    assert 2 < len(kept) < 20

    by_count, _ = browser_module._fit_snapshot(rows, on_screen, 5, 0)
    assert [row["ref"] for row in by_count] == ["j18", "j19", "j1", "j2", "j3"]


def test_a_cut_tool_result_says_it_was_cut() -> None:
    from alture_jarvis.agent import _bounded_tool_result

    assert _bounded_tool_result("가" * 100, 200) == "가" * 100
    cut = _bounded_tool_result("가" * 50_000, 30_000)
    assert len(cut) <= 30_000 and cut.startswith("가" * 1000)
    assert "잘렸다" in cut[-200:] and "50,000자" in cut


# ── 벤치 넷째 판(과제 E): 표로 짠 폼 · 값 없는 채우기 · 체크 칸 ──────────────────

TABLE_FORM = """<!doctype html><html><body><form id="apply" onsubmit="return false"><table>
<tr><th>희망연봉</th><td><input type="text" name="pay"> 만원</td></tr>
<tr><th>최종학력</th><td><select name="edu"><option value="">선택</option><option>고등학교 졸업</option><option>대학교(4년) 졸업</option></select></td></tr>
<tr><th>입사 가능 시기</th><td><label><input type="radio" name="start" value="즉시"> 즉시</label>
 <label><input type="radio" name="start" value="1개월 이내"> 1개월 이내</label></td></tr>
<tr><th>지원 분야</th><td><div id="dd" style="cursor:pointer;border:1px solid #999;width:200px">선택하세요</div></td></tr>
<tr><th>보유 자격증</th><td><input type="text" id="cert_name" placeholder="자격증명"><input type="text" id="cert_org" placeholder="발급기관">
 <button type="button" id="del">삭제</button></td></tr>
<tr><th>검색</th><td><input type="submit" id="go" value="조회"></td></tr>
<tr><th>동의</th><td><label><input type="checkbox" name="agree"> 개인정보 수집·이용에 동의합니다</label></td></tr>
</table><dl><dt>연락처</dt><dd><input type="text" id="phone"></dd></dl></form></body></html>"""


def _table_form(context: Any, monkeypatch: Any) -> Any:
    monkeypatch.setitem(PAGES, "/apply", TABLE_FORM)
    return _open(context, "/apply")


def test_a_field_in_a_headed_row_is_named_by_the_row_head(context, worker, monkeypatch) -> None:
    """`<th>희망연봉</th><td><input> 만원</td>` 의 칸 이름이 「만원 안의 input」이었다 — 모델은 줄과 칸을 잇지 못했다."""
    page = _table_form(context, monkeypatch)

    rows = {row["name"]: row for row in worker._snapshot(page, {})["elements"]}

    assert rows["희망연봉"]["tag"] == "input"
    assert rows["최종학력"]["tag"] == "select" and "대학교(4년) 졸업" in rows["최종학력"]["options"], "선택지는 이름이 아니라 따로 준다"
    assert rows["연락처"]["tag"] == "input", "정의 목록(dt·dd)도 같은 관계다"
    assert rows["자격증명"]["row"] == "보유 자격증" and rows["발급기관"]["row"] == "보유 자격증", "제 이름이 있으면 줄 머리는 문맥으로"
    assert rows["삭제"]["row"] == "보유 자격증", "어느 줄의 삭제인지"
    assert rows["선택하세요"]["row"] == "지원 분야"
    assert rows["조회"]["tag"] == "input", "단추인 input 은 제 글자가 이름이다"
    assert "row" not in rows["희망연봉"], "이름이 곧 줄 머리면 되풀이하지 않는다"


def test_find_reaches_a_nameless_widget_by_its_row_head(context, worker, monkeypatch) -> None:
    page = _table_form(context, monkeypatch)

    found = worker._find(page, {"query": "지원 분야"})

    assert [m["name"] for m in found["matches"]] == ["선택하세요"]


def test_a_fill_called_without_a_value_does_not_write_an_empty_string(context, worker, monkeypatch) -> None:
    """`fields: [{ref, value}]` 모양으로 불린 한 칸 채우기가 빈 글을 넣고 성공이라 답했다 — 모델은 「4200 입력」이라고 보고했다."""
    page = _table_form(context, monkeypatch)
    rows = {row["name"]: row["ref"] for row in worker._snapshot(page, {})["elements"]}

    done = worker._fill(page, {"ref": rows["자격증명"], "fields": [
        {"ref": rows["자격증명"], "value": "전산회계 1급"}, {"ref": rows["발급기관"], "value": "한국세무사회"}]})

    assert done["action"] == "form_filled" and [f["field"] for f in done["fields"]] == ["자격증명", "발급기관"]
    assert page.evaluate("() => [document.getElementById('cert_name').value, document.getElementById('cert_org').value]") == [
        "전산회계 1급", "한국세무사회"]

    with pytest.raises(ValueError, match="value_required"):
        worker._fill(page, {"ref": rows["희망연봉"]})
    assert page.evaluate("() => document.getElementById('cert_name').value") == "전산회계 1급", "아무것도 지우지 않았다"

    worker._fill(page, {"ref": rows["자격증명"], "value": ""})
    assert page.evaluate("() => document.getElementById('cert_name').value") == "", "비우려면 빈 글을 준다"


def test_pressing_a_radio_or_a_checkbox_is_proven_by_its_checked_state(context, worker, monkeypatch) -> None:
    """라디오를 맞게 눌렀는데 「화면에서 어떤 변화도 찾지 못했습니다. 무엇이 막고 있는지 확인하라」가 붙었다."""
    page = _table_form(context, monkeypatch)
    rows = {row["name"]: row["ref"] for row in worker._snapshot(page, {})["elements"]}

    radio = worker._click(page, {"ref": rows["1개월 이내"], "expect": {"kind": "text_appears", "value": "1개월 이내"}})

    assert radio["checked"] is True and radio["changed"] is True and radio["verified"] is True
    assert "체크 상태가 바뀌었다" in radio["instruction"] and "찾지 못했" not in radio["instruction"]

    box = worker._click(page, {"ref": rows["개인정보 수집·이용에 동의합니다"]})
    assert box["checked"] is True and box["changed"] is True

    again = worker._click(page, {"ref": rows["1개월 이내"]})
    assert again["checked"] is True and "전부터 선택돼" in again["instruction"]


# ── 벤치 다섯째 판: 번호는 그 요소의 것이다 ──────────────────────────────────────

GROWING = """<!doctype html><html><body><form onsubmit="return false">
<label for="pay">희망연봉</label><input type="text" id="pay">
<div id="certs"></div><button type="button" id="add">자격증 추가</button>
<label><input type="checkbox" id="agree"> 동의합니다</label>
<button type="button" id="save">임시저장</button><button type="button" id="apply">지원하기</button>
</form><script>
 let n = 0;
 document.getElementById('add').addEventListener('click', () => { n += 1;
   const row = document.createElement('div');
   row.innerHTML = '<input type="text" id="cert' + n + '" placeholder="자격증명 ' + n + '"><button type="button">삭제 ' + n + '</button>';
   document.getElementById('certs').appendChild(row); });
</script></body></html>"""


def _ids(page: Any) -> dict[str, str]:
    """번호 → 그 번호표가 붙은 요소의 id."""
    return page.evaluate(
        "() => Object.fromEntries(Array.from(document.querySelectorAll('[data-jarvis-ref]'))"
        ".map((e) => [e.getAttribute('data-jarvis-ref'), e.id || e.textContent.trim()]))")


def test_a_number_keeps_pointing_at_the_same_element_when_rows_are_added(context, worker, monkeypatch) -> None:
    """줄을 추가하자 뒤 번호가 밀렸다 — 앞에서 본 번호로 누른 것이 「임시저장」 대신 「자격증 추가」, 체크 칸 대신 새 글 칸이었다."""
    monkeypatch.setitem(PAGES, "/growing", GROWING)
    page = _open(context, "/growing")
    first = {row["name"]: row["ref"] for row in worker._snapshot(page, {})["elements"]}

    worker._click(page, {"ref": first["자격증 추가"]})
    worker._click(page, {"ref": first["자격증 추가"]})
    second = {row["name"]: row["ref"] for row in worker._snapshot(page, {})["elements"]}

    for name in ("희망연봉", "자격증 추가", "동의합니다", "임시저장", "지원하기"):
        assert second[name] == first[name], name
    fresh = {second["자격증명 1"], second["삭제 1"], second["자격증명 2"], second["삭제 2"]}
    assert len(fresh) == 4 and not fresh & set(first.values()), "새 요소는 한 번도 안 쓴 번호를 받는다"
    assert worker._ref_locator(page, first["임시저장"]).get_attribute("id") == "save"
    assert worker._ref_locator(page, first["동의합니다"]).get_attribute("id") == "agree"


def test_the_list_is_still_in_document_order(context, worker, monkeypatch) -> None:
    monkeypatch.setitem(PAGES, "/growing", GROWING)
    page = _open(context, "/growing")
    first = worker._snapshot(page, {})
    worker._click(page, {"ref": next(row["ref"] for row in first["elements"] if row["name"] == "자격증 추가")})

    names = [row["name"] for row in worker._snapshot(page, {})["elements"]]

    assert names == ["희망연봉", "자격증명 1", "삭제 1", "자격증 추가", "동의합니다", "임시저장", "지원하기"]


def test_find_snapshot_and_the_picture_tool_agree_after_the_page_grows(context, worker, monkeypatch) -> None:
    monkeypatch.setitem(PAGES, "/growing", GROWING)
    monkeypatch.setattr(worker, "_screenshot", lambda *_a, **_k: {"path": ""})
    page = _open(context, "/growing")
    save = worker._find(page, {"query": "임시저장"})["matches"][0]["ref"]
    worker._click(page, {"ref": worker._find(page, {"query": "자격증 추가"})["matches"][0]["ref"]})

    assert worker._find(page, {"query": "임시저장"})["matches"][0]["ref"] == save
    assert next(row["ref"] for row in worker._snapshot(page, {})["elements"] if row["name"] == "임시저장") == save
    assert next(row["ref"] for row in worker._annotate(page, {})["elements"] if row["name"] == "임시저장") == save


def test_a_copied_node_does_not_share_its_number(context, worker, monkeypatch) -> None:
    """번호표째 복제된 노드(다시 그리는 사이트가 그런다)가 같은 번호를 달고 있으면 누가 눌릴지 모른다."""
    monkeypatch.setitem(PAGES, "/growing", GROWING)
    page = _open(context, "/growing")
    first = {row["name"]: row["ref"] for row in worker._snapshot(page, {})["elements"]}
    page.evaluate("() => { const c = document.getElementById('save').cloneNode(true); c.id = 'save_copy'; document.body.appendChild(c); }")

    worker._snapshot(page, {})
    stamped = _ids(page)

    assert stamped[first["임시저장"]] == "save"
    assert [ref for ref, node in stamped.items() if node == "save_copy"] not in ([], [first["임시저장"]])
    assert len(stamped) == len(set(stamped)) == len(first) + 1


def test_a_new_document_starts_counting_again(context, worker, monkeypatch) -> None:
    monkeypatch.setitem(PAGES, "/growing", GROWING)
    page = _open(context, "/growing")
    worker._click(page, {"ref": next(r["ref"] for r in worker._snapshot(page, {})["elements"] if r["name"] == "자격증 추가")})
    assert len(worker._snapshot(page, {})["elements"]) == 7

    page.goto("https://jobs.example.com/")

    assert [row["ref"] for row in worker._snapshot(page, {})["elements"]][0] == "j1"


# ── 벤치 여섯째 판: 우리 누르기가 띄운 확인 창을 도구가 「취소」로 닫았다 ──────────

_MODAL = """<div id="modal" {hidden} style="position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:50">
 <div style="background:#fff;margin:20vh auto;padding:20px;width:320px"><p>{text}</p>
  <button type="button" id="ok">확인</button><button type="button" id="no">{negative}</button></div></div>"""

CONFIRMING = """<!doctype html><html><body><h1>지원서</h1><p>아래 단추로 저장합니다.</p>
<button type="button" id="save">임시저장</button><span id="status"></span>
""" + _MODAL.format(hidden="hidden", text="임시저장하시겠습니까?", negative="취소") + """
<script>
 window.pressed = [];
 const modal = document.getElementById('modal');
 document.getElementById('save').addEventListener('click', () => { window.pressed.push('save'); modal.hidden = false; });
 document.getElementById('no').addEventListener('click', () => { window.pressed.push('no'); modal.hidden = true; });
 document.getElementById('ok').addEventListener('click', () => { window.pressed.push('ok'); modal.hidden = true;
   document.getElementById('status').textContent = '임시저장되었습니다'; });
</script></body></html>"""

#: 우리가 띄운 적 없는 창이 처음부터 덮고 있다(소식지 권유 같은 것).
STRAY = """<!doctype html><html><body><h1>지원서</h1><button type="button" id="save">임시저장</button>
""" + _MODAL.format(hidden="", text="소식지를 받아 보시겠습니까?", negative="닫기") + """
<script>
 window.pressed = [];
 document.getElementById('save').addEventListener('click', () => window.pressed.push('save'));
 document.getElementById('no').addEventListener('click', () => { window.pressed.push('no'); document.getElementById('modal').hidden = true; });
 document.getElementById('ok').addEventListener('click', () => window.pressed.push('ok'));
</script></body></html>"""


def _writing_worker(tmp_path: Path) -> BrowserWorker:
    """누르는 것까지 하는 작업자 — 기본값(읽기 전용)은 「임시저장」을 누르기 전에 막는다."""
    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o",
                                      browser_read_only=False, browser_action_timeout_sec=2))


def test_a_dialog_our_own_click_opened_is_not_cancelled_for_us(context, tmp_path, monkeypatch) -> None:
    """「임시저장」이 띄운 「임시저장하시겠습니까?」를, 다음 누르기가 가로막히자 도구가 「취소」로 닫았다 — 결과에는 한 마디도 없이."""
    monkeypatch.setitem(PAGES, "/confirming", CONFIRMING)
    page = _open(context, "/confirming")
    worker = _writing_worker(tmp_path)
    save = next(row["ref"] for row in worker._snapshot(page, {})["elements"] if row["name"] == "임시저장")

    first = worker._click(page, {"ref": save, "expect": {"kind": "text_appears", "value": "임시저장되었습니다"}})
    assert any("임시저장하시겠습니까" in str(note) for note in first.get("what_changed") or []), first

    with pytest.raises(RuntimeError, match="click_blocked_by_the_dialog_you_opened") as blocked:
        worker._click(page, {"ref": save, "expect": {"kind": "text_appears", "value": "임시저장되었습니다"}})

    assert "임시저장하시겠습니까" in str(blocked.value) and "그 창 안의 단추" in str(blocked.value)
    assert page.evaluate("() => window.pressed") == ["save"], "취소도 확인도 대신 누르지 않았다"
    assert page.evaluate("() => document.getElementById('modal').hidden") is False

    ok = next(row["ref"] for row in worker._snapshot(page, {})["elements"] if row["name"] == "확인")
    done = worker._click(page, {"ref": ok, "expect": {"kind": "text_appears", "value": "임시저장되었습니다"}})
    assert done["verified"] is True and page.evaluate("() => window.pressed") == ["save", "ok"]


def test_a_stray_dialog_is_still_closed_but_the_result_says_so(context, tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(PAGES, "/stray", STRAY)
    page = _open(context, "/stray")
    worker = _writing_worker(tmp_path)
    save = worker._find(page, {"query": "임시저장"})["matches"][0]["ref"]

    done = worker._click(page, {"ref": save})

    assert page.evaluate("() => window.pressed") == ["no", "save"]
    assert done["closed_first"] == [{"text": done["closed_first"][0]["text"], "pressed": "닫기"}]
    assert "소식지" in done["closed_first"][0]["text"] and "닫고 눌렀다" in done["instruction"]
