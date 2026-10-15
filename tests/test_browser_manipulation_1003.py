"""화면 조작 묶음 B (2026-10-03, Browser Use 조작 방식 조사 · Online-Mind2Web 실패 판).

B1 선택 상자 미리 보기 · B2 입력 뒤 뜬 후보 알리기 · B3 닫기 버튼 없는 가림막 · B4 날짜 꼴 · B5 채운 뒤 되읽기.
"""

from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker, normalize_date_input


# ── B4 날짜 꼴 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw, want", [
    ("2026-10-05", "2026-10-05"),
    ("2026.10.5", "2026-10-05"),
    ("2026년 10월 5일", "2026-10-05"),
    ("10/05/2026", "2026-10-05"),          # 미국식 월/일
    ("Oct 5, 2026", "2026-10-05"),
    ("5 October 2026", "2026-10-05"),
    ("September 30th 2026", "2026-09-30"),
])
def test_dates_are_written_the_way_the_field_takes_them(raw: str, want: str) -> None:
    assert normalize_date_input("date", raw) == want


def test_other_date_kinds_and_refusals() -> None:
    assert normalize_date_input("month", "2026년 10월") == "2026-10"
    assert normalize_date_input("time", "2:30 PM") == "14:30"
    assert normalize_date_input("datetime-local", "2026-10-05 09:15") == "2026-10-05T09:15"
    # 못 읽으면 짐작하지 않는다.
    assert normalize_date_input("date", "next Friday") is None
    assert normalize_date_input("date", "2026-13-40") is None
    assert normalize_date_input("time", "noon") is None


# ── B2·B5 채우기: 되읽기 · 후보 ─────────────────────────────────────────────────────
class _Locator:
    def __init__(self, *, kind: str = "text", after: str | None = None) -> None:
        self.kind, self.after, self.filled = kind, after, None

    def get_attribute(self, name: str) -> Any:
        return self.kind if name == "type" else None

    def is_disabled(self, timeout: int = 0) -> bool:
        return False

    def input_value(self, timeout: int = 0) -> str:
        if self.filled is None:
            return ""
        return self.after if self.after is not None else self.filled

    def fill(self, value: str) -> None:
        self.filled = value


class _Page:
    def __init__(self, suggestions: list[str] | None = None) -> None:
        self.suggestions = suggestions or []
        self.url = "https://www.webmd.com/"

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def evaluate(self, script: str, arg: Any = None) -> Any:
        return self.suggestions


def _worker(locator: _Locator) -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._ref_locator = lambda page, ref: locator  # type: ignore[method-assign]
    worker._show_visual = lambda *a, **k: None  # type: ignore[method-assign]
    worker._local_test_secret_ok = lambda page, value: False  # type: ignore[method-assign]
    worker._remember_filled = lambda *a, **k: None  # type: ignore[method-assign]
    worker._remember_typed = lambda value: None  # type: ignore[method-assign]
    worker._evidence = lambda action, **fields: {"action": action, **fields}  # type: ignore[method-assign]
    return worker


def test_a_field_the_site_rewrote_is_reported() -> None:
    locator = _Locator(after="")
    got = _worker(locator)._fill(_Page(), {"ref": "j3", "value": "Seattle"})
    assert got["value_mismatch"] is True and got["value_after"] == ""
    assert "browser_snapshot" in got["next"]


def test_suggestions_that_appear_under_the_field_are_named() -> None:
    page = _Page(["Seattle, WA", "Seattle Heights, WA"])
    got = _worker(_Locator())._fill(page, {"ref": "j3", "value": "Seattle"})
    assert got["suggestions"] == ["Seattle, WA", "Seattle Heights, WA"]
    assert "browser_pick_suggestion(ref='j3'" in got["next"] and "Enter 를 누르지 말고" in got["next"]


def test_a_plain_fill_stays_quiet() -> None:
    got = _worker(_Locator())._fill(_Page(), {"ref": "j3", "value": "Seattle"})
    assert "value_mismatch" not in got and "suggestions" not in got and "next" not in got


