from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import pytest

from alture_jarvis import browser as browser_module
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class Node:
    """One DOM element as far as these handlers can tell it apart: text,
    attributes, visibility, children reachable by an exact selector string,
    and what happens when it is clicked."""

    def __init__(
        self,
        *,
        text: str = "",
        attrs: dict[str, str] | None = None,
        visible: bool = True,
        children: dict[str, list["Node"]] | None = None,
        click_error: Exception | None = None,
        blocker: str = "",
        on_click: Callable[[], None] | None = None,
    ) -> None:
        self.text = text
        self.attrs = attrs or {}
        self.visible = visible
        self.children = children or {}
        self.click_error = click_error
        self.blocker = blocker
        self.on_click = on_click
        self.clicks = 0


class FakeLocator:
    def __init__(self, nodes: list[Node], index: int | None = None) -> None:
        self.nodes = nodes
        self.index = index

    def count(self) -> int:
        return len(self.nodes)

    def nth(self, index: int) -> "FakeLocator":
        return FakeLocator(self.nodes, index)

    @property
    def first(self) -> "FakeLocator":
        return self.nth(0)

    def _node(self) -> Node | None:
        position = self.index or 0
        return self.nodes[position] if position < len(self.nodes) else None

    def is_visible(self) -> bool:
        node = self._node()
        return bool(node and node.visible)

    def inner_text(self, timeout: float | None = None) -> str:
        del timeout
        node = self._node()
        if node is None:
            raise RuntimeError("Timeout exceeded: element not found")
        return node.text

    def get_attribute(self, name: str) -> str | None:
        node = self._node()
        return node.attrs.get(name) if node else None

    def locator(self, selector: str) -> "FakeLocator":
        node = self._node()
        return FakeLocator(list(node.children.get(selector, [])) if node else [])

    def evaluate(self, script: str, *args: Any) -> Any:
        del script, args
        node = self._node()
        return node.blocker if node else ""

    def click(self, timeout: float | None = None) -> None:
        del timeout
        node = self._node()
        if node is None:
            raise RuntimeError("Locator.click: Timeout 20000ms exceeded.")
        if node.click_error is not None:
            raise node.click_error
        node.clicks += 1
        if node.on_click is not None:
            node.on_click()


class FakeFrame:
    def __init__(self, nodes: dict[str, list[Node]]) -> None:
        self.nodes = nodes

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(list(self.nodes.get(selector, [])))


class FakeKeyboard:
    def type(self, text: str, delay: int = 0) -> None:
        del text, delay

    def press(self, key: str) -> None:
        del key


class FakePage:
    def __init__(self, frame: FakeFrame, *, body_text: str = "", url: str = "") -> None:
        self.frame = frame
        self.body_text = body_text
        self.url = url
        self.keyboard = FakeKeyboard()
        self.waits = 0

    def frame_locator(self, selector: str) -> FakeFrame:
        del selector
        return self.frame

    def locator(self, selector: str) -> FakeLocator:
        del selector
        return FakeLocator([Node(text=self.body_text)])

    def wait_for_timeout(self, milliseconds: int) -> None:
        del milliseconds
        self.waits += 1
        time.sleep(0.01)

    def is_closed(self) -> bool:
        return False


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_visual_overlay=False,
            naver_blog_save_verify_timeout_sec=1,
        )
    )


def _restore_confirm(buttons: list[Node]) -> Node:
    """The popup from the live failure: SmartEditor's draft-restore confirm,
    identified by its own classes exactly as Playwright's call log reported it."""
    popup = Node(
        text="이전에 작성 중이던 글이 있습니다. 불러오시겠습니까?",
        attrs={
            "class": "se-popup __se-sentry se-popup-alert se-popup-alert-confirm",
            "data-name": "se-popup-alert se-popup-alert-confirm",
        },
        children={browser_module._SE_POPUP_BUTTON: buttons},
    )

    def hide() -> None:
        popup.visible = False

    for button in buttons:
        button.on_click = hide
    return popup


def _dialog(text: str, buttons: list[Node], *, klass: str = "renamed") -> Node:
    """A dialog with NO SmartEditor classes -- only its shape identifies it."""
    popup = Node(text=text, attrs={"class": klass},
                 children={browser_module._SE_POPUP_BUTTON: buttons})

    def hide() -> None:
        popup.visible = False

    for button in buttons:
        button.on_click = hide
    return popup


