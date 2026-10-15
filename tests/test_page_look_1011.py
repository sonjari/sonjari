"""만든 화면을 눈으로 본다 — 화면 없는 크롬으로 따로 통째로 찍어 모델에게 보여 준다 (2026-10-11).

손자리는 화면을 못 찍었다(뒤에서 도는 탭은 그림으로 안 찍힌다 · 찍혀도 모델에게 안 간다). 그래서 디자인 스킬이
「화면을 찍어 확인하라」고 해도 따를 길이 없었다. 계산 검사(`layout_probe`)가 못 재는 것 — 흐린 글자 · 어색한 자리 — 을 위해 만든다.

지키는 것
- 이 PC 안 페이지에서만 본다. 남의 사이트에는 크롬을 띄우지도 않는다.
- 본 것은 **인상**이라는 딱지를 붙인다(자리는 맞아도 설명이 틀릴 수 있다 — 재 보니 그랬다).
- 「이상 없음」이면 아무 말도 안 붙인다. 눈이 없거나 보다 틀어져도 페이지 열기는 그대로 성공한다.
- 보는 동안 화면 카드에 그 그림을 비추고, 다 보면 거둔다.
"""
from __future__ import annotations

import inspect
import io
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import page_look
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime


def _png(width: int, height: int) -> bytes:
    image_module = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image_module.new("RGB", (width, height), (250, 245, 238)).save(buffer, format="PNG")
    return buffer.getvalue()


# --- 말 옮기기 -------------------------------------------------------------------

def test_no_problem_answers_are_recognised() -> None:
    for said in ("이상 없음", "「이상 없음」", "이상 없습니다.", "문제 없음", "No issues found.", "", "   "):
        assert page_look.saw_nothing(said), repr(said)
    for said in ("상단 제목이 배경과 대비가 낮아 흐릿합니다.", "이상 없어 보이지만 하단 버튼이 겹칩니다"):
        assert not page_look.saw_nothing(said), said


def test_what_the_eye_saw_is_handed_over_as_an_impression() -> None:
    note = page_look.look_note("상단 히어로 섹션의 큰 제목이 배경과 대비가 낮아 흐릿하게 보입니다.")

    assert note.startswith("👁") and "틀릴 수 있다" in note and "확인하라" in note and "흐릿하게" in note
    assert "첫 모습" in note, "따로 띄운 크롬은 그 주소를 새로 열었을 때의 모습을 본다"
    assert page_look.look_note("이상 없음") == "" and page_look.look_note("") == ""


def test_the_shot_is_shrunk_to_the_width_the_eye_was_measured_at() -> None:
    image_module = pytest.importorskip("PIL.Image")

    jpeg, width, height = page_look.shrink_for_eyes(_png(1280, 2571))

    assert (width, height) == (1000, 2008) and image_module.open(io.BytesIO(jpeg)).size == (1000, 2008)
    assert page_look.shrink_for_eyes(_png(800, 600))[1:] == (800, 600), "작은 그림은 키우지 않는다"
    assert page_look.shrink_for_eyes(b"not a picture") == (b"", 0, 0)


# --- 브라우저: 언제 보고 무엇을 돌려주는가 ------------------------------------------

class _Page:
    def __init__(self, url: str) -> None:
        self.url = url


def _worker(monkeypatch: pytest.MonkeyPatch, *, eye: Any, shot: bytes | None = None) -> tuple[BrowserWorker, dict[str, Any]]:
    seen: dict[str, Any] = {"rendered": [], "told": []}
    worker = object.__new__(BrowserWorker)
    worker._playwright = object()
    worker._find_chrome = lambda: r"C:\somewhere\chrome.exe"   # type: ignore[method-assign]
    if eye is not None:
        worker.page_eye = eye
    worker.image_read_sink = seen["told"].append

    def fake_render(playwright: Any, chrome_path: str, url: str) -> bytes:
        seen["rendered"].append((chrome_path, url))
        return _png(1280, 1600) if shot is None else shot

    monkeypatch.setattr(page_look, "render_apart", fake_render)
    return worker, seen


