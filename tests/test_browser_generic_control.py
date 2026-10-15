"""Generic, site-agnostic browser control.

The Naver work proved a flow on one site. What did not transfer was the
foundation underneath it: the snapshot, the ref lookup and the text read all
saw the top document only, so any page that renders inside an iframe -- an
editor, a payment widget, an admin console -- reported "0 elements" and read as
broken rather than as unseen. These tests pin the frame-aware behaviour, and
that a dialog blocking a click is handled the same way everywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import browser as browser_module
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class El:
    """A DOM element as much as these handlers can tell one apart."""

    def __init__(
        self,
        *,
        tag: str = "button",
        text: str = "",
        attrs: dict[str, str] | None = None,
        visible: bool = True,
        disabled: bool = False,
        box: dict[str, float] | None = None,
        click_error: Exception | None = None,
        blocker: str = "",
        children: dict[str, list["El"]] | None = None,
        on_click: Any = None,
    ) -> None:
        self.children = children or {}
        self.on_click = on_click
        self.tag = tag
        self.text = text
        self.attrs = attrs or {}
        self.visible = visible
        self.disabled = disabled
        self.box = box
        self.click_error = click_error
        self.blocker = blocker
        self.ref = ""
        self.clicks = 0


class Loc:
    def __init__(self, elements: list[El], index: int | None = None) -> None:
        self.elements = elements
        self.index = index

    def count(self) -> int:
        return len(self.elements)

    def nth(self, index: int) -> "Loc":
        # type(self) 로 만드는 이유: 하위 클래스(폼 입력을 흉내 내는 것 등)가 .first /
        # .nth 를 거치는 순간 기반 클래스로 되돌아가면, 실제 코드가 쓰는 메서드가
        # 사라져 테스트가 엉뚱한 AttributeError 로 죽는다.
        return type(self)(self.elements, index)

    @property
    def first(self) -> "Loc":
        return self.nth(0)

    def _el(self) -> El | None:
        position = self.index or 0
        return self.elements[position] if position < len(self.elements) else None

    def is_visible(self) -> bool:
        element = self._el()
        return bool(element and element.visible)

    def is_disabled(self) -> bool:
        element = self._el()
        return bool(element and element.disabled)

    def inner_text(self, timeout: float | None = None) -> str:
        del timeout
        element = self._el()
        if element is None:
            raise RuntimeError("Timeout exceeded: element not found")
        return element.text

    def get_attribute(self, name: str) -> str | None:
        element = self._el()
        return element.attrs.get(name) if element else None

    def bounding_box(self) -> dict[str, float] | None:
        element = self._el()
        return element.box if element else None

    def evaluate(self, script: str, *args: Any) -> Any:
        element = self._el()
        if element is None:
            return ""
        # Order matters: the interception probe also mentions tagName, and
        # answering it with the element's own tag makes every failed click look
        # intercepted -- which quietly passed a test that meant to check the
        # opposite branch.
        if "elementFromPoint" in script:
            return element.blocker
        if "setAttribute" in script:
            element.ref = str(args[0]) if args else ""
            return None
        if "tagName" in script:
            return element.tag
        return element.blocker

    def click(self, timeout: float | None = None) -> None:
        del timeout
        element = self._el()
        if element is None:
            raise RuntimeError("Locator.click: Timeout 20000ms exceeded.")
        if element.click_error is not None:
            raise element.click_error
        element.clicks += 1
        if element.on_click is not None:
            element.on_click()

    def locator(self, selector: str) -> "Loc":
        element = self._el()
        return Loc(list(element.children.get(selector, [])) if element else [])


class Frame:
    def __init__(
        self,
        *,
        name: str = "",
        url: str = "",
        elements: list[El] | None = None,
        body: str = "",
        extra: dict[str, list[El]] | None = None,
    ) -> None:
        self.name = name
        self.url = url
        self.elements = elements or []
        self.body = body
        self.extra = extra or {}

    def locator(self, selector: str) -> Loc:
        if selector == browser_module._INTERACTIVE:
            return Loc(list(self.elements))
        if selector == "body":
            return Loc([El(tag="body", text=self.body)])
        if selector.startswith('[data-jarvis-ref='):
            wanted = selector.split('"')[1]
            return Loc([e for e in self.elements if e.ref == wanted])
        return Loc(list(self.extra.get(selector, [])))


class Page:
    def __init__(self, frames: list[Frame], *, url: str = "https://example.test/") -> None:
        self.frames = frames
        self.url = url
        self.waits = 0
        self.shots: list[str] = []
        self.wait_error: Exception | None = None

    def locator(self, selector: str) -> Loc:
        # 진짜 Page 는 최상위 프레임의 locator 를 그대로 노출한다. 이게 없으면
        # page.locator("body") 를 쓰는 코드가 조용히 예외로 빠져 검사 자체가 무력해진다.
        return self.frames[0].locator(selector)

    def title(self) -> str:
        return "테스트 페이지"

    def is_closed(self) -> bool:
        return getattr(self, "closed", False)

    def wait_for_timeout(self, milliseconds: int) -> None:
        del milliseconds
        self.waits += 1
        if self.wait_error is not None:
            raise self.wait_error

    def wait_for_load_state(self, state: str, timeout: int | None = None) -> None:
        del state, timeout

    def evaluate(self, script: str, *args: Any) -> Any:
        del script, args
        return 0

    def screenshot(self, path: str, full_page: bool = False, **options: object) -> None:
        # 2026-08-14: 진짜 워커가 `animations="disabled"`·`caret`·`timeout` 을 같이
        # 넘긴다(쿠팡 상세에서 스크린샷이 20초씩 타임아웃 나던 것을 잡느라). 가짜가
        # 그걸 못 받으면 **실패 증거 저장이 통째로 조용히 사라진다** — 실제로 그렇게
        # 깨졌다. 옵션은 안 쓰더라도 받아는 준다.
        del full_page, options
        Path(path).write_bytes(b"PNG")
        self.shots.append(path)


def _worker(tmp_path: Path, *, read_only: bool = False) -> BrowserWorker:
    """이 파일의 기본은 **쓰기 가능**이다.

    여기서 보는 것은 권한이 아니라 구조(프레임 인지 ref·증거 검증·대화상자 처리)다.
    읽기 전용을 기본으로 두면 '저장' 같은 평범한 버튼이 권한에서 막혀, 정작 확인하려던
    증거 검증에 도달하지 못한다. 권한 경계 자체는 test_browser_forms.py 가 맡는다.
    """
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_visual_overlay=False,
            browser_read_only=read_only,
            browser_evidence_dir=tmp_path / "evidence",
        )
    )


def test_read_only_still_blocks_a_save_button(tmp_path: Path) -> None:
    # 위 기본값이 쓰기 가능이라, 읽기 전용이 실제로 막는다는 사실을 여기서 못박아 둔다.
    button = El(text="저장")
    page = Page([Frame(elements=[button])])
    worker = _worker(tmp_path, read_only=True)
    worker._snapshot(page, {})

    with pytest.raises(RuntimeError, match="read_only_action_blocked"):
        worker._click(page, {"ref": button.ref})
    assert button.clicks == 0


# ── the snapshot must reach inside frames ────────────────────────────────────
def test_snapshot_lists_elements_from_every_frame_not_just_the_top_document(
    tmp_path: Path,
) -> None:
    """The exact blind spot behind '페이지 요소 0개'. The editor really was
    there; the snapshot was reading the wrong document."""
    page = Page(
        [
            Frame(name="", url="https://example.test/", elements=[El(text="로그인")]),
            Frame(
                name="mainFrame",
                url="https://example.test/editor",
                elements=[El(text="제목"), El(text="본문")],
            ),
        ]
    )

    result = _worker(tmp_path)._snapshot(page, {})

    names = [item["name"] for item in result["elements"]]
    assert names == ["로그인", "제목", "본문"]
    assert result["frame_count"] == 2
    # 본문 프레임은 기본이라 적지 않는다(2026-10-07) — 다른 프레임의 것만 이름표를 단다.
    assert [item.get("frame", "main") for item in result["elements"]] == ["main", "mainFrame", "mainFrame"]


def test_snapshot_refs_stay_unique_across_frames(tmp_path: Path) -> None:
    # Two frames numbering their own elements from j1 would make a ref
    # ambiguous, and the lookup below resolves by attribute alone.
    page = Page(
        [
            Frame(elements=[El(text="A")]),
            Frame(name="side", elements=[El(text="B"), El(text="C")]),
        ]
    )

    result = _worker(tmp_path)._snapshot(page, {})

    refs = [item["ref"] for item in result["elements"]]
    assert refs == ["j1", "j2", "j3"]
    assert len(set(refs)) == len(refs)


def test_snapshot_skips_invisible_elements(tmp_path: Path) -> None:
    page = Page([Frame(elements=[El(text="보임"), El(text="숨김", visible=False)])])

    result = _worker(tmp_path)._snapshot(page, {})

    assert [item["name"] for item in result["elements"]] == ["보임"]


def test_boxes_are_only_measured_when_asked_for(tmp_path: Path) -> None:
    # A bounding box costs a round trip per element. The vision path needs
    # them; a plain snapshot must not pay for them.
    element = El(text="저장", box={"x": 10.6, "y": 20.2, "width": 80.0, "height": 30.0})
    page = Page([Frame(elements=[element])])
    worker = _worker(tmp_path)

    assert "box" not in worker._snapshot(page, {})["elements"][0]

    boxed = worker._snapshot(page, {"include_box": True})["elements"][0]
    assert boxed["box"] == {"x": 10, "y": 20, "width": 80, "height": 30}


# ── a ref must resolve in whichever frame stamped it ─────────────────────────
def test_a_ref_stamped_inside_an_iframe_can_still_be_clicked(tmp_path: Path) -> None:
    """Snapshot and click disagreeing about which document to look in is a
    silent dead end: the element is listed, then reported stale."""
    target = El(text="임시저장")
    page = Page([Frame(elements=[El(text="로그인")]), Frame(name="mainFrame", elements=[target])])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    worker._click(page, {"ref": target.ref})

    assert target.clicks == 1


def test_a_ref_that_no_longer_exists_says_to_take_a_new_snapshot(tmp_path: Path) -> None:
    page = Page([Frame(elements=[El(text="A")])])
    with pytest.raises(RuntimeError, match="stale_element_ref"):
        _worker(tmp_path)._click(page, {"ref": "j7"})


def test_a_malformed_ref_is_rejected_before_touching_the_page(tmp_path: Path) -> None:
    page = Page([Frame(elements=[El(text="A")])])
    with pytest.raises(ValueError, match="invalid_element_ref"):
        _worker(tmp_path)._click(page, {"ref": "'; DROP"})


# ── reading text must not stop at the top document ───────────────────────────
def test_read_includes_iframe_text_so_an_embedded_page_is_not_empty(
    tmp_path: Path,
) -> None:
    page = Page(
        [
            Frame(body="머리말"),
            Frame(name="mainFrame", body="여기가 실제 본문이다"),
        ]
    )

    result = _worker(tmp_path)._read(page, {})

    assert "머리말" in result["text"]
    assert "여기가 실제 본문이다" in result["text"]
    assert "[mainFrame]" in result["text"], "which frame said what must survive"


def test_read_with_a_selector_skips_frames_that_do_not_have_it(tmp_path: Path) -> None:
    wanted = El(text="본문 문단")
    page = Page(
        [
            Frame(body="머리말"),
            Frame(name="mainFrame", body="편집기", extra={".se-text-paragraph": [wanted]}),
        ]
    )

    result = _worker(tmp_path)._read(page, {"selector": ".se-text-paragraph"})

    assert "본문 문단" in result["text"]
    assert "머리말" not in result["text"]


# ── dialogs are handled the same way on every site ───────────────────────────
def _dialog(text: str, buttons: list[El], *, klass: str = "cookie-consent") -> El:
    """A dialog that answers when a button is pressed, as a real one does."""
    popup = El(
        text=text,
        attrs={"class": klass},
        children={browser_module._SE_POPUP_BUTTON: buttons},
    )

    def hide() -> None:
        popup.visible = False

    for button in buttons:
        button.on_click = hide
    return popup


def test_a_consent_dialog_on_an_ordinary_site_is_cleared_with_its_negative_button(
    tmp_path: Path,
) -> None:
    """Nothing about this is Naver-shaped -- a cookie banner blocks a click the
    same way SmartEditor's draft-restore confirm did, and the rule for
    answering it is the same: only the negative button, ever."""
    reject, accept = El(text="거부"), El(text="동의")
    popup = _dialog("쿠키 사용에 동의하시겠습니까?", [reject, accept])
    page = Page([Frame(extra={browser_module._SE_POPUP: [popup]})])

    dismissed = _worker(tmp_path)._dismiss_dialogs(page)

    assert [record["button"] for record in dismissed] == ["거부"]
    assert accept.clicks == 0, "the positive button must never be pressed for us"
    assert popup.visible is False


def test_a_dialog_with_no_negative_button_stops_and_quotes_its_wording(
    tmp_path: Path,
) -> None:
    """Guessing 확인 on an unknown confirm is how a dismisser becomes a
    publisher. Stopping is the safe answer even though it blocks the task."""
    popup = _dialog("결제를 진행하시겠습니까?", [El(text="결제"), El(text="계속")])
    page = Page([Frame(extra={browser_module._SE_POPUP: [popup]})])

    with pytest.raises(RuntimeError) as failure:
        _worker(tmp_path)._dismiss_dialogs(page)

    assert "browser_popup_blocking" in str(failure.value)
    assert "결제를 진행하시겠습니까?" in str(failure.value)
    assert popup.visible is True


def test_a_generic_click_names_itself_not_the_blog_when_something_eats_it(
    tmp_path: Path,
) -> None:
    """`naver_blog_click_intercepted` on 쿠팡 would send the next reader looking
    at blog code. The prefix has to follow the caller."""
    element = El(
        text="결제하기",
        click_error=RuntimeError("Locator.click: Timeout 20000ms exceeded."),
        blocker="div.overlay | 로그인이 필요합니다",
    )
    locator = Loc([element], 0)

    with pytest.raises(RuntimeError) as failure:
        _worker(tmp_path)._guarded_click(locator, what="결제하기")

    assert str(failure.value).startswith("browser_click_intercepted:결제하기:")


def test_a_dialog_in_another_frame_still_triggers_recovery(tmp_path: Path) -> None:
    """Found live, 2026-08-05, on a page nothing had ever seen.

    `elementFromPoint` runs inside the *element's* document. When the target is
    in an iframe and the dialog is in the top document, the target reports
    nothing on top of it -- so keying recovery off "can we name the blocker"
    left the click looking like a plain 20-second timeout, with the dialog
    sitting right there. Recovery has to ask "is there a dialog anywhere".
    """
    attempts = {"n": 0}
    cancel = El(text="취소")
    popup = _dialog("이전에 작성 중이던 내용이 있습니다", [cancel, El(text="불러오기")])
    target = El(text="저장", blocker="")  # invisible blocker: different document
    locator = Loc([target], 0)

    def flaky(timeout: float | None = None) -> None:
        del timeout
        attempts["n"] += 1
        if attempts["n"] == 1 or popup.visible:
            raise RuntimeError("Locator.click: Timeout 20000ms exceeded.")

    locator.click = flaky  # type: ignore[method-assign]
    page = Page([Frame(extra={browser_module._SE_POPUP: [popup]}), Frame(name="workFrame")])

    _worker(tmp_path)._guarded_click(locator, what="저장", page=page)

    assert attempts["n"] == 2, "should clear the dialog and retry exactly once"
    assert popup.visible is False


def test_a_click_that_fails_with_no_dialog_anywhere_is_not_blamed_on_a_popup(
    tmp_path: Path,
) -> None:
    # The other side of the same branch: without a dialog, this is a real
    # failure and must say so instead of dismissing nothing and retrying.
    target = El(text="저장", blocker="", click_error=RuntimeError("Timeout 20000ms exceeded."))
    page = Page([Frame(elements=[target])])

    with pytest.raises(RuntimeError, match="browser_click_failed:저장"):
        _worker(tmp_path)._guarded_click(Loc([target], 0), what="저장", page=page)


def test_the_editor_flow_keeps_its_own_error_names(tmp_path: Path) -> None:
    element = El(
        text="제목",
        click_error=RuntimeError("Locator.click: Timeout 20000ms exceeded."),
        blocker="div.se-popup-dim | 이전에 작성 중이던 글",
    )

    with pytest.raises(RuntimeError, match="naver_blog_click_intercepted"):
        _worker(tmp_path)._naver_blog_click(Loc([element], 0), what="제목 영역")


# ── a failure leaves evidence behind ─────────────────────────────────────────
def test_a_failed_step_saves_a_screenshot_and_a_per_frame_dump(tmp_path: Path) -> None:
    """The expensive part of the 2026-08-03~05 chase was reconstructing the
    state each failure had been in, not fixing anything."""
    page = Page([Frame(elements=[El(text="저장")]), Frame(name="mainFrame")])
    page.wait_error = RuntimeError("Locator.click: Timeout 20000ms exceeded.")
    worker = _worker(tmp_path)
    worker._page = page
    worker._current_page = lambda: page  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        worker._execute("browser_wait", {})

    failure = worker.status()["last_failure"]
    assert Path(failure["screenshot"]).exists()
    assert [frame["name"] for frame in failure["frames"]] == ["main", "mainFrame"]
    assert "Timeout" in failure["error"]


def test_errors_that_say_nothing_about_the_page_do_not_cost_a_screenshot(
    tmp_path: Path,
) -> None:
    # A malformed ref is fully described by its own message. Capturing evidence
    # for it only adds latency to every mistake the model makes.
    page = Page([Frame(elements=[El(text="저장")])])
    worker = _worker(tmp_path)
    worker._page = page
    worker._current_page = lambda: page  # type: ignore[method-assign]

    with pytest.raises(ValueError):
        worker._execute("browser_click", {"ref": "nope"})

    assert page.shots == []
    assert worker.status()["last_failure"] == {}


# ── an action is only done when the screen says so ───────────────────────────
class CountingFrame(Frame):
    """A frame whose counter goes up the first time the button is pressed --
    the shape of a real save: the proof arrives after the click, not with it."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.counter = El(text="저장 3")

    def locator(self, selector: str) -> Loc:
        if selector == ".save_count":
            return Loc([self.counter])
        return super().locator(selector)


