"""장표 번호는 부품이 아니라 **장**이 센다 (2026-10-28 · 실제 판 a5fb5da7 · grove 결 slide_03 · slide_04).

요점(points)이 한 장에 여러 개 쌓이면 부품마다 1부터 다시 세어 「01 01 01」이 됐다. 단계(steps)는 CSS 카운터를 부품(ol)마다
리셋해서 같은 병이 있었다. 둘 다 장 단위로 이어 센다.
"""

from __future__ import annotations

import re

import pytest

from alture_jarvis import slide_parts


def _points(count: int, tag: str = "p") -> dict:
    return {"part": "points", "items": [{"title": f"{tag}{i}", "text": f"{tag} 설명 {i}"} for i in range(1, count + 1)]}


def _numbers(html: str) -> list[str]:
    return re.findall(r'<span class="n">(\d\d)</span><b class="t">', html)


def _slide(*cards: dict) -> dict:
    return {"head": "번호 시험", "cols": [list(cards)]}


def test_three_points_with_one_item_each_count_01_02_03() -> None:
    html = slide_parts.render(_slide(_points(1, "a"), _points(1, "b"), _points(1, "c")))
    assert _numbers(html) == ["01", "02", "03"]


def test_two_points_with_two_items_each_count_01_to_04() -> None:
    html = slide_parts.render(_slide(_points(2, "a"), _points(2, "b")))
    assert _numbers(html) == ["01", "02", "03", "04"]


def test_numbers_start_again_on_the_next_slide() -> None:
    first = slide_parts.render(_slide(_points(2, "a"), _points(1, "b")))
    second = slide_parts.render(_slide(_points(1, "c")))
    assert _numbers(first) == ["01", "02", "03"]
    assert _numbers(second) == ["01"], "장이 바뀌면 다시 01"


def test_other_parts_between_points_do_not_break_the_count() -> None:
    stat = {"part": "stat", "value": "12", "label": "건"}
    html = slide_parts.render(_slide(_points(1, "a"), stat, _points(2, "b")))
    assert _numbers(html) == ["01", "02", "03"]


def test_the_count_runs_across_columns_in_reading_order() -> None:
    spec = {"head": "두 칸", "layout": "1:1", "cols": [[_points(2, "a")], [_points(1, "b")]]}
    assert _numbers(slide_parts.render(spec)) == ["01", "02", "03"]


def test_a_shown_item_that_is_not_a_dict_is_not_counted() -> None:
    card = {"part": "points", "items": [{"title": "a", "text": "x"}, "문자열은 안 그린다"]}
    html = slide_parts.render(_slide(card, _points(1, "b")))
    assert _numbers(html) == ["01", "02"]


@pytest.mark.parametrize("theme_css", ["common.css", "ir-brief"])
def test_step_numbers_are_reset_once_per_slide_not_once_per_list(theme_css: str) -> None:
    from pathlib import Path

    root = Path(slide_parts.__file__).parent / "slide_themes"
    css = (root / "parts" / "common.css").read_text(encoding="utf-8") if theme_css == "common.css" \
        else (root / "own" / "ir-brief" / "theme.css").read_text(encoding="utf-8")
    steps_ol = re.search(r"\.(?:pz-slide|ir-parts) \.pz-steps ol \{[^}]*\}", css)
    assert steps_ol and "counter-reset" not in steps_ol.group(0), "단계 목록마다 리셋하면 부품마다 1부터 다시 센다"
    assert re.search(r"\.(?:pz-slide|ir-parts) \{ counter-reset: s; \}", css), "리셋은 장에 한 번"


def test_two_step_lists_on_one_slide_show_1_2_3_4_in_a_real_browser() -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    steps = lambda *names: {"part": "steps", "items": [{"title": name} for name in names]}  # noqa: E731
    html = slide_parts.render(_slide(steps("가", "나"), steps("다", "라")))
    other = slide_parts.render(_slide(steps("마")))
    css = slide_parts.parts_css("grove")
    assert css, "grove 결은 부품 묶음에 있어야 한다"
    page_html = f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>{html}{other}</body></html>"
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.set_content(page_html)
            # 의사요소(::before)의 카운터 값은 getComputedStyle 이 풀어 주지 않는다(「counter(s)」 그대로) — 그려진 글을 CDP 스냅샷으로 읽는다.
            session = page.context.new_cdp_session(page)
            snap = session.send("DOMSnapshot.captureSnapshot", {"computedStyles": []})
            strings = snap["strings"]
            layout = snap["documents"][0]["layout"]
            texts = [strings[i] for i in layout.get("text", []) if i >= 0]
            shown = [text.strip() for text in texts if re.fullmatch(r"\s*\d\s*", text)]
        finally:
            browser.close()
    assert shown == ["1", "2", "3", "4", "1"], "한 장에서는 이어서, 다음 장에서는 다시 1"
