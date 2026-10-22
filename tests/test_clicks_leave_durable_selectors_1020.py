"""누르고 채운 요소를 **다음 판에서도 찾을 셀렉터**로 남긴다 (2026-10-20 · 확장 설계 P1 「잘 해낸 판 → 레시피」).

판 기록의 `j5` 는 그 판의 스냅샷 번호라 다음 판에서는 아무것도 아니다. 클릭 · 입력 · 키 누르기 증거에 `selectors` 를 싣고,
그 후보가 정말로 **같은 요소**를 다시 찾는지 실제 크로미움에서 본다. 처음 짠 판은 `data-placeholder` 를 `placeholder` 로
적어 다음 판에 안 걸리는 후보를 냈다 — 그래서 「적었다」가 아니라 「다시 찾힌다」를 시험한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.agent import _step_evidence
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

PAGE = """<html><head><title>가게</title></head><body>
<input id="q" name="query" placeholder="상품 검색" data-jarvis-ref="j1">
<div contenteditable="true" data-placeholder="무엇이든 물어보세요" data-jarvis-ref="j2"></div>
<button data-testid="sort-low" data-jarvis-ref="j3" type="button" onclick="document.title='정렬됨'">낮은 가격순</button>
<button id="r9f8e7d6c" data-jarvis-ref="j4" type="button">더 보기</button>
</body></html>"""


@pytest.fixture()
def opened(tmp_path: Path):
    playwright_api = pytest.importorskip("playwright.sync_api")
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.set_default_timeout(3000)
            page.set_content(PAGE)
            yield worker, page
        finally:
            browser.close()


def _finds_the_same(page, ref: str, selectors: list[str]) -> None:
    assert selectors, "후보가 하나도 없다"
    element = page.locator(f'[data-jarvis-ref="{ref}"]').element_handle()
    for selector in selectors:
        assert page.locator(selector).first.evaluate("(a, b) => a === b", element), selector


def test_a_click_records_selectors_that_find_the_same_button(opened) -> None:
    worker, page = opened
    clicked = worker._click(page, {"ref": "j3"})
    assert clicked["action"] == "clicked"
    assert '[data-testid="sort-low"]' in clicked["selectors"]
    _finds_the_same(page, "j3", clicked["selectors"])


def test_a_fill_and_a_press_record_selectors(opened) -> None:
    worker, page = opened
    filled = worker._fill(page, {"ref": "j1", "value": "닌텐도 스위치 2"})
    assert '[placeholder="상품 검색"]' in filled["selectors"]
    _finds_the_same(page, "j1", filled["selectors"])
    pressed = worker._press(page, {"ref": "j1", "key": "Enter"})
    _finds_the_same(page, "j1", pressed["selectors"])


def test_a_data_placeholder_is_written_under_its_own_name(opened) -> None:
    worker, page = opened
    selectors = worker._durable_selectors(page.locator('[data-jarvis-ref="j2"]'))
    assert selectors == ['[data-placeholder="무엇이든 물어보세요"]']
    _finds_the_same(page, "j2", selectors)


def test_a_generated_looking_id_is_not_used(opened) -> None:
    worker, page = opened
    selectors = worker._durable_selectors(page.locator('[data-jarvis-ref="j4"]'))
    assert not any(selector.startswith("#") for selector in selectors)
    _finds_the_same(page, "j4", selectors)


def test_the_trace_keeps_the_selectors() -> None:
    """판 기록은 목록 항목을 80자로 자른다 — 후보는 80자 안이라 그대로 남는다."""
    kept = _step_evidence({"action": "clicked", "ref": "j3", "selectors": ['[data-testid="sort-low"]', 'text="낮은 가격순"']})
    assert kept["selectors"] == ['[data-testid="sort-low"]', 'text="낮은 가격순"']


def test_a_broken_locator_gives_no_selectors_and_does_not_raise() -> None:
    class Broken:
        def evaluate(self, *_args):
            raise RuntimeError("detached")

    assert BrowserWorker._durable_selectors(Broken()) == []
