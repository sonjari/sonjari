"""이 PC 안 페이지의 확인창은 따로 정하지 않았으면 확인으로 답한다 (2026-10-04 대표 결정, 도구 전수조사 11번).

기본이 취소라, 자기가 만든 페이지의 「삭제」 버튼(`confirm("삭제할까요?")`)은 눌러도 아무 일이 안 일어났다. 모델은 자기 코드가
틀린 줄 알고 멀쩡한 코드를 고쳤다. 누르기는 09-30 부터 이 PC 안 페이지에서 승인 없이 눌린다 — 결정은 그 누르기에서 났다.

안 바뀌는 것:
- 밖의 사이트는 기본 취소. 허가를 둬도 「정말 삭제?」·결제는 취소.
- 모델이 미리 정한 답(`browser_handle_dialog`)이 먼저다 — 이 PC 안 페이지에서도 취소로 정했으면 취소.
- 사람이 넘겨받은 동안 뜬 확인창은 사람의 것.
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from alture_jarvis.browser import LOCAL_DIALOG_NOTE, BrowserWorker
from alture_jarvis.code_runtime import CODE_PREVIEW_TOOL_NAMES


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url
        self.handler: Any = None

    def on(self, event: str, handler: Any) -> None:
        assert event == "dialog"
        self.handler = handler


class _Dialog:
    def __init__(self, message: str, kind: str = "confirm") -> None:
        self.message, self.type = message, kind
        self.answered = ""

    def accept(self, _text: str = "") -> None:
        self.answered = "accept"

    def dismiss(self) -> None:
        self.answered = "dismiss"


class _Worker:
    def __init__(self, policy: dict[str, Any] | None = None, live_view: Any = None) -> None:
        self._dialog_policy = policy
        self._last_dialog: dict[str, Any] | None = None
        self.live_view = live_view


def _answer(url: str, message: str, *, policy: dict[str, Any] | None = None, live_view: Any = None) -> tuple[_Dialog, _Worker]:
    worker, page, dialog = _Worker(policy, live_view), _Page(url), _Dialog(message)
    BrowserWorker._watch_dialogs(worker, page)  # type: ignore[arg-type]
    page.handler(dialog)
    return dialog, worker


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:5173/index.html",
    "http://localhost:3000/todos",
    "file:///C:/work/app/index.html",
])
def test_a_confirm_on_a_page_on_this_pc_is_accepted_by_default(url: str) -> None:
    dialog, worker = _answer(url, "정말 삭제할까요?")

    assert dialog.answered == "accept"
    assert worker._last_dialog["accepted"] is True
    assert worker._last_dialog["auto_accepted_local"] is True  # 누가 답했는지 남긴다


def test_the_models_own_choice_comes_first_even_on_a_local_page() -> None:
    dialog, worker = _answer("http://localhost:3000/", "정말 삭제할까요?", policy={"accept": False})

    assert dialog.answered == "dismiss"
    assert worker._last_dialog["auto_accepted_local"] is False
    assert worker._dialog_policy is None  # 일회용


def test_outside_sites_are_unchanged() -> None:
    # 기본은 취소.
    assert _answer("https://shop.example.com/cart", "장바구니를 비울까요?")[0].answered == "dismiss"
    # 허가를 뒀어도 되돌릴 수 없는 문구는 취소.
    blocked, worker = _answer("https://shop.example.com/cart", "정말 삭제하시겠습니까?", policy={"accept": True})
    assert blocked.answered == "dismiss" and worker._last_dialog["blocked_by_read_only"] is True
    # 허가를 둔 평범한 확인은 그대로 확인.
    assert _answer("https://example.com/", "계속할까요?", policy={"accept": True})[0].answered == "accept"


def test_a_dialog_shown_while_a_person_is_in_control_is_left_to_them() -> None:
    class _View:
        @staticmethod
        def human_in_control() -> bool:
            return True

    dialog, worker = _answer("http://localhost:3000/", "정말 삭제할까요?", live_view=_View())

    assert dialog.answered == ""
    assert worker._last_dialog["left_to_human"] is True


def test_the_result_says_the_tool_answered_and_how_to_cancel_instead() -> None:
    source = inspect.getsource(BrowserWorker)

    assert '"auto_accepted_local": True, "note": LOCAL_DIALOG_NOTE' in source
    assert "accept=false" in LOCAL_DIALOG_NOTE and "누르기 전에" in LOCAL_DIALOG_NOTE
    # 취소 쪽을 시험할 손이 코드 판 화면 묶음에 있다.
    assert "browser_handle_dialog" in CODE_PREVIEW_TOOL_NAMES


def test_the_tool_description_no_longer_says_the_order_backwards() -> None:
    """예전 설명: 「확인창이 떠 있으면 페이지가 멈추므로 다른 동작 전에 먼저 처리해야 한다」 — 반대다. 뜨는 즉시 답해 버린다."""
    from alture_jarvis import browser

    source = inspect.getsource(browser)  # 설명은 도구 목록(BrowserTools)에 있다

    assert "확인창이 떠 있으면 페이지가 멈추므로 다른 동작 전에 먼저 처리해야 한다" not in source
    assert "누르기 **전에** 부른다" in source
