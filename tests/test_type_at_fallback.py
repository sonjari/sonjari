"""좌표 입력은 **들어갔는지 확인하고**, 안 들어갔으면 도구가 다음 단계를 밟는다 — 진짜 크로미움 (2026-09-29 밤).

한방 도전 W1(가계부): 예산 칸에 좌표로 14번 쳤다. 칸은 `type=number`, 모델은 「100,000」을 쳤다 — 숫자 칸은 쉼표 든 글자를
**조용히 거절**해 빈 칸으로 남는데, 도구는 확인 없이 「성공」을 돌려줬다. 762초 판의 약 8분이 여기였다.
단계: ① 사람처럼 누르고 친다 → ② 분명히 비었으면 그 칸에 값을 직접 넣고 input·change 를 쏜다 → ③ 그래도 안 되면 정직하게 실패.
"""

from __future__ import annotations

from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from alture_jarvis.browser import BrowserWorker, _coerce_expect  # noqa: E402
from alture_jarvis.config import JarvisConfig  # noqa: E402

PAGE = """<!doctype html><html><body style="margin:40px">
<input id="budget" type="number" placeholder="예산을 입력하세요 (원)" style="width:300px;height:36px"><br><br>
<input id="swallow" type="text" placeholder="메모" style="width:300px;height:36px"><br><br>
<input id="locked" type="text" readonly placeholder="잠김" style="width:300px;height:36px">
<p id="mirror"></p>
<script>
  document.getElementById('swallow').addEventListener('keydown', (e) => e.preventDefault());
  document.getElementById('swallow').addEventListener('input', (e) => { document.getElementById('mirror').textContent = e.target.value; });
</script></body></html>"""


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield launched
        launched.close()


@pytest.fixture()
def worker(tmp_path: Path, monkeypatch) -> BrowserWorker:
    made = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    monkeypatch.setattr(made.config, "browser_read_only", False, raising=False)
    return made


def _center(page, selector: str) -> dict[str, float]:
    box = page.evaluate(
        "(s) => { const r = document.querySelector(s).getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; }",
        selector,
    )
    return {"x": box["x"], "y": box["y"]}


def test_a_comma_number_in_a_number_field_ends_up_as_the_number(worker, browser) -> None:
    """헤드리스 크롬은 쉼표를 알아서 빼고 받았다(키보드 단계에서 끝). 어느 단계든 **값이 맞고 확인됐는가**를 본다."""
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    page.set_content(PAGE)
    result = worker._type_at(page, {**_center(page, "#budget"), "text": "100,000"})
    assert page.evaluate("() => document.getElementById('budget').value") == "100000"
    assert result["value_verified"] is True
    page.close()


def test_a_number_field_that_swallows_keys_gets_the_digits_directly(worker, browser) -> None:
    """키가 안 먹는 숫자 칸 — 직접 넣을 때 쉼표를 빼야 칸이 받는다."""
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    page.set_content(PAGE)
    page.evaluate("() => document.getElementById('budget').addEventListener('keydown', (e) => e.preventDefault())")
    result = worker._type_at(page, {**_center(page, "#budget"), "text": "100,000"})
    assert page.evaluate("() => document.getElementById('budget').value") == "100000"
    assert result["method"] == "direct_fill"
    page.close()


def test_a_field_that_swallows_keys_gets_the_value_and_the_page_hears_it(worker, browser) -> None:
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    page.set_content(PAGE)
    result = worker._type_at(page, {**_center(page, "#swallow"), "text": "점심 식대"})
    assert page.evaluate("() => document.getElementById('swallow').value") == "점심 식대"
    assert page.evaluate("() => document.getElementById('mirror').textContent") == "점심 식대", "input 이벤트가 안 가면 앱은 모른다"
    assert result["method"] == "direct_fill"
    page.close()


def test_an_ordinary_field_stays_on_the_human_path(worker, browser) -> None:
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    page.set_content(PAGE)
    result = worker._type_at(page, {**_center(page, "#budget"), "text": "250000"})
    assert result["method"] == "keyboard" and result["value_verified"] is True
    page.close()


def test_when_nothing_sticks_it_says_so_instead_of_claiming_success(worker, browser) -> None:
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    page.set_content(PAGE)
    with pytest.raises(RuntimeError, match="type_at_not_applied.*browser_fill"):
        worker._type_at(page, {**_center(page, "#locked"), "text": "바꿔 봐"})
    page.close()


def test_an_expectation_sent_as_text_does_not_kill_the_click() -> None:
    """W1 55·56번 걸음: `expect` 가 글자로 와서 클릭이 `'str' object has no attribute 'get'` 으로 죽었다."""
    parsed = _coerce_expect({"ref": "j2", "expect": '<{"kind": "text_appears", "value": "예산"}'})
    assert parsed == {"ref": "j2", "expect": {"kind": "text_appears", "value": "예산"}}
    assert _coerce_expect({"ref": "j2", "expect": "<{\"value\": 100,000}"}) == {"ref": "j2"}
    assert _coerce_expect({"ref": "j2", "expect": {"kind": "appears"}})["expect"] == {"kind": "appears"}


def test_code_mode_can_fill_what_it_built() -> None:
    """W1 16번 걸음: 모델이 `browser_fill` 을 먼저 불렀는데 코드 모드 목록에 없어 튕겼다."""
    from alture_jarvis.code_runtime import CODE_PREVIEW_TOOL_NAMES

    assert {"browser_fill", "browser_select_option", "browser_press", "browser_type_at"} <= CODE_PREVIEW_TOOL_NAMES


def test_a_false_written_as_text_is_false_at_the_gate(tmp_path) -> None:
    """W1: `submit="False"` 를 `bool()` 로 읽어 **참** — 칠 때마다 엔터가 눌려 폼이 제출되고 값이 날아갔다(14번).
    게이트웨이가 스키마의 boolean 칸만 바꾼다. 글자 칸의 「False」는 사용자가 넣으라 한 글자일 수 있어 그대로."""
    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.models import RiskLevel
    from alture_jarvis.tool_gateway import ToolGateway, ToolSpec, coerce_boolean_arguments

    schema = {"properties": {"text": {"type": "string"}, "submit": {"type": "boolean"}}}
    assert coerce_boolean_arguments(schema, {"text": "False", "submit": "False"}) == {"text": "False", "submit": False}
    assert coerce_boolean_arguments(schema, {"submit": "true"})["submit"] is True
    assert coerce_boolean_arguments(schema, {"submit": "maybe"})["submit"] == "maybe", "모르는 말은 추측하지 않는다"

    seen: list[dict] = []
    gateway = ToolGateway(JobStore(tmp_path / "j.db"), EventBus())
    gateway.register(ToolSpec("fake_type_at", "좌표 입력", RiskLevel.L0, lambda args: seen.append(args) or {"ok": True},
                              parameters=schema))
    gateway.execute("fake_type_at", {"text": "100000", "submit": "False"})
    assert seen == [{"text": "100000", "submit": False}]


def test_the_real_type_at_schema_marks_submit_as_boolean() -> None:
    """변환은 스키마를 믿는다 — 도구 정의에서 submit 이 boolean 이 아니면 위 고침이 조용히 안 먹는다."""
    import inspect

    import alture_jarvis.browser as browser_module

    import re

    source = inspect.getsource(browser_module)
    found = re.search(r'self\._function\(\s*"browser_type_at",', source)
    assert found, "browser_type_at 도구 정의를 못 찾았다"
    assert '"submit": {"type": "boolean"}' in source[found.start():found.start() + 800]