def test_draft_restore_confirm_is_dismissed_with_cancel_never_the_positive(tmp_path: Path) -> None:
    """Pressing 불러오기 would load a previous draft on top of the post that was
    just written, so the dismisser must only ever take the negative button."""
    cancel, restore = Node(text="취소"), Node(text="불러오기")
    popup = _restore_confirm([cancel, restore])
    frame = FakeFrame({browser_module._SE_POPUP: [popup]})
    page = FakePage(frame)

    dismissed = _worker(tmp_path)._naver_blog_dismiss_popups(page, frame)

    assert cancel.clicks == 1
    assert restore.clicks == 0
    assert dismissed[0]["button"] == "취소"
    assert dismissed[0]["confirm"] is True


def test_confirm_without_a_negative_button_fails_loudly_with_its_text(tmp_path: Path) -> None:
    popup = _restore_confirm([Node(text="불러오기"), Node(text="확인")])
    frame = FakeFrame({browser_module._SE_POPUP: [popup]})
    page = FakePage(frame)

    with pytest.raises(RuntimeError, match="popup_blocking:이전에 작성 중이던"):
        _worker(tmp_path)._naver_blog_dismiss_popups(page, frame)


def test_plain_alert_is_acknowledged_because_it_asks_nothing(tmp_path: Path) -> None:
    ok = Node(text="확인")
    popup = Node(
        text="이미지를 등록할 수 없습니다.",
        attrs={"class": "se-popup se-popup-alert", "data-name": "se-popup-alert"},
        children={browser_module._SE_POPUP_BUTTON: [ok]},
    )
    ok.on_click = lambda: setattr(popup, "visible", False)
    frame = FakeFrame({browser_module._SE_POPUP: [popup]})

    dismissed = _worker(tmp_path)._naver_blog_dismiss_popups(FakePage(frame), frame)

    assert ok.clicks == 1
    assert dismissed[0]["confirm"] is False


def test_intercepted_click_names_the_element_that_ate_it(tmp_path: Path) -> None:
    """The live failure: the selector was right and the element was visible,
    enabled and stable, but SmartEditor's dim layer owned the click point.
    Playwright reported only "Timeout 20000ms exceeded", which got read twice
    as "iframe 구조 때문에 본문 영역 인식 실패"."""
    title = Node(
        text="",
        click_error=RuntimeError("Locator.click: Timeout 20000ms exceeded."),
        blocker=(
            "div.se-popup-dim.se-popup-dim-white<se-popup-alert se-popup-alert-confirm>"
            " | 이전에 작성 중이던 글이 있습니다"
        ),
    )
    locator = FakeLocator([title])

    with pytest.raises(RuntimeError) as failure:
        _worker(tmp_path)._naver_blog_click(locator, what="제목 영역")

    message = str(failure.value)
    assert message.startswith("naver_blog_click_intercepted:제목 영역:")
    assert "se-popup-dim" in message


def test_click_failure_with_nothing_on_top_is_not_blamed_on_a_popup(tmp_path: Path) -> None:
    locator = FakeLocator([Node(click_error=RuntimeError("Timeout 20000ms exceeded."), blocker="")])
    with pytest.raises(RuntimeError, match="naver_blog_click_failed:본문 영역"):
        _worker(tmp_path)._naver_blog_click(locator, what="본문 영역")


def _save_frame(
    *,
    count_text: str = "",
    body_text: str = "",
    on_save: Callable[[], None] | None = None,
    popup: Node | None = None,
) -> tuple[FakeFrame, Node]:
    save_button = Node(text=count_text or "저장", on_click=on_save)
    counter = Node(text=count_text) if count_text else None
    nodes: dict[str, list[Node]] = {
        ".save_btn__bzc5B, .btn_save, button:has-text('저장')": [save_button],
        "body": [Node(text=body_text)],
    }
    if counter is not None:
        nodes[".save_btn__bzc5B"] = [counter]
    if popup is not None:
        nodes[browser_module._SE_POPUP] = [popup]
    return FakeFrame(nodes), save_button


def test_save_draft_reports_unverified_when_the_page_shows_no_proof(tmp_path: Path) -> None:
    """A click that returned without throwing is not a saved draft. This is the
    exact state the 2026-08-03 session was in when it answered 임시 저장 완료."""
    frame, save_button = _save_frame()
    page = FakePage(frame)

    evidence = _worker(tmp_path)._naver_blog_click_save_draft(page, {})

    assert save_button.clicks == 1
    assert evidence["saved_verified"] is False
    assert evidence["saved_evidence"] == ""