def test_a_click_with_no_expectation_stays_silent_about_verification(
    tmp_path: Path,
) -> None:
    # Most clicks change nothing worth proving. Reporting `verified: false` for
    # those would train everyone to ignore the field.
    page = Page([Frame(elements=[El(text="다음")])])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._click(page, {"ref": "j1"})

    assert "verified" not in result


def test_a_counter_that_goes_up_is_the_proof_a_save_landed(tmp_path: Path) -> None:
    """The generalized `draft_count:3->4`. Naver proved the shape; nothing about
    it is Naver's."""
    frame = CountingFrame()
    save = El(text="저장", on_click=lambda: setattr(frame.counter, "text", "저장 4"))
    frame.elements = [save]
    page = Page([frame])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._click(
        page,
        {"ref": "j1", "expect": {"kind": "number_increases", "selector": ".save_count"}},
    )

    assert result["verified"] is True
    assert result["verification"]["evidence"] == "number:3->4"


def test_a_click_that_changes_nothing_is_unknown_not_success(tmp_path: Path) -> None:
    """The whole point. A button that was pressed and did nothing must not come
    back as done -- that is the exact false report this replaces.

    `unknown` 은 2026-08-05 저녁에 `unchanged`/`changed_otherwise` 둘로 갈렸다.
    여기서 확인하는 것은 이름이 아니라 성질이다: 성공이 아니고, 재시도도 아니다.
    (이 픽스처는 정말로 아무것도 안 바뀌는 화면이라 `unchanged` 쪽이다.)
    """
    frame = CountingFrame(elements=[El(text="저장")])
    page = Page([frame])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._click(
        page,
        {
            "ref": "j1",
            "expect": {"kind": "number_increases", "selector": ".save_count"},
            "verify_timeout_ms": 600,
        },
    )

    assert result["verified"] is False
    assert result["verification"]["status"] == "unchanged"
    assert result["verification"]["evidence"] == ""
    assert result["verification"]["changes"] == []


