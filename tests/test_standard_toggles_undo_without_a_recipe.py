"""표준이 **"나는 토글"** 이라고 말한 것은 레시피 없이도 되돌린다.

## 왜 이 방향인가 (2026-08-16, 사용자님 지시)

    "잡코리아는 됐고, 그냥 **범용적으로 잘하는 게 중요**한 거지"

맞는 말이다. 레시피는 안 늘리면 안 늘지만 범용은 한 번 좋아지면 전부 좋아진다.
그런데 범용에서 제일 아픈 자리가 **되돌리기**였다 — "지원 취소를 어떻게 하는가"는
화면만 봐서는 모르니까.

다만 **전부 모르는 것은 아니다.** `aria-pressed` 와 `aria-checked` 는 뜻이 정해져
있다 — 누르면 두 상태를 오가는 버튼이고 지금 어느 쪽인지 알려 준다. 그러니 그것이
뒤집혔다면 **같은 것을 다시 누르는 것이 역동작**이라고 말할 근거가 있다.

실측(2026-08-16):

    사람인 검색 화면   [aria-pressed] 40개
    다나와            [role=switch]   5개
    쿠팡·위시켓        안 쓴다

범용으로 다 덮지는 못해도, 쓰는 사이트에서는 **레시피 없이** 스크랩·관심기업이
되돌려진다. 사람인 레시피가 하던 일의 상당 부분을 표준이 대신 해 준다.

## ★ 클래스 변화로 짐작하지 않는 이유

"눌렀더니 클래스가 바뀌었다"도 토글처럼 보인다. 그런데 **제출 버튼도 누르면
클래스가 바뀐다**(disabled·loading·done…). 그걸 토글로 오해하면 되돌리기가
**두 번째 제출**이 된다 — 지원서를 두 번 내는 것보다 나쁜 되돌리기는 없다.

못 잡는 토글이 생기더라도 **없는 역동작을 만들어 내지는 않는다.** 모르면 안 내준다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.browser import BrowserTools, BrowserWorker
from alture_jarvis.tool_gateway import UndoUnverified


class _El:
    def __init__(self, **attrs) -> None:
        self._attrs = attrs

    def get_attribute(self, name):
        return self._attrs.get(name)


class _ToggleLocator:
    def __init__(self, state: str, *, on_click=None) -> None:
        self.state = state
        self.on_click = on_click
        self.clicks = 0

    def get_attribute(self, name):
        return self.state if name == "aria-pressed" else None

    def click(self, timeout=0) -> None:
        del timeout
        self.clicks += 1
        if self.on_click is not None:
            self.on_click()


class _Page:
    url = "https://www.saramin.co.kr/a"

    def wait_for_timeout(self, milliseconds: int) -> None:
        del milliseconds


class _Tab(_Page):
    def __init__(self, url: str) -> None:
        self.url = url
        self.brought_to_front = 0

    def is_closed(self) -> bool:
        return False

    def bring_to_front(self) -> None:
        self.brought_to_front += 1


def _worker() -> BrowserWorker:
    return BrowserWorker.__new__(BrowserWorker)


def test_aria_pressed_is_recognised_as_a_toggle() -> None:
    assert _worker()._toggle_state(_El(**{"aria-pressed": "false"})) == ("aria-pressed", "false")
    assert _worker()._toggle_state(_El(**{"aria-checked": "true"})) == ("aria-checked", "true")


def test_a_plain_button_is_not_a_toggle() -> None:
    """★ 제출 버튼에 역동작을 달면 되돌리기가 두 번째 제출이 된다."""
    assert _worker()._toggle_state(_El()) is None
    assert _worker()._toggle_state(_El(**{"class": "btn_apply on"})) is None
    # 값이 true/false 가 아니면 뜻을 모른다 — 모르면 안 내준다.
    assert _worker()._toggle_state(_El(**{"aria-pressed": "mixed"})) is None


def test_the_handle_remembers_what_to_go_back_to() -> None:
    handle = _worker()._toggle_handle(
        {
            "url": "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1",
            "undo_ref": "j20",
            "toggled": {"attr": "aria-pressed", "from": "false", "to": "true"},
            "element": {"name": "스크랩 23건"},
        }
    )
    assert handle["ref"] == "j20"
    assert handle["back_to"] == "false", "되돌린다는 것은 **누르기 전 상태**로 가는 것이다"
    assert handle["attr"] == "aria-pressed"


def test_a_click_that_changed_nothing_leaves_no_handle() -> None:
    """이동이나 평범한 누르기에는 아무것도 안 남긴다."""
    worker = _worker()
    assert worker._toggle_handle({"url": "https://x.test/", "undo_ref": "j2"}) is None
    assert worker._toggle_handle({"toggled": {"attr": "aria-pressed", "from": "false"}}) is None


def test_it_is_registered_as_an_automatic_inverse() -> None:
    """명세를 짜 놓고 `ToolSpec(inverse=...)` 에 안 물리면 아무 일도 안 일어난다."""

    class _Tools:
        worker = _worker()

    inverses = BrowserTools._inverses(_Tools())
    assert inverses["browser_click"].undo is not None, "토글은 자동으로 되돌아가야 한다"
    # 되돌릴 수 없는 제출은 여전히 수동이다 — 둘을 섞으면 안 된다.
    assert inverses["browser_click_confirmed"].undo is None


def test_the_undo_refuses_when_the_screen_moved() -> None:
    """ref 는 그 화면의 것이다. 딴 데서 같은 번호는 딴 요소다."""
    worker = _worker()
    worker._current_page = lambda: type("P", (), {"url": "https://other.test/"})()  # type: ignore
    try:
        worker._undo_toggle({"url": "https://www.saramin.co.kr/a", "ref": "j20", "back_to": "false"})
    except RuntimeError as exc:
        assert "undo_toggle_wrong_page" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("딴 화면인데 눌렀다")


def test_undo_reacquires_the_one_open_tab_with_the_original_exact_url() -> None:
    """호출 사이 현재 탭을 잃어도 원래 화면이 하나면 그 탭으로 돌아간다."""
    worker = _worker()
    other = _Tab("https://other.test/")
    target = _Tab("https://www.saramin.co.kr/a#after-click")
    current = _ToggleLocator("true", on_click=lambda: setattr(current, "state", "false"))
    worker._page = other
    worker._context = type("Context", (), {"pages": [other, target]})()
    worker._current_page = lambda: other  # type: ignore
    worker._ref_locator = lambda *_args: current  # type: ignore
    worker._toggle_counts = lambda *_args: None  # type: ignore

    result = worker._undo_toggle(
        {
            "url": "https://www.saramin.co.kr/a#before-click",
            "ref": "j20",
            "attr": "aria-pressed",
            "back_to": "false",
        }
    )

    assert result["verification"] == "target"
    assert worker._page is target
    assert target.brought_to_front == 1
    assert current.clicks == 1


def test_undo_does_not_guess_between_duplicate_exact_url_tabs() -> None:
    """같은 URL 탭이 둘이면 ref가 어느 문서 것인지 모르므로 누르지 않는다."""
    worker = _worker()
    other = _Tab("https://other.test/")
    first = _Tab("https://www.saramin.co.kr/a")
    second = _Tab("https://www.saramin.co.kr/a#copy")
    locator = _ToggleLocator("true")
    worker._page = other
    worker._context = type("Context", (), {"pages": [other, first, second]})()
    worker._current_page = lambda: other  # type: ignore
    worker._ref_locator = lambda *_args: locator  # type: ignore

    with pytest.raises(RuntimeError, match="undo_toggle_ambiguous_page"):
        worker._undo_toggle(
            {
                "url": "https://www.saramin.co.kr/a",
                "ref": "j20",
                "attr": "aria-pressed",
                "back_to": "false",
            }
        )

    assert locator.clicks == 0


def test_undo_reacquires_a_toggle_replaced_by_the_click() -> None:
    """번호표가 사라져도 기존 ref 복구 경로로 새 노드의 상태를 읽는다."""
    worker = _worker()
    page = _Page()
    old = _ToggleLocator("true")
    fresh = _ToggleLocator("false")
    found = 0

    def locate(_page, _ref):
        nonlocal found
        found += 1
        return old if found == 1 else fresh

    worker._current_page = lambda: page  # type: ignore
    worker._ref_locator = locate  # type: ignore
    worker._toggle_counts = lambda *_args: None  # type: ignore

    result = worker._undo_toggle(
        {"url": page.url, "ref": "j20", "attr": "aria-pressed", "back_to": "false"}
    )

    assert result["verified"] is True
    assert result["verification"] == "target"
    assert old.clicks == 1, "DOM 교체 뒤 확인 때문에 토글을 다시 누르면 도로 켜진다"


def test_undo_uses_the_aria_count_delta_when_the_replacement_has_no_ref() -> None:
    """이름까지 바뀌어 새 노드를 못 잡아도 화면의 토글 수 변화는 증거가 된다."""
    worker = _worker()
    page = _Page()
    old = _ToggleLocator("true")
    finds = 0
    counts = iter([{"true": 4, "false": 7}, {"true": 3, "false": 8}])

    def locate(_page, _ref):
        nonlocal finds
        finds += 1
        if finds == 1:
            return old
        raise RuntimeError("stale_element_ref:take_a_new_snapshot")

    worker._current_page = lambda: page  # type: ignore
    worker._ref_locator = locate  # type: ignore
    worker._toggle_counts = lambda *_args: next(counts)  # type: ignore

    result = worker._undo_toggle(
        {"url": page.url, "ref": "j20", "attr": "aria-pressed", "back_to": "false"}
    )

    assert result["verified"] is True
    assert result["verification"] == "aggregate"
    assert old.clicks == 1


def test_an_unreadable_result_is_consumed_but_not_called_a_failure() -> None:
    """눌렀지만 확인 못 한 것은 재시도 불가한 제3상태다."""
    worker = _worker()
    page = _Page()
    old = _ToggleLocator("true")
    finds = 0

    def locate(_page, _ref):
        nonlocal finds
        finds += 1
        if finds == 1:
            return old
        raise RuntimeError("stale_element_ref:take_a_new_snapshot")

    worker._current_page = lambda: page  # type: ignore
    worker._ref_locator = locate  # type: ignore
    worker._toggle_counts = lambda *_args: None  # type: ignore

    with pytest.raises(UndoUnverified) as raised:
        worker._undo_toggle(
            {"url": page.url, "ref": "j20", "attr": "aria-pressed", "back_to": "false"}
        )

    assert raised.value.result["verification"] == "unverified"
    assert old.clicks == 1, "확인 못 했다고 다시 누르면 안 된다"


def test_undo_does_not_click_when_the_toggle_is_already_back() -> None:
    """사람이 먼저 원복한 뒤 온 늦은 undo는 다시 켜지 않아야 한다."""
    worker = _worker()
    page = _Page()
    current = _ToggleLocator("false")
    worker._current_page = lambda: page  # type: ignore
    worker._ref_locator = lambda *_args: current  # type: ignore
    worker._toggle_counts = lambda *_args: {"true": 3, "false": 8}  # type: ignore

    result = worker._undo_toggle(
        {"url": page.url, "ref": "j20", "attr": "aria-pressed", "back_to": "false"}
    )

    assert result["verification"] == "already_returned"
    assert current.clicks == 0


def test_the_model_is_told_never_to_retry_an_unverified_undo() -> None:
    """제3상태를 만들어도 상위가 ok만 읽고 다시 누르면 소용없다."""
    import inspect

    from alture_jarvis import agent

    rules = str(getattr(agent, "BROWSER_RULES", "")) or inspect.getsource(agent)
    assert "attempted_unverified" in rules
    assert "같은 `undo_action` 을 다시 부르지 마라" in rules