def test_a_date_field_gets_the_iso_value() -> None:
    locator = _Locator(kind="date")
    _worker(locator)._fill(_Page(), {"ref": "j9", "value": "10/05/2026"})
    assert locator.filled == "2026-10-05"
    with pytest.raises(RuntimeError, match="date_format_required:date"):
        _worker(_Locator(kind="date"))._fill(_Page(), {"ref": "j9", "value": "next Friday"})


# ── B5 선택 상자 되읽기 ─────────────────────────────────────────────────────────────
class _Select:
    def __init__(self, shown: str) -> None:
        self.shown = shown

    def evaluate(self, script: str) -> str:
        return "select" if "tagName" in script else self.shown

    def select_option(self, **kwargs: Any) -> list[str]:
        return ["v1"]


def test_select_reads_back_what_the_box_shows() -> None:
    worker = _worker(_Locator())
    worker._ref_locator = lambda page, ref: _Select("GeForce RTX 40 Series")  # type: ignore[method-assign]
    ok = worker._select_option(_Page(), {"ref": "j5", "label": "GeForce RTX 40 Series"})
    assert ok["verified"] is True and ok["selected_label"] == "GeForce RTX 40 Series"
    worker._ref_locator = lambda page, ref: _Select("Select a series")  # type: ignore[method-assign]
    bad = worker._select_option(_Page(), {"ref": "j5", "label": "GeForce RTX 40 Series"})
    assert bad["verified"] is False and "Select a series" in bad["next"]


# ── B3 닫기 버튼 없는 가림막 ──────────────────────────────────────────────────────────
class _Keyboard:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    def press(self, key: str) -> None:
        self.pressed.append(key)


class _ClickPage(_Page):
    def __init__(self) -> None:
        super().__init__()
        self.keyboard = _Keyboard()


class _Blocked:
    """맨 위가 가림막인 요소 — `relation` 대로 답하고, Esc 를 누른 뒤에만 보통 클릭이 된다(`opens_after`)."""

    def __init__(self, relation: str, page: _ClickPage, *, escape_clears: bool) -> None:
        self.relation, self.page, self.escape_clears = relation, page, escape_clears
        self.clicks: list[bool] = []

    def evaluate(self, script: str) -> str:
        return self.relation

    def click(self, timeout: float = 0, force: bool = False) -> None:
        self.clicks.append(force)
        if force:
            return
        if self.escape_clears and "Escape" in self.page.keyboard.pressed:
            return
        if any(self.clicks[:-1]):  # 앞서 강제 클릭(바깥 누르기)으로 뒷막이 닫혔다
            return
        raise RuntimeError("intercepts pointer events")


def test_a_skinned_checkbox_is_clicked_where_its_face_is() -> None:
    page = _ClickPage()
    target = _Blocked("same_control", page, escape_clears=False)
    assert BrowserWorker.__new__(BrowserWorker)._clear_blocker(page, target, timeout=1000) is True
    assert target.clicks == [True] and page.keyboard.pressed == []


def test_a_backdrop_is_closed_with_escape_first() -> None:
    page = _ClickPage()
    target = _Blocked("backdrop", page, escape_clears=True)
    assert BrowserWorker.__new__(BrowserWorker)._clear_blocker(page, target, timeout=1000) is True
    assert page.keyboard.pressed == ["Escape"] and target.clicks == [False]


def test_a_backdrop_that_ignores_escape_is_clicked_away() -> None:
    page = _ClickPage()
    target = _Blocked("backdrop", page, escape_clears=False)
    assert BrowserWorker.__new__(BrowserWorker)._clear_blocker(page, target, timeout=1000) is True
    assert target.clicks == [False, True, False]


def test_an_unrelated_blocker_is_left_alone() -> None:
    page = _ClickPage()
    target = _Blocked("other", page, escape_clears=True)
    assert BrowserWorker.__new__(BrowserWorker)._clear_blocker(page, target, timeout=1000) is False
    assert target.clicks == [] and page.keyboard.pressed == []