def test_unknown_is_reported_once_and_never_retried_by_the_tool(tmp_path: Path) -> None:
    # Retrying here is how one save becomes two posts. The tool reports and
    # stops; deciding what to do next is the caller's, with a person in it.
    frame = CountingFrame(elements=[El(text="저장")])
    page = Page([frame])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    worker._click(
        page,
        {"ref": "j1", "expect": {"kind": "number_increases", "selector": ".save_count"},
         "verify_timeout_ms": 600},
    )

    assert frame.elements[0].clicks == 1


def test_a_toast_appearing_counts_as_proof(tmp_path: Path) -> None:
    frame = Frame(body="저장 중", elements=[El(text="저장")])
    frame.elements[0].on_click = lambda: setattr(frame, "body", "저장되었습니다")
    page = Page([frame])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._click(
        page,
        {"ref": "j1", "expect": {"kind": "text_appears", "value": "저장되었습니다"}},
    )

    assert result["verified"] is True


def test_an_expectation_that_needs_a_baseline_is_refused_standalone(
    tmp_path: Path,
) -> None:
    # "숫자가 올랐나"를 나중에 혼자 물으면 무엇과 비교할지가 없다. 조용히
    # 0과 비교하면 아무 저장도 안 했는데 성공으로 읽힌다.
    page = Page([CountingFrame()])
    with pytest.raises(ValueError, match="expectation_needs_a_baseline"):
        _worker(tmp_path)._verify(
            page, {"expect": {"kind": "number_increases", "selector": ".save_count"}}
        )