def test_a_local_page_is_shot_apart_and_shown_to_the_eye(monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[bytes] = []

    def eye(jpeg: bytes) -> str:
        got.append(jpeg)
        return "상단 제목이 배경과 대비가 낮아 흐릿합니다."

    worker, seen = _worker(monkeypatch, eye=eye)

    said = worker._look_at_local_page(_Page("http://127.0.0.1:54513/index.html"))

    assert said == "상단 제목이 배경과 대비가 낮아 흐릿합니다."
    assert seen["rendered"] == [(r"C:\somewhere\chrome.exe", "http://127.0.0.1:54513/index.html")]
    assert len(got) == 1 and got[0][:3] == b"\xff\xd8\xff", "모델에게는 줄인 JPEG 한 장이 간다"
    shown = [row for row in seen["told"] if not row.get("done")]
    assert len(shown) == 1 and shown[0]["kind"] == "page" and shown[0]["picture"].startswith("data:image/jpeg;base64,")
    assert seen["told"][-1] == {"done": True}, "다 보면 거둔다"


def test_someone_elses_site_is_never_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    worker, seen = _worker(monkeypatch, eye=lambda jpeg: "뭔가 이상합니다")

    assert worker._look_at_local_page(_Page("https://www.danawa.com/")) == ""
    assert seen["rendered"] == [] and seen["told"] == [], "크롬을 띄우지도, 카드에 비추지도 않는다"


def test_nothing_wrong_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    worker, seen = _worker(monkeypatch, eye=lambda jpeg: "「이상 없음」")

    assert worker._look_at_local_page(_Page("http://localhost:5173/")) == ""
    assert seen["told"][-1] == {"done": True}


def test_no_eye_no_shot_and_a_broken_eye_breaks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    worker, seen = _worker(monkeypatch, eye=None)
    assert worker._look_at_local_page(_Page("http://localhost:5173/")) == "" and seen["rendered"] == []

    def broken(jpeg: bytes) -> str:
        raise RuntimeError("model has no eyes")

    worker, seen = _worker(monkeypatch, eye=broken)
    assert worker._look_at_local_page(_Page("http://localhost:5173/")) == ""
    assert seen["told"][-1] == {"done": True}, "눈이 틀어져도 카드는 거둔다"

    worker, seen = _worker(monkeypatch, eye=lambda jpeg: "뭔가", shot=b"")
    assert worker._look_at_local_page(_Page("http://localhost:5173/")) == "" and seen["told"] == [], "못 찍었으면 보여 줄 것이 없다"


def test_opening_measures_first_and_looks_second() -> None:
    source = inspect.getsource(BrowserWorker._open)

    assert source.index("self._layout_check(page)") < source.index("self._look_at_local_page(page)")
    assert source.index("_layout_probe.layout_note(layout_lines)") < source.index("_page_look.look_note(looked)"), (
        "참·거짓이 분명한 계산 결과를 앞에, 눈으로 본 인상을 뒤에 둔다"
    )


# --- 진짜로 찍어 본다 --------------------------------------------------------------

def test_a_page_is_shot_from_top_to_bottom_but_not_past_the_limit(tmp_path: Path) -> None:
    image_module = pytest.importorskip("PIL.Image")
    playwright_api = pytest.importorskip("playwright.sync_api")
    short = tmp_path / "short.html"
    short.write_text("<body style='margin:0'><div style='height:1500px;background:#faf5ee'>가게</div></body>", encoding="utf-8")
    tall = tmp_path / "tall.html"
    tall.write_text("<body style='margin:0'><div style='height:9000px;background:#faf5ee'>긴 페이지</div></body>", encoding="utf-8")
    with playwright_api.sync_playwright() as p:
        try:
            p.chromium.launch(headless=True).close()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        first = page_look.render_apart(p, "", short.as_uri())
        second = page_look.render_apart(p, "", tall.as_uri())
        missing = page_look.render_apart(p, "", (tmp_path / "nowhere.html").as_uri())

    assert image_module.open(io.BytesIO(first)).size == (page_look.SHOT_WIDTH, 1500), "화면 한 칸이 아니라 통째로"
    assert image_module.open(io.BytesIO(second)).size == (page_look.SHOT_WIDTH, page_look.SHOT_MAX_HEIGHT)
    assert isinstance(missing, bytes), "없는 페이지에도 죽지 않는다"


# --- 런타임 · 설정 ----------------------------------------------------------------

def test_the_runtime_gives_the_browser_an_eye_unless_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    source = inspect.getsource(JarvisRuntime.__init__)
    assert "if self.config.page_eye_enabled:" in source and "self.browser.page_eye = self._look_at_page" in source
    look = inspect.getsource(JarvisRuntime._look_at_page)
    assert "temperature=0.0" in look and "think=False" in look and "page_look.LOOK_PROMPT" in look

    assert JarvisConfig().page_eye_enabled is True
    monkeypatch.setenv("JARVIS_PAGE_EYE_ENABLED", "0")
    assert JarvisConfig.from_env().page_eye_enabled is False


def test_a_call_cut_at_the_length_limit_is_recorded() -> None:
    """한도에 걸려 끊긴 호출은 지금까지 어디에도 안 남았다 — 일어난 사실을 판 결과에 남긴다(한도는 그대로)."""
    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent)
    assert '"why": "length_limit"' in source and 'get("done_reason") == "length"' in source
