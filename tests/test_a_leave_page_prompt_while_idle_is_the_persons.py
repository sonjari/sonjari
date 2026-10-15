"""우리가 일하지 않는 동안 뜬 「나가시겠습니까?」는 사람의 것이다 — 답하지 않는다 (2026-10-07 대표 실사용).

채용 사이트의 이력서 수정 탭의 X 를 눌러도 닫히지 않았다. 쉬는 동안에도 도는 펌프가 그 확인창(beforeunload)을 받아
기본값(취소)으로 닫아 버렸기 때문이다. 사람은 창을 보지도 못하고 「닫기가 안 된다」만 겪었다.

재현(진짜 크롬): 자동 취소 = 탭 그대로 · 답하지 않고 두면 사람이 「나가기」를 누르는 순간 닫힌다.

안 바뀌는 것:
- 우리가 건 이동이 띄운 「나가시겠습니까?」는 예전대로 취소한다(사람이 쓰던 입력을 지킨다).
- 다른 확인창(confirm·alert)은 쉬는 동안에도 예전 규칙 그대로다.
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.browser import BrowserWorker

EDIT_PAGE = "https://jobs.example.com/resume/edit"


class _Page:
    def __init__(self, url: str = EDIT_PAGE) -> None:
        self.url = url
        self.handler: Any = None

    def on(self, event: str, handler: Any) -> None:
        assert event == "dialog"
        self.handler = handler


class _Dialog:
    def __init__(self, kind: str = "beforeunload", message: str = "") -> None:
        self.message, self.type = message, kind
        self.answered = ""

    def accept(self, _text: str = "") -> None:
        self.answered = "accept"

    def dismiss(self) -> None:
        if self.answered:
            raise RuntimeError("dialog_already_handled")
        self.answered = "dismiss"


class _Worker:
    def __init__(self, *, action_depth: int = 0, current: Any = None) -> None:
        self._dialog_policy: dict[str, Any] | None = None
        self._last_dialog: dict[str, Any] | None = None
        self._human_dialog: Any = None
        self.live_view = None
        self._action_depth = action_depth
        if current is not None:
            self._page = current


def _show(worker: _Worker, page: _Page, dialog: _Dialog) -> None:
    BrowserWorker._watch_dialogs(worker, page)  # type: ignore[arg-type]
    page.handler(dialog)


def test_a_leave_prompt_while_we_are_idle_is_not_answered() -> None:
    worker, page, dialog = _Worker(), _Page(), _Dialog()

    _show(worker, page, dialog)

    assert dialog.answered == "", "취소로 닫으면 사람이 누른 X 가 먹지 않는다"
    assert worker._last_dialog["left_to_human"] is True and worker._last_dialog["type"] == "beforeunload"


def test_a_leave_prompt_from_our_own_navigation_is_still_cancelled() -> None:
    """우리가 그 탭에서 다른 데로 가려다 뜬 창 — 사람이 쓰던 입력을 지키는 쪽(취소)으로 답한다."""
    page, dialog = _Page(), _Dialog()
    worker = _Worker(action_depth=1, current=page)

    _show(worker, page, dialog)

    assert dialog.answered == "dismiss"
    assert worker._last_dialog["accepted"] is False


def test_a_leave_prompt_on_another_tab_during_our_work_is_the_persons() -> None:
    """우리는 A 탭에서 일하는 중인데 사람이 B 탭을 닫으려 한다."""
    ours, theirs, dialog = _Page("https://example.com/a"), _Page(), _Dialog()
    worker = _Worker(action_depth=1, current=ours)

    _show(worker, theirs, dialog)

    assert dialog.answered == ""


def test_other_dialogs_while_idle_follow_the_old_rule() -> None:
    worker, page, dialog = _Worker(), _Page("https://shop.example.com/cart"), _Dialog("confirm", "장바구니를 비울까요?")

    _show(worker, page, dialog)

    assert dialog.answered == "dismiss"


def test_a_prompt_the_person_never_answered_is_cancelled_when_our_work_starts() -> None:
    """답 안 한 확인창이 떠 있는 탭은 멈춰 있다 — 그대로 일을 시작하면 호출이 시간 초과까지 매달린다."""
    worker, page, dialog = _Worker(), _Page(), _Dialog()
    _show(worker, page, dialog)

    BrowserWorker._settle_human_dialog(worker)  # type: ignore[arg-type]

    assert dialog.answered == "dismiss"
    assert worker._human_dialog is None


def test_settling_is_quiet_when_the_person_already_answered() -> None:
    worker, page, dialog = _Worker(), _Page(), _Dialog()
    _show(worker, page, dialog)
    dialog.accept()  # 사람이 「나가기」를 눌렀다

    BrowserWorker._settle_human_dialog(worker)  # type: ignore[arg-type]

    assert dialog.answered == "accept"
    BrowserWorker._settle_human_dialog(worker)  # type: ignore[arg-type]  — 남은 것이 없어도 조용하다