def test_an_unknown_expectation_kind_is_rejected_rather_than_ignored(
    tmp_path: Path,
) -> None:
    # Silently treating a typo'd kind as "satisfied" would hand back a
    # verification that proves nothing.
    page = Page([Frame(elements=[El(text="저장")])])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    with pytest.raises(ValueError, match="unknown_expectation"):
        worker._click(page, {"ref": "j1", "expect": {"kind": "저장됨"}})


# ── 봇 확인 화면은 알아보고 멈춘다 (푸는 게 아니라) ──────────────────────────
@pytest.mark.parametrize(
    "body",
    [
        "마지막 한 단계 계속하려면 아래 과제 해결 확인 중…",
        "사람인지 확인하고 있습니다",
        "Checking your browser before you continue",
        "One more step — solve the challenge",
        "로봇이 아닙니다",
    ],
)
def test_a_bot_check_is_recognised_as_a_block(body: str) -> None:
    """알아보지 못하는 게 더 나쁘다: 검사 화면을 검색 결과로 읽어 없는 사실을 지어낸다.
    2026-08-05 사용자님 화면의 Bing 한국어 문구 3종이 목록에 하나도 없었다."""
    page = Page([Frame(body=body)])
    assert BrowserWorker._search_blocked(page) is True


def test_an_ordinary_result_page_is_not_mistaken_for_a_block(tmp_path: Path) -> None:
    del tmp_path
    page = Page([Frame(body="검색 결과 1,240건 — 에듀테크 시장 동향 보고서")])
    assert BrowserWorker._search_blocked(page) is False


