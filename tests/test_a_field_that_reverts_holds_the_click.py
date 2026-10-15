"""채운 칸이 **포커스가 떠나는 순간 되돌아가면** 누르지 않고 알린다 (2026-10-06 r/AI_Agents 댓글 · Mind2Web WebMD 위치).

자동완성 칸은 후보를 안 고르고 떠나면 친 글을 지운다. 채운 직후의 되읽기(`_fill`)는 그 뒤를 못 본다 — 모델은 채웠다고
믿고 검색을 눌렀고 빈 칸으로 검색이 나갔다. 되돌림은 **그 누르기 때문에** 일어나므로 누른 뒤에 보면 늦다.
누르기 직전에 칸을 먼저 떠나 보고, 달라졌으면 누르지 않는다. 한 번만 붙잡는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

PAGE = """<html><head><title>검색</title></head><body>
<input id="city" data-jarvis-ref="j1" aria-label="도시">
<input id="memo" data-jarvis-ref="j3" aria-label="메모">
<input id="phone" data-jarvis-ref="j4" aria-label="전화">
<button id="go" data-jarvis-ref="j2" type="button" onclick="document.title = 'clicked:' + city.value">찾기</button>
<ul><li><button id="pick" data-jarvis-ref="j5" type="button"
  onmousedown="event.preventDefault()" onclick="city.dataset.picked = 1; city.value = 'Seoul, South Korea'">Seoul, South Korea</button></li></ul>
<script>
  // 후보를 안 고르고 포커스가 떠나면 친 글을 지운다 — 흔한 자동완성 위젯의 모양
  city.addEventListener('blur', () => { if (!city.dataset.picked) city.value = ''; });
  // 떠날 때 꼴만 바꾼다
  phone.addEventListener('blur', () => { phone.value = phone.value.replace(/(\\d{3})(\\d{4})(\\d{4})/, '$1-$2-$3'); });
</script></body></html>"""


def test_the_print_ignores_formatting_but_not_content() -> None:
    same = BrowserWorker._value_print
    assert same("01012345678") == same("010-1234-5678")
    assert same("seoul") == same("Seoul")
    assert same("2026-10-05") == same("10/05/2026")
    assert same("seoul") != same("")
    assert same("seoul") != same("busan")


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
            page.set_content(PAGE)
            yield worker, page
        finally:
            browser.close()


def test_a_field_that_empties_on_leaving_holds_the_click_once(opened) -> None:
    worker, page = opened
    worker._fill(page, {"ref": "j1", "value": "seoul"})

    held = worker._click(page, {"ref": "j2"})

    assert held["action"] == "not_clicked"
    assert held["fields_changed"] == [{"field": "도시", "filled_chars": 5, "now": "", "now_chars": 0}]
    assert page.title() == "검색", "빈 칸으로 찾기가 나가면 안 된다"

    # 같은 상태로 다시 누르면 그때는 누른다 — 일부러 비운 칸일 수 있다.
    again = worker._click(page, {"ref": "j2"})
    assert again["action"] == "clicked"
    assert page.title() == "clicked:"


def test_a_field_that_keeps_its_value_does_not_hold_anything(opened) -> None:
    """역방향 — 평범한 칸은 한 번에 눌린다."""
    worker, page = opened
    worker._fill(page, {"ref": "j3", "value": "메모 한 줄"})

    assert worker._click(page, {"ref": "j2"})["action"] == "clicked"


def test_reformatting_on_leaving_is_not_a_change(opened) -> None:
    worker, page = opened
    worker._fill(page, {"ref": "j4", "value": "01012345678"})

    assert worker._click(page, {"ref": "j2"})["action"] == "clicked"
    assert page.evaluate("() => phone.value") == "010-1234-5678"


def test_picking_from_the_list_is_not_disturbed_and_becomes_the_new_value(opened) -> None:
    """목록 안의 것을 누를 때는 칸을 먼저 떠나지 않는다(목록이 닫힌다). 고른 값이 새 기준이 된다."""
    worker, page = opened
    worker._fill(page, {"ref": "j1", "value": "seoul"})

    assert worker._click(page, {"ref": "j5"})["action"] == "clicked"
    assert page.evaluate("() => city.value") == "Seoul, South Korea"
    worker._resettle_fields(page)

    assert worker._click(page, {"ref": "j2"})["action"] == "clicked"
    assert page.title() == "clicked:Seoul, South Korea"
