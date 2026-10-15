"""폼 벤치 과제 G·H·I 에서 나온 도구 버그 셋 (2026-10-07 · 고치기 전 3판씩: 자동완성 1/3 · 달력 0/3 · 파일 올리기 0/3).

1. **자동완성**: 모델이 칸에 글을 먼저 채우고 「그 글을 목록에서 골라라」를 불렀다. 후보를 찾는 코드는 값으로도 이름을 삼아서,
   값이 그 글인 **칸 자신**이 정확히 같은 후보가 됐고 문서에서 목록보다 앞이라 그것이 뽑혔다. 칸을 누르니 아무것도 안 골라졌다.
2. **달력**: 날짜를 `2026-02-02` 로 넣자 사이트가 칸을 비우고 받는 모양을 화면에 적었다. 누르기 전 확인은 「값이 달라졌다」까지만
   말해서 모델은 같은 모양으로 또 넣었다. 채운 뒤 **새로 나온 글**을 같이 건넨다.
3. **파일 올리기**: 파일 칸은 숨어 있고 「파일 선택」 단추가 그것을 연다. 모델이 줄 수 있는 번호는 단추뿐인데 도구는
   「파일 칸이 아니다」로 끝났다. 단추를 눌러 뜨는 파일 선택 창에 넣는다.

화면의 이름들은 지어낸 것이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

PAGE = r"""<html><head><title>이력서</title></head><body>
<div><label for="sch">학교명</label><input id="sch" data-jarvis-ref="j1"><ul id="list"></ul></div>
<div><input id="start" data-jarvis-ref="j2" aria-label="입사일"><p id="err"></p></div>
<button id="save" data-jarvis-ref="j3" type="button" onclick="document.title = 'saved:' + sch.value + '|' + start.value">저장</button>
<div><input id="file" type="file" style="display:none"><button id="pick" data-jarvis-ref="j4" type="button" onclick="file.click()">파일 선택</button>
<button id="plain" data-jarvis-ref="j5" type="button">미리보기</button><span id="got"></span></div>
<script>
  const NAMES = ['한빛가람대학교 대학원', '한빛가람대학교', '한빛가람대학교 새봄캠퍼스'];
  sch.addEventListener('input', () => {
    delete sch.dataset.picked;
    list.innerHTML = '';
    for (const name of NAMES.filter(n => sch.value && n.includes(sch.value))) {
      const li = document.createElement('li');
      li.textContent = name;
      li.onmousedown = (e) => e.preventDefault();
      li.onclick = () => { sch.value = name; sch.dataset.picked = 1; list.innerHTML = ''; };
      list.appendChild(li);
    }
  });
  // 후보를 안 고르고 떠나면 친 글을 지운다
  sch.addEventListener('blur', () => { if (!sch.dataset.picked) { sch.value = ''; list.innerHTML = ''; } });
  // 받는 모양이 아니면 칸을 비우고 까닭을 적는다
  start.addEventListener('blur', () => {
    if (start.value && !/^\d{4}\.\d{2}\.\d{2}$/.test(start.value)) {
      start.value = '';
      err.textContent = '날짜는 YYYY.MM.DD 형식으로 입력해 주세요';
    } else { err.textContent = ''; }
  });
  file.addEventListener('change', () => { got.textContent = file.files.length ? file.files[0].name : ''; });
</script></body></html>"""


@pytest.fixture()
def opened(tmp_path: Path):
    playwright_api = pytest.importorskip("playwright.sync_api")
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o",
                                        browser_visual_overlay=False, browser_read_only=False,
                                        browser_upload_allowed_roots=(str(tmp_path),)))
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.set_content(PAGE)
            yield worker, page, tmp_path
        finally:
            browser.close()


# ── 자동완성: 칸 자신은 후보가 아니다 ─────────────────────────────────────────
def test_the_field_being_filled_is_not_one_of_its_own_suggestions(opened) -> None:
    worker, page, _ = opened
    worker._fill(page, {"ref": "j1", "value": "한빛가람대학교"})

    picked = worker._pick_suggestion(page, {"ref": "j1", "choose": "한빛가람대학교"})

    assert picked["action"] == "suggestion_picked" and picked["verified"] is True, picked
    assert page.evaluate("() => [sch.value, sch.dataset.picked]") == ["한빛가람대학교", "1"]
    assert worker._click(page, {"ref": "j3"})["action"] == "clicked"
    assert page.title().startswith("saved:한빛가람대학교|")


def test_the_exact_suggestion_wins_over_the_first_one_that_contains_it(opened) -> None:
    """목록의 첫 줄은 「… 대학원」이다 — 글자가 정확히 같은 줄을 고른다."""
    worker, page, _ = opened

    worker._pick_suggestion(page, {"ref": "j1", "text": "한빛가람", "choose": "한빛가람대학교"})

    assert page.evaluate("() => sch.value") == "한빛가람대학교"


# ── 드롭다운: 이미 열린 목록을 닫지 않는다 ───────────────────────────────────
DROPDOWN = """<html><body>
<div id="trigger" data-jarvis-ref="j1" role="button" tabindex="0" onclick="list.hidden = !list.hidden">직종 선택</div>
<ul id="list" role="listbox" hidden>
  <li role="option" onclick="trigger.textContent = this.textContent; list.hidden = true">품질관리(QC)</li>
  <li role="option" onclick="trigger.textContent = this.textContent; list.hidden = true">품질보증(QA)</li>
