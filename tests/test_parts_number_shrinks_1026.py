"""부품 장의 숫자 칸(.n)이 좁은 카드에서 넘치면 그 숫자만 줄인다 — 그리고 뒤 단계(빈 칸 키우기)가 그 크기를 지우지 않는다 (2026-10-26).

sakura 판 둘(2dac3245 · 3abc60a7)의 「4,820만 원」이 48px 넘쳐 돌려보내졌다. 줄이기 목록에 .n 이 없었고, 키우기를 되돌릴 때
font-size 를 지워 줄여 둔 크기까지 날렸다. 지난 부품 장 113개 다시 재기: 넘침 3 → 0 · 나빠진 장 0.
"""

from pathlib import Path

from alture_jarvis import slide_parts, slides, slides_style


def test_a_wide_metric_number_is_shrunk_and_kept(tmp_path: Path) -> None:
    metrics = {"part": "metrics", "items": [
        {"label": "3분기 매출", "value": "4,820", "unit": "만 원", "note": "2분기 3,950만 원"},
        {"label": "하루 손님", "value": "142", "unit": "명"}, {"label": "재방문", "value": "46", "unit": "%"},
        {"label": "흑임자 라떼", "value": "18", "unit": "%"}]}
    photo = {"part": "photo", "label": "매장 전경", "ratio": "4:3"}
    frag, _, _, _ = slide_parts.build_with_fixes({"head": "3분기 한눈에", "layout": "1:1", "cols": [[metrics], [photo]]})
    html, _ = slides_style.wrap_fragment(frag, "sakura-chroma", title="t", index=2, total=7)
    page = tmp_path / "slide_02.html"
    page.write_text(slides.clean_slide_html(html), encoding="utf-8")
    shape = slides.fit_slide(page)
    assert shape["overflow_before"] > 0 and shape["overflow"] == 0  # 넘쳤던 장이 숫자만 줄여 맞았다
    saved = page.read_text(encoding="utf-8")
    assert "4,820" in saved and "font-size" in saved.split("<body", 1)[1]


def test_a_photo_slot_counts_as_filled_for_the_sparse_check(tmp_path: Path) -> None:
    """10-26 3판씩 재기: 「비었다」 27번 중 9번이 사진 칸 장 — 사람이 사진을 넣을 칸을 빈 곳으로 셌다. 판정은 사진 칸을 채운 자리로."""
    text = {"part": "text", "title": "잘한 점", "items": ["아침 7시 개점", "도서관 도장 행사"]}
    photo = {"part": "photo", "label": "매장 전경", "ratio": "3:4"}
    frag, _, _, _ = slide_parts.build_with_fixes({"head": "잘한 점", "layout": "1:1", "cols": [[text], [photo]]})
    html, _ = slides_style.wrap_fragment(frag, "grove", title="t", index=3, total=7)
    page = tmp_path / "slide_03.html"
    page.write_text(slides.clean_slide_html(html), encoding="utf-8")
    assert float(slides.fit_slide(page)["empty"]) <= 0.4
