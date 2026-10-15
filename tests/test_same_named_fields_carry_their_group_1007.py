"""같은 이름의 칸이 둘 이상이면 **어느 묶음의 칸인지**가 같이 온다 (2026-10-07 폼 벤치 과제 J · 고치기 전 3판 중 1판).

라벨이 하나도 없는 폼에 「본인 정보 — 이름·연락처·주소」와 「비상 연락처 — 이름·연락처」가 있었다. 목록에는 「연락처 안의 input」이
둘이었고, 모델은 앞의 것(본인)에 새 번호를 넣은 뒤 「비상 연락처를 바꿨다」고 답했다. 고를 근거가 목록에 없었다.
배송지/청구지, 학력 1/학력 2 처럼 묶음이 되풀이되는 폼이 다 같은 모양이다.

제목을 낱말이나 태그로 찾지 않는다 — 같은 이름의 다른 칸과 **갈라지는 가지**가 그 칸의 묶음이다.
화면의 이름·번호는 지어낸 것이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

# 묶음을 감싼 폼 — 묶음마다 상자가 있고 그 첫 줄이 묶음 이름이다
WRAPPED = """<html><body><div class="form">
<div class="sec"><div class="t">본인 정보</div>
  <div class="row"><div>이름</div><input value="김가온"></div>
  <div class="row"><div>연락처</div><input value="010-0000-0101"></div>
  <div class="row"><div>주소</div><input value="가람시 새봄구 한빛로 12"></div></div>
<div class="sec"><div class="t">비상 연락처</div>
  <div class="row"><div>이름</div><input value="김나래"></div>
  <div class="row"><div>연락처</div><input value="010-0000-0202"></div></div>
<button type="button">저장</button></div></body></html>"""

# 제목과 줄이 나란히 놓인 폼 — 묶음 상자가 없다
FLAT = """<html><body><div class="form">
<div class="t">본인 정보</div>
<div class="row"><div>이름</div><input value="김가온"></div>
<div class="row"><div>연락처</div><input value="010-0000-0101"></div>
<div class="t">비상 연락처</div>
<div class="row"><div>이름</div><input value="김나래"></div>
<div class="row"><div>연락처</div><input value="010-0000-0202"></div>
<button type="button">저장</button></div></body></html>"""

# 이름이 겹치지 않는 폼 — 붙일 것이 없다
UNIQUE = """<html><body><div class="form"><div class="t">본인 정보</div>
<div class="row"><div>이름</div><input value="김가온"></div>
<div class="row"><div>연락처</div><input value="010-0000-0101"></div>
<button type="button">저장</button></div></body></html>"""

# 같은 이름의 칸 둘이 한 묶음 안에 있다 — 묶음 이름으로는 못 가린다
SAME_GROUP = """<html><body><div class="form"><div class="t">연락처 목록</div>
<div class="row"><div>연락처</div><input value="010-0000-0101"></div>
<div class="row"><div>연락처</div><input value="010-0000-0202"></div>
<button type="button">저장</button></div></body></html>"""


@pytest.fixture()
def browser(tmp_path: Path):
    playwright_api = pytest.importorskip("playwright.sync_api")
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o",
                                        browser_visual_overlay=False, browser_read_only=False))
    with playwright_api.sync_playwright() as p:
        try:
            chromium = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            yield worker, chromium.new_page()
        finally:
            chromium.close()


def _inputs(worker: BrowserWorker, page, html: str) -> list[dict]:
    page.set_content(html)
    return [e for e in worker._snapshot(page, {})["elements"] if e.get("tag") == "input"]


@pytest.mark.parametrize("html", [WRAPPED, FLAT], ids=["묶음을 감싼 폼", "제목과 줄이 나란한 폼"])
def test_each_of_two_same_named_fields_says_which_group_it_is_in(browser, html: str) -> None:
    worker, page = browser
    inputs = _inputs(worker, page, html)

    by_value = {e["value"]: e.get("group") for e in inputs}
    assert by_value["010-0000-0101"] == "본인 정보"
    assert by_value["010-0000-0202"] == "비상 연락처"
    assert by_value["김가온"] == "본인 정보" and by_value["김나래"] == "비상 연락처"


def test_a_field_whose_name_is_not_repeated_gets_no_group(browser) -> None:
    worker, page = browser
    assert all("group" not in e for e in _inputs(worker, page, UNIQUE))
    # 겹치는 이름이 있는 폼에서도, 하나뿐인 칸(주소)에는 안 붙는다
    address = next(e for e in _inputs(worker, page, WRAPPED) if e["value"].startswith("가람시"))
    assert "group" not in address


def test_a_group_name_that_tells_nothing_apart_is_not_added(browser) -> None:
    worker, page = browser
    assert all("group" not in e for e in _inputs(worker, page, SAME_GROUP))


def test_the_fill_says_which_group_it_filled_and_find_can_use_the_group(browser) -> None:
    worker, page = browser
    inputs = _inputs(worker, page, FLAT)
    emergency = next(e for e in inputs if e["value"] == "010-0000-0202")

    filled = worker._fill(page, {"ref": emergency["ref"], "value": "010-0000-0303"})

    assert filled["field"].startswith("비상 연락처 › "), filled["field"]
    assert page.evaluate("() => [...document.querySelectorAll('input')].map(i => i.value)")[3] == "010-0000-0303"
    found = worker._find(page, {"query": "비상 연락처", "limit": 10})
    assert {m["ref"] for m in found["matches"]} >= {emergency["ref"]}
