"""레시피가 없는 사이트에서 낸 것도 **찾아갈 수는 있어야** 한다.

## 왜 (13-3, 2026-08-16)

레시피가 있는 사이트는 절차가 역동작을 선언한다(`site_recipes` 의 action `undo`).
레시피가 없는 사이트에서 폼을 내면 **아무 기록도 안 남았다** — 채우기에는 되돌리기가
붙었는데(같은 날) 정작 **제출이 비어 있었다.**

자동으로는 못 되돌린다. 무엇이 일어나는지 사이트마다 다르고, **모르면서 되돌리는
척하는 것이 제일 나쁘다.** 그래서 `undo=None` 으로 두고 **어디에서 무엇을 냈는지**를
남긴다 — 되돌리려면 먼저 찾을 수 있어야 한다. 발행(`naver_blog_publish`)에 한 것과
같은 규율이고, 그것의 일반화다.

## 값은 안 남긴다

칸 **이름과 글자 수**만 남긴다. 사람이 "무엇을 냈는지" 찾아가는 데는 그것으로
충분하고, 값까지 남기면 이 장부가 그 자체로 새는 자리가 된다.
"""

from __future__ import annotations

from alture_jarvis.browser import BrowserTools, BrowserWorker


class _Field:
    def __init__(self, **attrs: str) -> None:
        self._attrs = attrs

    def get_attribute(self, name: str):
        return self._attrs.get(name)


def _worker() -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._form_trail = []
    return worker


def test_filling_records_the_field_name_not_the_value() -> None:
    worker = _worker()
    worker._remember_filled(
        "https://apply.test/form", _Field(**{"aria-label": "휴대전화"}), "j5", 11
    )
    trail = worker._form_trail
    assert trail[0]["field"] == "휴대전화"
    assert trail[0]["chars"] == 11
    # ★ 값이 어디에도 없어야 한다.
    assert not any("value" in item for item in trail)


def test_the_field_name_falls_back_through_the_usual_attributes() -> None:
    worker = _worker()
    worker._remember_filled("https://apply.test/form", _Field(name="phone"), "j5", 3)
    worker._remember_filled("https://apply.test/form", _Field(placeholder="이름"), "j6", 3)
    worker._remember_filled("https://apply.test/form", _Field(), "j7", 3)
    assert [item["field"] for item in worker._form_trail] == ["phone", "이름", "j7"]


def test_only_this_screen_counts() -> None:
    """딴 화면에서 채운 것을 이 제출의 내용이라고 적으면 거짓말이 된다."""
    worker = _worker()
    worker._remember_filled("https://apply.test/form", _Field(name="phone"), "j5", 3)
    worker._remember_filled("https://other.test/form", _Field(name="card"), "j9", 16)
    assert [item["field"] for item in worker._filled_here("https://apply.test/form")] == ["phone"]


def test_the_submit_handle_says_where_and_what() -> None:
    worker = _worker()
    worker._remember_filled("https://apply.test/form", _Field(name="phone"), "j5", 11)
    worker._remember_filled("https://apply.test/form", _Field(name="resume"), "j6", 40)

    handle = worker._submit_handle(
        {
            "url": "https://apply.test/form",
            "title": "지원서 작성",
            "element": {"name": "지원하기"},
        }
    )
    assert handle["url"] == "https://apply.test/form"
    assert handle["button"] == "지원하기"
    assert handle["fields"] == ["phone", "resume"]


def test_no_address_means_no_button() -> None:
    """어디서 냈는지 모르면 찾아갈 수가 없다 — 안 내주는 편이 낫다."""
    assert _worker()._submit_handle({"element": {"name": "지원하기"}}) is None


def test_the_commit_tool_carries_the_spec_and_stays_manual() -> None:
    """★ 명세를 짜 놓고 `ToolSpec(inverse=...)` 에 안 물리면 아무 일도 안 일어난다."""

    class _Tools:
        worker = _worker()

    inverses = BrowserTools._inverses(_Tools())
    spec = inverses["browser_click_confirmed"]
    assert spec.undo is None, "무엇이 일어났는지 모르면서 되돌리는 척하면 안 된다"
    assert "레시피에 취소 절차" in spec.manual_hint

    _Tools.worker._remember_filled("https://apply.test/f", _Field(name="phone"), "j5", 3)
    handle = spec.handle_from({"url": "https://apply.test/f", "element": {"name": "제출"}})
    assert handle["fields"] == ["phone"]