</ul></body></html>"""


def test_a_dropdown_the_model_already_opened_is_not_closed_by_picking(opened) -> None:
    worker, page, _ = opened
    page.goto("about:blank")
    page.set_content(DROPDOWN)
    worker._click(page, {"ref": "j1"})                       # 모델이 먼저 눌러 열어 둔다
    assert page.evaluate("() => list.hidden") is False

    picked = worker._pick_suggestion(page, {"ref": "j1", "choose": "품질보증(QA)", "wait_ms": 800})

    assert picked["action"] == "suggestion_picked", picked
    assert page.evaluate("() => trigger.textContent") == "품질보증(QA)"


def test_a_closed_dropdown_is_still_opened_by_picking(opened) -> None:
    """역방향 — 닫혀 있으면 예전처럼 눌러서 연 뒤 고른다."""
    worker, page, _ = opened
    page.goto("about:blank")
    page.set_content(DROPDOWN)

    picked = worker._pick_suggestion(page, {"ref": "j1", "choose": "품질보증(QA)", "wait_ms": 800})

    assert picked["action"] == "suggestion_picked", picked
    assert page.evaluate("() => trigger.textContent") == "품질보증(QA)"


# ── 달력: 사이트가 한 말을 건넨다 ────────────────────────────────────────────
def test_what_the_site_wrote_after_the_fill_comes_with_the_held_click(opened) -> None:
    worker, page, _ = opened
    worker._fill(page, {"ref": "j2", "value": "2026-02-02"})

    held = worker._click(page, {"ref": "j3"})

    assert held["action"] == "not_clicked"
    assert held["site_said"] == ["날짜는 YYYY.MM.DD 형식으로 입력해 주세요"], held
    assert "site_said" in held["instruction"]
    assert page.title() == "이력서", "빈 날짜로 저장이 나가면 안 된다"

    worker._fill(page, {"ref": "j2", "value": "2026.02.02"})
    assert worker._click(page, {"ref": "j3"})["action"] == "clicked"
    assert page.title() == "saved:|2026.02.02"


def test_the_same_address_opened_again_hears_what_the_site_says_again(opened) -> None:
    """같은 주소를 다시 연 화면은 새 화면이다 — 앞에서 한 번 건넨 말이라고 이번에 입을 닫지 않는다."""
    worker, page, _ = opened
    for _round in range(2):
        page.goto("about:blank")      # 새 문서로 — 같은 문서에 두 번 써 넣으면 화면의 스크립트(const)가 두 번째에 죽는다
        page.set_content(PAGE)
        worker._fill(page, {"ref": "j2", "value": "2026-02-02"})

        held = worker._click(page, {"ref": "j3"})

        assert held["action"] == "not_clicked"
        assert held.get("site_said") == ["날짜는 YYYY.MM.DD 형식으로 입력해 주세요"], (_round, held)


def test_a_change_with_nothing_new_on_screen_says_nothing_extra(opened) -> None:
    """역방향 — 사이트가 말없이 지운 칸에는 site_said 가 없다(없는 말을 지어 붙이지 않는다)."""
    worker, page, _ = opened
    worker._fill(page, {"ref": "j1", "value": "한빛가람"})

    held = worker._click(page, {"ref": "j3"})

    assert held["action"] == "not_clicked" and "site_said" not in held, held


# ── 파일 올리기: 단추가 여는 파일 선택 창에 넣는다 ───────────────────────────
def test_a_file_goes_in_through_the_button_that_opens_the_hidden_file_field(opened) -> None:
    worker, page, folder = opened
    document = folder / "경력증명서_시험.txt"
    document.write_text("시험용 파일", encoding="utf-8")

    result = worker._file_upload(page, {"ref": "j4", "paths": [str(document)]})

    assert result["files"] == ["경력증명서_시험.txt"] and result.get("via") == "button", result
    assert page.evaluate("() => got.textContent") == "경력증명서_시험.txt"


def test_a_button_that_opens_no_file_dialog_is_named_as_such(opened) -> None:
    worker, page, folder = opened
    document = folder / "경력증명서_시험.txt"
    document.write_text("시험용 파일", encoding="utf-8")

    with pytest.raises(RuntimeError, match="not_a_file_control"):
        worker._file_upload(page, {"ref": "j5", "paths": [str(document)]})
    assert page.evaluate("() => got.textContent") == ""
