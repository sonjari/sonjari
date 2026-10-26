"""부품 조립을 결 24개 모두로 — 결을 「그리는 문법」 네 묶음으로 나눴다 (2026-10-25 대표 「유사도 · 유형으로 묶음집」).

line(선) · block(면) · round(둥근 칸) · sticky(붙인 종이). 묶음은 slide_themes/parts/<묶음>.css, 결마다 다른 것은 값(themes.json)뿐.
IR 브리프는 자기 부품 CSS 를 그대로 쓴다.
"""

import json
import re
from pathlib import Path

import pytest

from alture_jarvis import slide_parts, slides_style

SAMPLE = json.loads((Path(__file__).parent / "fixtures_ir_parts_sample.json").read_text(encoding="utf-8"))


def test_every_theme_supports_parts() -> None:
    missing = [name for name in slides_style.THEMES if not slide_parts.supports(name)]
    assert missing == []
    assert slide_parts.family("ir-brief") == ""  # IR 은 묶음 밖(자기 CSS)
    assert {slide_parts.family(name) for name in slides_style.THEMES} - {""} == {"line", "block", "round", "sticky"}


@pytest.mark.parametrize("theme", sorted(slides_style.THEMES))
def test_parts_slide_gets_family_css(theme: str) -> None:
    fragment, _, _ = slide_parts.build(SAMPLE[2])
    html, layout = slides_style.wrap_fragment(fragment, theme, title="t", index=2, total=5)
    if theme == "ir-brief":
        assert "data-sonjari-parts" not in html
        return
    assert layout == "parts"
    assert "data-sonjari-parts" in html and "--pz-bg:" in html
    family = slide_parts.family(theme)
    if family != "line":
        assert (Path(slide_parts._PARTS_DIR) / f"{family}.css").read_text(encoding="utf-8")[:60] in html
    assert '<div class="folio">' not in html  # 부품 장은 출처 줄이 바닥 — 쪽 표시를 겹쳐 넣지 않는다


def _rgb(value: str, base: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int] | None:
    value = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    match = re.fullmatch(r"rgba?\(([^)]*)\)", value)
    if match:
        parts = [float(x) for x in match.group(1).split(",")]
        alpha = parts[3] if len(parts) > 3 else 1.0
        return tuple(round(parts[i] * alpha + base[i] * (1 - alpha)) for i in range(3))  # type: ignore[return-value]
    return None


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    def lum(color: tuple[int, int, int]) -> float:
        def ch(x: float) -> float:
            x /= 255
            return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(color[0]) + 0.7152 * ch(color[1]) + 0.0722 * ch(color[2])
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


#: (글자, 바탕, 기준) — 본문 4.5, 큰 숫자 · 머리 · 덧말 3.0 (WCAG 큰 글자 기준).
PAIRS = [("ink", "bg", 4.5), ("sub", "bg", 3.0), ("key", "bg", 3.0), ("head_color", "bg", 3.0), ("card_ink", "card", 4.5),
         ("card_key", "card", 3.0), ("on_accent", "accent", 4.5), ("fill_2_ink", "fill_2", 4.5), ("c2_ink", "c2", 4.5),
         ("c3_ink", "c3", 4.5), ("c4_ink", "c4", 4.5), ("card_ink", "c1", 4.5)]


def test_token_contrast_meets_floor() -> None:
    """결 값의 글자 · 바탕 짝이 읽히는가 — 10-25 처음 잴 때 185짝 중 8짝이 모자랐다(고침)."""
    short = []
    checked = 0
    for theme in slide_parts.FAMILIES:
        tokens = slide_parts.theme_tokens(theme)
        for fg_name, bg_name, need in PAIRS:
            bg = _rgb(tokens.get(bg_name, ""))
            fg = _rgb(tokens.get(fg_name, ""), bg) if bg else None
            if not bg or not fg:
                continue  # var(--…) 로 적은 우리 결 다섯은 원래 결 CSS 의 짝을 따른다
            checked += 1
            if _contrast(fg, bg) < need:
                short.append(f"{theme} {fg_name}/{bg_name} {_contrast(fg, bg):.2f}")
    assert checked >= 150
    assert short == []
