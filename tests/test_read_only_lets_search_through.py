"""읽기 전용(기본값)이 **검색**까지 막지 않는가 (2026-09-26 A/B 벤치 · 다나와).

`<button type=submit>검색</button>` 이 막혀 모델이 승인 클릭으로 우회했고, 가격 조회에 승인 카드가 떠서 판이 멈췄다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from alture_jarvis.browser import BrowserWorker, _read_only_blocks


@pytest.mark.parametrize("name", ["검색", "찾기", "조회", "Search", "상품 검색"])
def test_a_search_submit_is_not_blocked(name: str) -> None:
    assert not _read_only_blocks(name, "submit")


@pytest.mark.parametrize("name,kind", [("", "submit"), ("신청하기", "submit"), ("결제", "button"), ("삭제", "button"),
                                       ("검색 후 결제", "submit"), ("파일 올리기", "file"), ("저장", "button")])
def test_what_leaves_a_mark_is_still_blocked(name: str, kind: str) -> None:
    assert _read_only_blocks(name, kind), name


class _Locator:
    def __init__(self, search: bool) -> None:
        self.search, self.pressed = search, []

    def evaluate(self, _script):
        return self.search

    def press(self, key):
        self.pressed.append(key)


def _worker(locator: _Locator) -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker.config = SimpleNamespace(browser_read_only=True)
    worker._ref_locator = lambda _page, _ref: locator  # type: ignore[method-assign]
    worker._evidence = lambda kind, **fields: {"kind": kind, **fields}  # type: ignore[method-assign]
    return worker


def test_enter_in_a_search_box_goes_through() -> None:
    locator = _Locator(search=True)
    _worker(locator)._press(None, {"ref": "j8", "key": "Enter"})
    assert locator.pressed == ["Enter"]


def test_enter_elsewhere_is_still_blocked() -> None:
    locator = _Locator(search=False)
    with pytest.raises(RuntimeError, match="read_only_enter_blocked"):
        _worker(locator)._press(None, {"ref": "j3", "key": "Enter"})
    assert locator.pressed == []