def test_the_probe_can_show_what_a_selector_actually_matched(tmp_path: Path) -> None:
    # A count answers "does it hit anything", never "is it hitting the thing I
    # mean" -- which is the question that followed every single time.
    page = Page(
        [
            Frame(
                name="mainFrame",
                extra={
                    ".se-text-paragraph": [
                        El(text="제목입니다", box={"x": 0, "y": 0, "width": 10, "height": 5}),
                        El(text="본문입니다"),
                    ]
                },
            )
        ]
    )

    result = _worker(tmp_path)._probe_frames(
        page, {"selectors": [".se-text-paragraph"], "samples": True}
    )

    frame = result["frames"][0]
    assert frame["counts"][".se-text-paragraph"] == 2
    assert [s["text"] for s in frame["samples"][".se-text-paragraph"]] == [
        "제목입니다",
        "본문입니다",
    ]


# ── 화면 읽기는 브라우저 안에서 한 번에 (2026-08-10) ─────────────────────────
#
# 요소 하나마다 is_visible·evaluate·get_attribute×6·is_disabled 로 **열두 번씩**
# 왕복하고 있었다. 네이버 검색 한 화면이 요소 494개·프레임 5개라 왕복이 수천 번이
# 되고, 한 번에 8~10ms 라 그것만으로 50초다. 실측:
#
#     browser_open      1.1초
#     browser_snapshot 53.5초  →  0.5초 (같은 화면, 같은 120개, 전 항목 일치)
#     browser_search   70.0초
#
# 조사가 느린 진짜 이유가 검색 엔진도 네트워크도 아니라 여기였다.
class FastFrame(Frame):
    """`evaluate` 로 한 번에 훑어 주는 프레임(진짜 브라우저와 같은 모양)."""

    def __init__(self, payload: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.payload = payload
        self.evaluate_calls = 0

    def evaluate(self, script: str, *args: Any) -> Any:
        del args
        self.evaluate_calls += 1
        self.script = script
        return [dict(item) for item in self.payload]


class BlindFrame(Frame):
    """evaluate 를 막는 페이지(CSP 등). 느린 길로 돌아가야 한다."""

    def evaluate(self, script: str, *args: Any) -> Any:
        del script, args
        raise RuntimeError("evaluate_blocked")


def test_the_snapshot_reads_each_frame_in_one_round_trip(tmp_path: Path) -> None:
    frames = [
        FastFrame(
            [{"ref": "j1", "role": "link", "name": "로그인", "tag": "a", "type": "", "disabled": False}],
            name="",
            url="https://example.test/",
        ),
        FastFrame(
            [{"ref": "j2", "role": "button", "name": "저장", "tag": "button", "type": "", "disabled": False}],
            name="mainFrame",
            url="https://example.test/editor",
        ),
    ]

    result = _worker(tmp_path)._snapshot(Page(frames), {})

    assert [item["name"] for item in result["elements"]] == ["로그인", "저장"]
    # 프레임 이름표는 파이썬 쪽 것이다 — 브라우저 안에서는 자기가 몇 번째인지 모른다.
    # 2026-10-07: 본문 프레임은 기본이라 적지 않는다(요소마다 35자) — 다른 프레임의 것만 이름표를 단다.
    assert [item.get("frame", "main") for item in result["elements"]] == ["main", "mainFrame"]
    assert [item.get("frame_index", 0) for item in result["elements"]] == [0, 1]
    assert [frame.evaluate_calls for frame in frames] == [1, 1], "프레임당 한 번이어야 한다"


def test_a_page_that_blocks_evaluate_still_gets_read(tmp_path: Path) -> None:
    """빠른 길이 막히면 **못 읽는 게 아니라 느리게 읽는다.**

    이 폴백이 죽어 있으면 CSP 걸린 페이지에서 요소 0개가 나오고, 그건 이 저장소가
    여러 번 데인 바로 그 고장이다("빈 페이지"와 구별되지 않는다).
    """
    page = Page([BlindFrame(name="", url="https://example.test/", elements=[El(text="로그인")])])

    result = _worker(tmp_path)._snapshot(page, {})

    assert [item["name"] for item in result["elements"]] == ["로그인"]


def test_the_fast_path_still_stamps_refs(tmp_path: Path) -> None:
    """ref 는 나중에 클릭·입력할 때 다시 찾는 주소다.

    브라우저 안에서 훑도록 바꾸면서 `data-jarvis-ref` 를 안 찍으면 스냅샷만 빨라지고
    **조작이 통째로 깨진다** — 화면은 잘 보이는데 아무것도 못 누르게 된다.
    """
    frame = FastFrame(
        [{"ref": "j1", "role": "button", "name": "저장", "tag": "button", "type": "", "disabled": False}],
        name="",
        url="https://example.test/",
    )

    result = _worker(tmp_path)._snapshot(Page([frame]), {})

    assert result["elements"][0]["ref"] == "j1"
    # 가짜 프레임에는 DOM 이 없으므로, 브라우저로 **보내는 스크립트**가 실제로 그
    # 도장을 찍는지를 본다. 이게 빠지면 화면은 잘 보이는데 아무것도 못 누른다.
    assert "setAttribute(\"data-jarvis-ref\", ref)" in frame.script


# ── 클릭이 새 창을 열면 그 창으로 옮겨 탄다 (2026-08-10) ─────────────────────
#
# 사용자님 지적: "위시켓에서 구글로 로그인이 안 된다." 실제로 가서 보니 **구글은
# 아무것도 막고 있지 않았다** — 로그인 화면이 멀쩡히 떠 있었다. 다만 새 창에.
#
#     탭 0  auth.wishket.com/login    ← 자비스가 보던 곳
#     탭 1  accounts.google.com/...   ← 실제로 일이 벌어지는 곳
#
# 자비스는 "주소가 그대로다 = 아무 일도 안 일어났다"고 읽었고, 사람 눈에는 큰 창
# 뒤에 가려 "눌러도 안 넘어간다"로 보였다. OAuth·결제·본인확인이 전부 이 모양이라
# 한 사이트의 문제가 아니다.
class PoppingPage(Page):
    """누르면 새 창이 열리는 화면. 원래 창은 그대로다(OAuth 가 하는 그대로)."""

    def __init__(self, frames: list[Frame], popup: Page) -> None:
        super().__init__(frames)
        self.popup = popup


class Ctx:
    """창 목록을 들고 있는 가짜 컨텍스트."""

    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages


def _worker_with_windows(tmp_path: Path, pages: list[Any]) -> BrowserWorker:
    worker = _worker(tmp_path)
    worker._context = Ctx(pages)
    return worker


def test_a_click_that_opens_a_window_moves_there(tmp_path: Path) -> None:
    first = Page([Frame(name="", url="https://auth.wishket.com/login", elements=[El(text="구글로 로그인")])])
    popup = Page([Frame(name="", url="https://accounts.google.com/signin", elements=[El(text="이메일")])])
    popup.url = "https://accounts.google.com/signin"
    worker = _worker_with_windows(tmp_path, [first])
    worker._page = first

    # 클릭 도중에 창이 하나 늘어난다 — 실제 팝업과 같은 순서다.
    worker._context.pages.append(popup)
    opened = worker._adopt_new_window([first])

    assert opened is not None, "새 창이 열렸는데 못 봤다 — 여기가 위시켓에서 죽던 자리다"
    assert "accounts.google.com" in opened["url"]
    assert worker._page is popup, "따라가지 않으면 스냅샷도 추출도 엉뚱한 창을 본다"


def test_no_new_window_means_no_switch(tmp_path: Path) -> None:
    """대부분의 클릭은 창을 안 연다. 그때 엉뚱한 창으로 옮겨 타면 더 나쁘다."""
    only = Page([Frame(name="", url="https://example.test/", elements=[El(text="확인")])])
    worker = _worker_with_windows(tmp_path, [only])
    worker._page = only

    assert worker._adopt_new_window([only], wait_ms=0) is None
    assert worker._page is only


def test_a_closed_window_is_not_adopted(tmp_path: Path) -> None:
    """닫힌 창으로 옮겨 타면 그 다음 호출이 통째로 죽는다."""
    first = Page([Frame(name="", url="https://example.test/", elements=[El(text="열기")])])
    ghost = Page([Frame(name="", url="https://example.test/gone", elements=[])])
    ghost.closed = True
    worker = _worker_with_windows(tmp_path, [first, ghost])
    worker._page = first

    assert worker._adopt_new_window([first], wait_ms=0) is None
    assert worker._page is first


# ── 눈에 보이는데 태그로는 안 걸리는 것들 (2026-08-11) ───────────────────────
#
# 사용자님 지적: "자비스가 글 넣는 건 잘하는데 클릭을 못한다."
# 위시켓 보유기술 화면 실측 — 자비스가 본 것은 요소 65개, **전부 <a>(64)+button(1)**.
# 화면에는 수정(연필) 아이콘 5개와 '보유기술 추가' 버튼이 멀쩡히 보이는데 목록에
# 하나도 없었다. 못 누른 게 아니라 **처음부터 안 보였다** — 그래서 모델은 후보 중
# 제일 그럴듯한 저장 버튼을 골랐다.
#
# 요즘 웹은 <div onclick> 과 <li> 로 조작 요소를 만든다. 선택자를 사이트마다 늘리는
# 것은 두더지 잡기이므로, **사람에게 클릭하라고 알리는 신호**로 판정한다:
# 손가락 커서 · role · tabindex · onclick. (로그인 문을 문구가 아니라 구조로 본 것과 같다)
#
# 고친 뒤 같은 화면: 105개 · 연필 5개 이름까지 붙음 · 이름없음 27→2 · 234ms
def _fast_script(tmp_path: Path) -> str:
    """실제로 브라우저에 보내는 스크립트를 붙잡아 온다."""
    frame = FastFrame([], name="", url="https://example.test/")
    worker = _worker(tmp_path)
    worker._frame_elements_fast(frame, frame_label="main", frame_index=0, budget=10, start=0, include_box=False)
    return frame.script


def test_it_looks_for_click_signals_not_just_tags(tmp_path: Path) -> None:
    script = _fast_script(tmp_path)

    assert 'cursor === "pointer"' in script, "손가락 커서가 제일 일반적인 클릭 신호다"
    assert "onclick" in script and "tabindex" in script
    for role in ("option", "listitem", "menuitem"):
        assert role in script, f"{role} 은 드롭다운·목록에서 클릭 대상이다"


def test_an_icon_button_without_a_label_is_still_offered(tmp_path: Path) -> None:
    """위시켓 수정 버튼은 24×24 에 글자가 없다. 이름으로만 거르면 통째로 사라진다."""
    script = _fast_script(tmp_path)

    assert "iconSized" in script
    assert "64" in script and "12" in script, "아이콘 크기 범위가 있어야 한다"


def test_invisible_leftovers_are_not_offered(tmp_path: Path) -> None:
    """닫힌 달력이 opacity:0 으로 남아 있었다 — 안 거르면 날짜 칸 43개가 목록을 채운다."""
    script = _fast_script(tmp_path)

    assert "opacity" in script


def test_a_nameless_element_borrows_the_name_of_its_row(tmp_path: Path) -> None:
    """★ 목록에 담아 놓고 이름을 안 주면 안 담은 것과 같다.

    실측에서 이름 없는 img 가 27개 나왔다. 모델은 그중 무엇이 'Python 수정'인지
    알 방법이 없다. alt 를 읽고, 그것도 없으면 그 줄의 글을 빌려 온다 —
    사람도 "Python 줄의 연필"이라고 알아본다.
    """
    script = _fast_script(tmp_path)

    assert 'getAttribute("alt")' in script, "아이콘이 <img> 인 사이트가 많다"
    assert "안의" in script, "줄의 글을 빌려 오는 폴백이 있어야 한다"


# ── 타이핑해서 뜬 목록에서 고르기 (2026-08-11) ───────────────────────────────
#
# 사용자님이 위시켓 보유기술에서 겪은 것: 자비스가 `Python` 을 치는 데까지는 했는데
# 밑에 뜬 목록을 못 눌러 결국 손으로 하셨다. 도구는 다 있었다(채우기·스냅샷·클릭).
# 없던 것은 **순서**다 — 채우고 → 뜰 때까지 기다리고 → **다시 찍고** → 고른다.
# 모델에게 매번 알아서 하라고 두면 낡은 스냅샷의 저장 버튼을 누른다.
def test_the_exact_match_wins_over_a_longer_name(tmp_path: Path) -> None:
    """★ `Java` 로 찾을 때 `JavaScript` 가 먼저 걸리면 엉뚱한 게 등록된다.

    그리고 사람은 그걸 한참 뒤에 발견한다 — 조용히 틀리는 쪽이 제일 나쁘다.
    """
    items = [
        {"ref": "j1", "tag": "div", "name": "JavaScript 1200"},
        {"ref": "j2", "tag": "div", "name": "Java 480"},
    ]
    picked = BrowserWorker._match_suggestion(items, "Java")

    assert picked is not None and picked["ref"] == "j2"


def test_it_falls_back_to_a_prefix_then_contains(tmp_path: Path) -> None:
    items = [{"ref": "j9", "tag": "div", "name": "playwright 483"}]

    assert BrowserWorker._match_suggestion(items, "playwright")["ref"] == "j9"
    assert BrowserWorker._match_suggestion(items, "483")["ref"] == "j9"
    assert BrowserWorker._match_suggestion(items, "selenium") is None


def test_nothing_matching_means_nothing_is_clicked(tmp_path: Path) -> None:
    """비슷해 보이는 다른 것을 누르는 게 이 기능에서 제일 나쁜 실패다."""
    items = [{"ref": "j1", "tag": "div", "name": "저장"}, {"ref": "j2", "tag": "div", "name": "취소"}]

    assert BrowserWorker._match_suggestion(items, "Python") is None


def test_a_nameless_row_is_never_matched(tmp_path: Path) -> None:
    """이름 없는 요소가 빈 문자열로 아무거나 맞아 버리면 안 된다."""
    items = [{"ref": "j1", "tag": "div", "name": ""}, {"ref": "j2", "tag": "div", "name": None}]

    assert BrowserWorker._match_suggestion(items, "Python") is None
    assert BrowserWorker._match_suggestion(items, "") is None


def test_the_count_tag_after_a_name_does_not_confuse_the_match(tmp_path: Path) -> None:
    """자동완성은 이름 뒤에 숫자를 달고 온다(위시켓은 보유자 수). 꼬리표는 뗀다."""
    assert BrowserWorker._suggestion_head("Java 480") == "java"
    assert BrowserWorker._suggestion_head("JavaScript 1,200") == "javascript"
    assert BrowserWorker._suggestion_head("C++") == "c++"


def test_a_word_boundary_keeps_java_from_matching_javascript(tmp_path: Path) -> None:
    """★ 이게 없으면 조용히 엉뚱한 태그가 등록된다."""
    items = [
        {"ref": "j1", "tag": "div", "name": "JavaScript 1200"},
        {"ref": "j2", "tag": "div", "name": "Java SE 8"},
    ]
    picked = BrowserWorker._match_suggestion(items, "Java")

    assert picked["ref"] == "j2", "JavaScript 가 아니라 Java 계열을 골라야 한다"


def test_the_same_screen_always_gives_the_same_pick(tmp_path: Path) -> None:
    """결정론 — 같은 화면에서 두 번 부르면 두 번 다 같아야 한다."""
    items = [
        {"ref": "j1", "tag": "div", "name": "Python 900"},
        {"ref": "j2", "tag": "div", "name": "Python 3 120"},
        {"ref": "j3", "tag": "div", "name": "'Python' 선택"},
    ]
    picks = {BrowserWorker._match_suggestion(items, "Python")["ref"] for _ in range(5)}

    assert picks == {"j1"}, "동점이면 화면에 먼저 나온 것 — 매번 같아야 한다"


# ── 죽은 ref 를 이름으로 되살린다 (2026-08-11) ──────────────────────────────
#
# 위시켓 실측: 목록에서 하나 고르면 SPA 가 그 자리를 통째로 다시 그린다. 노드가
# 바뀌니 붙여 둔 번호표가 사라지고, 사람 눈엔 화면이 그대로인데 자비스만 "없다"며
# 손을 놓는다(숙련도를 고른 직후 경험 칸이 정확히 그랬다).
#
# ★ 번호로 다시 찾으면 안 된다 — 다시 찍으면 번호는 DOM 순서로 새로 매겨지므로
# 같은 번호가 다른 것을 가리킬 수 있고, 그걸 누르면 조용히 엉뚱한 일이 벌어진다.
class _Recovering:
    """번호표가 떨어진 화면. 다시 찍으면 같은 칸이 다른 번호로 나온다."""

    def __init__(self, worker: BrowserWorker, fresh: list[dict[str, Any]]) -> None:
        self.worker = worker
        self.fresh = fresh
        self.rescans = 0

    def install(self) -> None:
        def scan(page: Any) -> list[dict[str, Any]]:
            del page
            self.rescans += 1
            return self.fresh

        self.worker._snapshot_elements = scan  # type: ignore[assignment]
        self.worker._frames_of = lambda page: [_RefFrame(self.fresh)]  # type: ignore[assignment]


class _RefFrame:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    def locator(self, selector: str) -> Any:
        alive = any(f'"{i["ref"]}"' in selector for i in self.items)
        return type(
            "L", (), {"count": lambda _s, n=1 if alive else 0: n,
                      "is_visible": lambda _s: alive,
                      "first": property(lambda _s: _s)},
        )()


def test_a_ref_killed_by_a_rerender_is_found_again_by_name(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    worker._ref_memory = {"j104": {"name": "경험 *", "tag": "div"}}
    # 다시 그려진 뒤 같은 칸이 j77 로 번호가 바뀌었다.
    helper = _Recovering(worker, [{"ref": "j77", "name": "경험 *", "tag": "div"}])
    helper.install()

    assert worker._recover_ref(object(), "j104") is not None
    assert helper.rescans == 1, "되살릴 때만 다시 찍어야 한다"


def test_a_name_that_no_longer_exists_is_not_guessed(tmp_path: Path) -> None:
    """★ 비슷한 걸 골라 주는 편이 친절해 보이지만, 그건 사람 모르게 다른 것을
    누르게 만드는 길이다. 못 찾으면 못 찾았다고 해야 한다."""
    worker = _worker(tmp_path)
    worker._ref_memory = {"j104": {"name": "경험 *", "tag": "div"}}
    helper = _Recovering(worker, [{"ref": "j77", "name": "숙련도", "tag": "div"}])
    helper.install()

    assert worker._recover_ref(object(), "j104") is None


def test_without_a_memory_there_is_nothing_to_recover_from(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    worker._ref_memory = {}

    assert worker._recover_ref(object(), "j104") is None


def test_an_internal_scan_does_not_renumber_the_world(tmp_path: Path) -> None:
    """★ 오늘 두 번 깨진 자리. 속으로 훑는 일이 번호를 다시 찍으면 밖에 내준
    ref 가 그 자리에서 어긋난다(invalid_element_ref)."""
    script = _fast_script(tmp_path)

    assert "stampRefs" in script
    # 2026-10-07: 번호를 붙박이로 주면서 한 줄이던 것이 묶음이 됐다. 지키는 것은 같다 — 번호표를 붙이는 자리는
    # 전부 `if (stampRefs) {` 안에 있다(속으로 훑을 때는 아무 번호표도 안 건드린다).
    stamping = [i for i in range(len(script)) if script.startswith('el.setAttribute("data-jarvis-ref"', i)]
    assert stamping, "번호표를 붙이는 자리가 있어야 한다"
    for at in stamping:
        assert "if (stampRefs) {" in script[max(0, at - 500):at]
    removing = script.index('old.removeAttribute("data-jarvis-ref")')
    assert "if (stampRefs) {" in script[max(0, removing - 900):removing]


def test_old_ref_stamps_are_removed_before_new_ones(tmp_path: Path) -> None:
    """★ 한 번호는 한 요소만 가리켜야 한다 — 그게 번호표의 유일한 약속이다.

    붙이기만 하고 안 뗐더니 같은 번호가 여러 노드에 남았다. SPA 가 화면을 다시
    그리면 옛 노드는 사라지는데 번호표는 그대로라, `[data-jarvis-ref="j104"]` 로
    찾으면 그 유령이 먼저 잡힌다. 위시켓 경험 칸이 계속 실패한 이유가 이것이었고,
    증상은 "요소는 있는데 안 보인다"로 나왔다.

    사이트 문제가 아니라 우리 구조 문제였다.
    """
    script = _fast_script(tmp_path)

    # 2026-09-17: 섀도 DOM 안까지 떼도록 `__deepAll` 로 바뀌었다(_deep_js). 지키는 것은 같다 — 새로 찍기 전에 옛 번호표를 전부 뗀다.
    assert '__deepAll("[data-jarvis-ref]")' in script
    assert 'removeAttribute("data-jarvis-ref")' in script
    # 번호를 새로 안 매기는 내부 스캔은 남의 번호표를 떼서도 안 된다.
    clear_at = script.index('removeAttribute("data-jarvis-ref")')
    guard_at = script.index("if (stampRefs) {")
    assert guard_at < clear_at, "떼는 일도 stampRefs 안에서만 일어나야 한다"


def test_recovery_says_why_it_failed(tmp_path: Path) -> None:
    """이유 없이 None 만 돌려주면 추측으로 고치게 된다 — 오늘 두 번 빗나갔다."""
    worker = _worker(tmp_path)
    worker._ref_memory = {}

    assert worker._recover_ref(object(), "j104") is None
    assert "기억에" in worker._recover_why


# ── 지침: 마우스와 키보드를 갈라서 (2026-08-11) ─────────────────────────────
#
# 사용자님 지적: "글 넣는 건 잘하는데 클릭을 못하더라. 젬마한테 지침을 줄 때
# 마우스랑 키보드 둘 다 잘 쓰는 방식으로 가야지."
# 도구를 만들어 놓고 언제 쓰는지 안 알려주면 안 쓰인다 — 오늘 아침 risk_of 와 같다.
def test_the_prompt_tells_the_model_when_to_click_and_when_to_type() -> None:
    from alture_jarvis import agent as agent_module

    text = agent_module.BROWSER_RULES if hasattr(agent_module, "BROWSER_RULES") else ""
    if not text:
        import inspect
        text = inspect.getsource(agent_module)

    assert "browser_pick_suggestion" in text, "새 도구를 지침에 안 넣으면 안 쓰인다"
    assert "눌러야 목록이 뜨는" in text, "커스텀 셀렉트도 같은 도구로 된다는 것"
    assert "글자만 넣고 끝내면 등록이 안 된다" in text, "이게 어제 실제로 난 사고다"
    assert "비슷해 보이는 다른 것을 누르지 마라" in text, "못 찾을 때의 방어"


def test_a_failed_pick_gets_a_next_step_not_just_an_error() -> None:
    """오류 문구만 던지면 모델은 같은 것을 또 부른다. 다음 수를 같이 준다."""
    import inspect

    from alture_jarvis import agent as agent_module

    source = inspect.getsource(agent_module)
    assert "suggestion_not_found" in source
    assert "candidates 를 읽고" in source