def test_save_draft_is_verified_by_the_draft_counter_going_up(tmp_path: Path) -> None:
    state = {"count": "저장 3"}
    frame, _ = _save_frame(count_text="저장 3")

    def bump() -> None:
        state["count"] = "저장 4"
        frame.nodes[".save_btn__bzc5B"] = [Node(text=state["count"])]

    frame.nodes[".save_btn__bzc5B, .btn_save, button:has-text('저장')"][0].on_click = bump

    evidence = _worker(tmp_path)._naver_blog_click_save_draft(FakePage(frame), {})

    assert evidence["saved_verified"] is True
    assert evidence["saved_evidence"] == "draft_count:3->4"


def test_save_draft_is_verified_by_the_saved_notice_on_the_page(tmp_path: Path) -> None:
    frame, _ = _save_frame()

    def show_toast() -> None:
        frame.nodes["body"] = [Node(text="저장되었습니다")]

    frame.nodes[".save_btn__bzc5B, .btn_save, button:has-text('저장')"][0].on_click = show_toast

    evidence = _worker(tmp_path)._naver_blog_click_save_draft(FakePage(frame), {})

    assert evidence["saved_verified"] is True
    assert evidence["saved_evidence"] == "page_text:저장되었습니다"


def test_save_draft_clears_the_popup_before_pressing_save(tmp_path: Path) -> None:
    cancel = Node(text="취소")
    popup = _restore_confirm([cancel])
    frame, save_button = _save_frame(popup=popup)

    def toast() -> None:
        frame.nodes["body"] = [Node(text="저장되었습니다")]

    save_button.on_click = toast

    evidence = _worker(tmp_path)._naver_blog_click_save_draft(FakePage(frame), {})

    assert cancel.clicks == 1
    assert save_button.clicks == 1
    assert evidence["saved_verified"] is True


# ── being logged out must not look like a broken editor ──────────────────────
class _LoginPage:
    """A page that Naver has bounced to the login host."""

    def __init__(self, url: str, body: str = "NAVER 로그인\n아이디 찾기 비밀번호 찾기 회원가입") -> None:
        self.url = url
        self._body = body

    def locator(self, _selector: str):
        page = self

        class _Body:
            def inner_text(self, timeout: float = 0) -> str:
                del timeout
                return page._body

        return _Body()


def test_being_bounced_to_the_login_page_says_so(tmp_path: Path) -> None:
    # Measured live: logged out, the editor navigation silently landed on
    # nid.naver.com and the next step failed with a title-locator timeout. That
    # error blames the editor's markup for a session problem, and it sent a
    # whole investigation the wrong way.
    page = _LoginPage(
        "https://nid.naver.com/nidlogin.login?mode=form&url=https://blog.naver.com/GoBlogWrite.naver"
    )
    with pytest.raises(RuntimeError, match="naver_blog_login_required"):
        _worker(tmp_path)._naver_blog_check_intervention(page)


def test_the_login_error_names_the_setting_that_makes_it_recur(tmp_path: Path) -> None:
    # The session was lost because 로그인 상태 유지 was off, so the cookies died
    # with the browser process. Telling the user only "log in" guarantees the
    # same call next restart.
    page = _LoginPage("https://nid.naver.com/nidlogin.login")
    with pytest.raises(RuntimeError, match="로그인 상태 유지"):
        _worker(tmp_path)._naver_blog_check_intervention(page)


def test_the_editor_page_is_not_mistaken_for_a_login_page(tmp_path: Path) -> None:
    page = _LoginPage("https://blog.naver.com/GoBlogWrite.naver", body="제목 본문 저장 발행")
    _worker(tmp_path)._naver_blog_check_intervention(page)  # must not raise


# ── session status must run on the browser's own thread ─────────────────────
class FakeNaverContext:
    def __init__(self, cookies: list[dict[str, object]]) -> None:
        self._cookies = cookies

    def cookies(self, _url: str) -> list[dict[str, object]]:
        return self._cookies


def test_session_check_runs_without_a_cross_thread_error(tmp_path: Path) -> None:
    # Reading naver_session_alive() directly (not through _submit) raised a
    # greenlet cross-thread error the first time it was called from the API's
    # request thread, because Playwright's sync API is bound to the thread
    # that created it. This calls it exactly the way the health endpoint does.
    worker = _worker(tmp_path)
    worker._context = FakeNaverContext(
        [{"name": "NID_AUT", "expires": 1999999999}, {"name": "NID_SES", "expires": 1999999999}]
    )
    try:
        result = worker.naver_session_alive()
    finally:
        worker.stop()
    assert result["known"] is True
    assert result["signed_in"] is True


