""""같은 동작"인지는 **어느 화면에서 하느냐**까지 봐야 정해진다.

2026-08-13. "교보문고에서 회계 책 3권"에 2 권만 나왔다. 모델이 게을러서가 아니라
**세 번째 추출부터 판이 끝날 때까지 도구가 막혀 있었다.**

    4  OK   browser_extract   chars=880
    6  OK   browser_extract   chars=1904
    8  FAIL browser_extract   duplicate_action_blocked
    11 FAIL browser_extract   duplicate_action_blocked
    13 FAIL browser_extract   duplicate_action_blocked

원인은 지문이 `{"tool","arguments"}` 뿐이었던 것이다. `browser_extract` 의 인자는
`{}` 다 — "지금 화면을 읽어라"라는 뜻이라 그럴 수밖에 없다. 그래서 상품 상세를
아무리 옮겨 다녀도 지문이 늘 똑같았고, 세 번째부터 전부 되풀이로 몰렸다.

되풀이를 막자는 취지는 맞다. **같은 화면에서** 되풀이하는 것이 낭비지, 다음 상품을
열고 읽는 것은 시킨 일 그 자체다.

133 판 재현: 차단 42 회 → 9 회. 사라진 것은 전부 헛차단이고, 남은 9 회는 같은 질의
재검색 같은 진짜 되풀이다.
"""

from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.agent import BrowserAgent, _page_scoped
from alture_jarvis.browser import BrowserWorker


def _step(tool: str, url: str = "") -> dict[str, Any]:
    return {"tool": tool, "ok": True, "arguments": {}, "evidence": {"url": url} if url else {}}


def _count(calls: list[tuple[str, dict[str, Any], str]]) -> int:
    """이 순서대로 갔을 때 몇 번 막히는지."""
    seen: dict[str, int] = {}
    steps: list[dict[str, Any]] = []
    blocked = 0
    for tool, arguments, resulting_url in calls:
        key = BrowserAgent._fingerprint(tool, arguments, steps)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 2:
            blocked += 1
        steps.append(_step(tool, resulting_url))
    return blocked


def test_reading_five_different_books_is_not_repeating_yourself() -> None:
    """교보문고 판 그대로다. 상세를 열고 읽고를 다섯 번 되풀이한다."""
    calls: list[tuple[str, dict[str, Any], str]] = []
    for i in range(5):
        calls.append(("browser_open_result", {"rank": i + 1}, f"https://product.kyobobook.co.kr/{i}"))
        calls.append(("browser_extract", {}, f"https://product.kyobobook.co.kr/{i}"))
    assert _count(calls) == 0


def test_reading_the_same_screen_over_and_over_is_still_blocked() -> None:
    """취지는 그대로 지킨다 — 같은 화면을 계속 긁는 것은 낭비다."""
    same = [("browser_extract", {}, "https://product.kyobobook.co.kr/1")] * 4
    assert _count(same) > 0


def test_repeating_the_same_search_is_blocked_wherever_you_stand() -> None:
    """검색어는 그 자체로 대상이다. 서 있는 페이지가 달라도 같은 질의는 같은 질의다.

    프롬프트도 이미 그렇게 말한다: "같은 질의로 재검색하는 것은 거의 언제나 낭비다".
    """
    calls = [
        ("browser_search", {"query": "무선마우스"}, "https://search.naver.com/a"),
        ("browser_open_result", {"rank": 1}, "https://a.example.com/x"),
        ("browser_search", {"query": "무선마우스"}, "https://search.naver.com/b"),
        ("browser_open_result", {"rank": 2}, "https://b.example.com/y"),
        ("browser_search", {"query": "무선마우스"}, "https://search.naver.com/c"),
    ]
    assert _count(calls) > 0


def test_going_back_and_forth_between_two_pages_is_still_caught() -> None:
    """`browser_open` 은 인자가 대상을 가리킨다. 페이지로 나누면 A↔B 왕복을 못 막는다."""
    calls = [
        ("browser_open", {"url": "https://a.kr"}, "https://a.kr"),
        ("browser_open", {"url": "https://b.kr"}, "https://b.kr"),
        ("browser_open", {"url": "https://a.kr"}, "https://a.kr"),
        ("browser_open", {"url": "https://b.kr"}, "https://b.kr"),
        ("browser_open", {"url": "https://a.kr"}, "https://a.kr"),
    ]
    assert _count(calls) > 0


def test_switching_back_after_visiting_another_tab_is_not_a_duplicate() -> None:
    """라이브의 0→0→2→0 순서다. 마지막 0은 다른 화면에서 돌아가는 새 동작이다."""
    calls = [
        ("browser_switch_tab", {"index": 0}, "https://saramin.test/job/1"),
        ("browser_extract", {}, "https://saramin.test/job/1"),
        ("browser_switch_tab", {"index": 0}, "https://saramin.test/job/1"),
        ("browser_switch_tab", {"index": 2}, "https://saramin.test/search"),
        ("browser_switch_tab", {"index": 0}, "https://saramin.test/job/1"),
    ]
    assert _count(calls) == 0


def test_switching_between_the_same_two_tabs_forever_is_still_caught() -> None:
    """페이지 범위를 넣어도 진짜 A↔B 왕복 방지는 살아 있어야 한다."""
    calls = [
        ("browser_switch_tab", {"index": 0}, "https://a.test"),
        ("browser_switch_tab", {"index": 2}, "https://b.test"),
        ("browser_switch_tab", {"index": 0}, "https://a.test"),
        ("browser_switch_tab", {"index": 2}, "https://b.test"),
        ("browser_switch_tab", {"index": 0}, "https://a.test"),
        ("browser_switch_tab", {"index": 2}, "https://b.test"),
        ("browser_switch_tab", {"index": 0}, "https://a.test"),
    ]
    assert _count(calls) > 0


@pytest.mark.parametrize(
    ("tool", "scoped"),
    [
        ("browser_extract", True),
        ("browser_snapshot", True),
        ("browser_open_result", True),
        ("browser_click", True),
        ("browser_open", False),
        ("browser_search", False),
        ("browser_switch_tab", True),
        ("google_drive_read", False),
    ],
)
def test_which_tools_are_judged_per_page(tool: str, scoped: bool) -> None:
    assert _page_scoped(tool) is scoped


def test_the_current_page_is_the_last_one_actually_observed() -> None:
    steps = [
        _step("browser_open", "https://a.kr"),
        _step("browser_extract"),  # 실패해서 증거가 없는 걸음
        _step("browser_open_result", "https://b.kr"),
        _step("browser_extract"),
    ]
    assert BrowserAgent._current_page(steps) == "https://b.kr"
    assert BrowserAgent._current_page([]) == ""


def test_switching_to_the_already_active_tab_is_a_successful_noop() -> None:
    class Page:
        def is_closed(self) -> bool:
            return False

    page = Page()
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._context = type("Context", (), {"pages": [page]})()
    worker._page = page
    worker._evidence = lambda action, **values: {"action": action, **values}

    result = BrowserWorker._switch_tab(worker, page, {"index": 0})

    assert result == {"action": "tab_already_active", "index": 0, "already_active": True}