def test_a_session_only_cookie_is_flagged_as_wont_survive_restart(tmp_path: Path) -> None:
    # expires<=0 is Playwright's own signal for "session cookie, no expiry" --
    # the exact state that keeps dying with the browser process because
    # '로그인 상태 유지' was left unticked.
    worker = _worker(tmp_path)
    worker._context = FakeNaverContext([{"name": "NID_AUT", "expires": 0}])
    try:
        result = worker.naver_session_alive()
    finally:
        worker.stop()
    assert result["signed_in"] is True
    assert result["survives_restart"] is False
    assert "로그인 상태 유지" in result["hint"]


def test_no_browser_started_is_reported_not_raised(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        result = worker.naver_session_alive()
    finally:
        worker.stop()
    assert result == {"known": False, "reason": "browser_not_started"}


# ── modals are found dynamically, not by one hardcoded iframe or class ───────
class FramedPage(FakePage):
    """A page whose frames each hold their own nodes, like the real thing.

    The 2026-08-05 failure: Naver's draft-restore confirm ("작성 중인 글이
    있습니다") renders in the TOP document, while the dismisser only searched
    `iframe#mainFrame`. Nothing was found, the dim layer stayed up, and the
    whole page reported zero elements.
    """

    def __init__(self, frames: list[FakeFrame], **kwargs) -> None:
        super().__init__(frames[0], **kwargs)
        self.frames = frames


def test_a_modal_in_the_top_document_is_found(tmp_path: Path) -> None:
    editor_frame = FakeFrame({})           # the iframe: nothing blocking here
    top_frame = FakeFrame({browser_module._SE_POPUP: [_restore_confirm([
        Node(text="취소"), Node(text="확인")])]})
    page = FramedPage([editor_frame, top_frame])

    dismissed = _worker(tmp_path)._naver_blog_dismiss_popups(page)

    assert len(dismissed) == 1
    assert dismissed[0]["dismissed"] is True
    assert dismissed[0]["button"] == "취소"


def test_two_buttons_means_a_question_even_without_the_confirm_class(tmp_path: Path) -> None:
    # Structural, so it survives a rename: a dialog offering a choice is asking
    # something, and answering it positively could load an old draft over the
    # post we just wrote. Without the class, this used to look like a plain
    # alert and get "확인"ed.
    popup = _dialog("작성 중인 글이 있습니다. 이어서 작성하시겠습니까?",
                    [Node(text="아니오"), Node(text="예")], klass="some-renamed-dialog")
    page = FramedPage([FakeFrame({browser_module._SE_POPUP: [popup]})])

    dismissed = _worker(tmp_path)._naver_blog_dismiss_popups(page)

    assert dismissed[0]["confirm"] is True
    assert dismissed[0]["button"] == "아니오"


def test_a_renamed_confirm_with_no_negative_button_fails_loudly(tmp_path: Path) -> None:
    # Two buttons and neither is a "no" -- guessing here is how an automated
    # dismisser ends up publishing something.
    popup = Node(
        text="이어서 작성하시겠습니까?",
        attrs={"class": "renamed"},
        children={browser_module._SE_POPUP_BUTTON: [Node(text="이어쓰기"), Node(text="새로쓰기")]},
    )
    page = FramedPage([FakeFrame({browser_module._SE_POPUP: [popup]})])

    with pytest.raises(RuntimeError, match="naver_blog_popup_blocking"):
        _worker(tmp_path)._naver_blog_dismiss_popups(page)


def test_a_single_button_dialog_is_still_acknowledged(tmp_path: Path) -> None:
    # One button means it is only telling us something; pressing it is the only
    # way out and cannot answer a question on the user's behalf.
    popup = _dialog("이미지 용량이 초과되었습니다.", [Node(text="확인")], klass="renamed")
    page = FramedPage([FakeFrame({browser_module._SE_POPUP: [popup]})])

    dismissed = _worker(tmp_path)._naver_blog_dismiss_popups(page)

    assert dismissed[0]["confirm"] is False
    assert dismissed[0]["button"] == "확인"


# ── a modal that appears *after* the dismisser ran ───────────────────────────
def test_a_popup_that_appears_mid_flight_is_cleared_and_the_click_retried(tmp_path: Path) -> None:
    # Measured 2026-08-05: the editor booted clean, _naver_blog_dismiss_popups
    # found nothing, and only then did "작성 중인 글이 있습니다" appear -- so the
    # very next click was what discovered it. Waiting longer is a guess;
    # reacting to the interception is not.
    popup = _restore_confirm([Node(text="취소"), Node(text="확인")])
    target = Node(text="제목", blocker="div.se-popup-dim | 작성 중인 글이 있습니다")

    attempts = {"n": 0}

    def flaky_click(timeout: float | None = None) -> None:
        del timeout
        attempts["n"] += 1
        if attempts["n"] == 1:            # first click: the dim layer eats it
            raise RuntimeError("Locator.click: Timeout 20000ms exceeded.")
        if popup.visible:                 # still blocked -> would be a real failure
            raise RuntimeError("Locator.click: Timeout 20000ms exceeded.")

    locator = FakeLocator([target], 0)
    locator.click = flaky_click           # type: ignore[method-assign]
    page = FramedPage([FakeFrame({browser_module._SE_POPUP: [popup]})])

    _worker(tmp_path)._naver_blog_click(locator, what="제목 영역", page=page)

    assert attempts["n"] == 2, "should retry exactly once after clearing"
    assert popup.visible is False, "the popup must actually have been dismissed"


def test_a_click_still_blocked_after_clearing_is_reported_not_retried_forever(
    tmp_path: Path,
) -> None:
    # Still blocked after the popup really went away: that is a genuine
    # blocker, not the timing race. Looping here would bury it under an
    # eventual timeout instead of naming it.
    popup = _restore_confirm([Node(text="취소"), Node(text="확인")])
    target = Node(text="제목", blocker="div.other-overlay | 다른 레이어")
    locator = FakeLocator([target], 0)

    def always_blocked(timeout: float | None = None) -> None:
        del timeout
        raise RuntimeError("Locator.click: Timeout 20000ms exceeded.")

    locator.click = always_blocked        # type: ignore[method-assign]
    page = FramedPage([FakeFrame({browser_module._SE_POPUP: [popup]})])

    with pytest.raises(RuntimeError, match="naver_blog_click_intercepted"):
        _worker(tmp_path)._naver_blog_click(locator, what="제목 영역", page=page)


def test_a_popup_that_refuses_to_close_is_named_rather_than_clicked_past(
    tmp_path: Path,
) -> None:
    # A dialog whose negative button does nothing must surface as itself. The
    # dangerous alternative is deciding to press the positive one instead.
    stuck = Node(text="안 사라지는 창", attrs={"class": "x"},
                 children={browser_module._SE_POPUP_BUTTON: [Node(text="취소")]})
    target = Node(text="제목", blocker="div.overlay | 안 사라지는 창")
    locator = FakeLocator([target], 0)

    def always_blocked(timeout: float | None = None) -> None:
        del timeout
        raise RuntimeError("Locator.click: Timeout 20000ms exceeded.")

    locator.click = always_blocked        # type: ignore[method-assign]
    page = FramedPage([FakeFrame({browser_module._SE_POPUP: [stuck]})])

    with pytest.raises(RuntimeError, match="naver_blog_popup_persists_after_dismiss"):
        _worker(tmp_path)._naver_blog_click(locator, what="제목 영역", page=page)


def test_without_a_page_the_click_still_names_its_blocker(tmp_path: Path) -> None:
    # Callers that cannot supply a page keep the old behaviour: no retry, but
    # the error still says what ate the click.
    target = Node(text="제목", blocker="div.se-popup-dim | 무언가")
    locator = FakeLocator([target], 0)

    def blocked(timeout: float | None = None) -> None:
        del timeout
        raise RuntimeError("Locator.click: Timeout 20000ms exceeded.")

    locator.click = blocked               # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="naver_blog_click_intercepted"):
        _worker(tmp_path)._naver_blog_click(locator, what="제목 영역")


# ── the button row is not a button ───────────────────────────────────────────
class WrapperNode(Node):
    """A node that reports itself as containing other buttons."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.is_wrapper = True


class WrapperAwareLocator(FakeLocator):
    """evaluate() answers the wrapper question the way a browser would."""

    def nth(self, index: int) -> "WrapperAwareLocator":
        return WrapperAwareLocator(self.nodes, index)

    def locator(self, selector: str) -> "WrapperAwareLocator":
        # Children must stay wrapper-aware too: the button row is reached
        # through the popup's own locator, not the frame's.
        node = self._node()
        return WrapperAwareLocator(list(node.children.get(selector, [])) if node else [])

    def evaluate(self, script: str, *args: Any) -> Any:
        node = self._node()
        if "querySelectorAll" in script:
            return bool(getattr(node, "is_wrapper", False))
        return super().evaluate(script, *args)


class WrapperFrame(FakeFrame):
    def locator(self, selector: str) -> FakeLocator:
        return WrapperAwareLocator(list(self.nodes.get(selector, [])))


def test_the_row_holding_the_buttons_is_not_treated_as_a_button(tmp_path: Path) -> None:
    # Measured live 2026-08-05: `[class*='button']` also matched the row
    # wrapping 취소 and 확인, so the dialog reported a single button labelled
    # "취소 확인". Clicking it hit the gap between the real buttons, and the
    # dismisser looped three times reporting "취소 확인; 취소 확인; 취소 확인".
    cancel, ok = Node(text="취소"), Node(text="확인")
    row = WrapperNode(text="취소 확인")
    popup = Node(
        text="작성 중인 글이 있습니다. 이어서 작성하시겠습니까?",
        attrs={"class": "renamed"},
        children={browser_module._SE_POPUP_BUTTON: [row, cancel, ok]},
    )

    def hide() -> None:
        popup.visible = False

    cancel.on_click = hide
    ok.on_click = hide

    page = FramedPage([WrapperFrame({browser_module._SE_POPUP: [popup]})])
    dismissed = _worker(tmp_path)._naver_blog_dismiss_popups(page)

    assert dismissed[0]["button"] == "취소", "must press the real 취소, not the row"
    assert cancel.clicks == 1
    assert row.clicks == 0, "clicking the row lands between the buttons"
    assert ok.clicks == 0


def test_dropping_the_wrapper_still_leaves_it_a_confirm(tmp_path: Path) -> None:
    # The wrapper must not be counted toward "how many choices are there",
    # but two real buttons still make this a question, not an alert.
    cancel, ok = Node(text="취소"), Node(text="확인")
    row = WrapperNode(text="취소 확인")
    popup = Node(text="이어서 작성하시겠습니까?", attrs={"class": "renamed"},
                 children={browser_module._SE_POPUP_BUTTON: [row, cancel, ok]})
    for button in (cancel, ok):
        button.on_click = lambda: setattr(popup, "visible", False)

    page = FramedPage([WrapperFrame({browser_module._SE_POPUP: [popup]})])
    dismissed = _worker(tmp_path)._naver_blog_dismiss_popups(page)

    assert dismissed[0]["confirm"] is True


# ── an empty draft has different markup than one with content ───────────────
def test_the_body_falls_back_when_an_empty_draft_has_no_paragraph_yet(tmp_path: Path) -> None:
    # Measured 2026-08-05: the title typed in fine, then the body timed out.
    # SmartEditor only creates `.se-text-paragraph` once there is text, so on a
    # fresh post the original selector matched nothing -- and a click timeout
    # cannot tell that apart from "something is covering it".
    body = Node(text="")
    frame = FakeFrame({".se-main-container [contenteditable='true']": [body]})

    found = _worker(tmp_path)._first_present(
        frame,
        ".se-main-container .se-text-paragraph",      # absent on an empty draft
        ".se-main-container [contenteditable='true']",
        what="본문 영역",
    )

    assert found._node() is body


def test_the_precise_selector_still_wins_when_it_is_there(tmp_path: Path) -> None:
    paragraph, editable = Node(text="본문"), Node(text="")
    frame = FakeFrame({
        ".se-main-container .se-text-paragraph": [paragraph],
        ".se-main-container [contenteditable='true']": [editable],
    })

    found = _worker(tmp_path)._first_present(
        frame,
        ".se-main-container .se-text-paragraph",
        ".se-main-container [contenteditable='true']",
        what="본문 영역",
    )

    assert found._node() is paragraph


def test_every_selector_missing_names_all_of_them(tmp_path: Path) -> None:
    # "본문 영역을 못 찾음" alone sends the next person hunting for a popup.
    # Listing what was tried is what makes it fixable.
    frame = FakeFrame({})

    with pytest.raises(RuntimeError, match="naver_blog_element_missing:본문 영역"):
        _worker(tmp_path)._first_present(
            frame, ".se-a", ".se-b", what="본문 영역"
        )
