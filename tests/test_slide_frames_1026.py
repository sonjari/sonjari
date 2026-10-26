"""표지 · 마무리 부품 · 장식 부품 · 장표 유형 · 글 겹침 검사 (2026-10-26 대표 「템플릿에 종속되면 큰일난다」).

계기: 10-26 13:40 실제 판(cobalt-grid) — 표지가 템플릿 통째라 짧은 꼬리말 칸에 긴 문장이 들어가 아래 작은 바닥 글과 겹쳤다.
넘침 검사는 「장 밖으로」만 봐서 못 잡았다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from alture_jarvis import slide_frames, slide_parts, slides, slides_style
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

THEMES = [key for key in slides_style.THEMES if slide_parts.supports(key)]
COVER = {"frame": "cover", "kicker": "국내 뉴스 브리핑 · 3건", "title": "국내 AI 에이전트 최근 소식",
         "sub": "2026년 10월 26일 기준, 네이버 뉴스에서 확인한 국내 AI 에이전트 관련 최근 소식.",
         "meta": [["정리", "로보메타핏 · 대표이사 보고용"], ["범위", "국내 AI 에이전트 관련 최근 기사 3건"]], "note": "2026.10.26 · 네이버 뉴스"}
_HAS_CHROME = bool(shutil.which("chrome") or Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe").exists()
                   or Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe").exists())


def _tools(tmp_path: Path) -> LocalComputerTools:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=str(tmp_path / "docs"))
    tools = LocalComputerTools(config)
    tools.publish = lambda event, payload: None
    return tools


@pytest.mark.parametrize("theme", THEMES)
def test_every_theme_builds_a_cover_and_closing_from_parts_not_from_its_template(theme: str) -> None:
    for kind, index in (("cover", 1), ("closing", 8)):
        html, sig, names, fixed = slide_parts.build_with_fixes(dict(COVER, frame=kind), theme, index, 8)
        assert sig.startswith(f"frame:{kind}:") and f"frame-{kind}" in names and not fixed
        assert "pz-frame" in html and "국내 AI 에이전트 최근 소식" in html and f"{index:02d} / 08" in html
        # 글은 위에서 아래로 흐르는 한 줄기 — 글 칸에 절대 위치를 쓰지 않는다(겹칠 수 없게).
        assert "position:absolute" not in html.split('<div class="fr-main">', 1)[1]
        wrapped, layout = slides_style.wrap_fragment(html, theme, title="t", index=index, total=8)
        assert layout == "parts" and "data-sonjari-parts" in wrapped and "--pz-bg" in wrapped
        # 템플릿 장 틀의 글 · 장식을 베끼지 않는다.
        if slides_style.is_template(theme):
            template_cover = slides_style.template_sections(theme)[0]["html"]
            assert template_cover not in wrapped


def test_each_theme_gets_its_own_decoration_drawn_by_code() -> None:
    """장식은 결 값(themes.json arrange · deco)으로 코드가 그린다 — 모델은 장식을 보지도 쓰지도 않는다."""
    decorated = {theme: slide_frames.style_of(theme) for theme in THEMES}
    assert decorated["cobalt-grid"] == ("side", ["stripes", "rules"])
    assert decorated["daisy-days"][1] == ["daisy"] and decorated["ir-brief"][0] == "panel"
    assert len({tuple(decos) for _, decos in decorated.values()}) >= 12  # 결마다 다른 무늬
    html = slide_parts.build_with_fixes(COVER, "cobalt-grid", 1, 4)[0]
    assert html.count('class="pz-deco"') == 3 and 'aria-hidden="true"' in html and "url(#pzs)" in html


def test_the_guide_no_longer_hands_over_any_template_html() -> None:
    """daisy 표지 틀은 장식 SVG 째 9,856자였다 — 모델이 그것을 베껴 표지 한 장에 약 8,000토큰을 냈다(10-26 결과.md)."""
    for theme in THEMES:
        payload = slides.guide_payload(theme)
        text = json.dumps(payload, ensure_ascii=False)
        assert "<section" not in payload["layouts"] and "<svg" not in text, theme
        assert "frames" in payload and "order" in payload and payload["deck_type"] in slide_frames.DECK_TYPES
    daisy = len(json.dumps(slides.guide_payload("daisy-days"), ensure_ascii=False))
    assert daisy < 12_000  # 예전 25,138자


@pytest.mark.parametrize("about, kind", [("시드 투자 IR 자료", "IR"), ("신입사원 온보딩 교육", "교육"), ("도입 제안서", "제안"),
                                         ("우리 회사 소개", "소개"), ("주간 업무 보고", "보고"), ("", "보고")])
def test_the_deck_type_comes_from_the_request_and_sets_the_flow(about: str, kind: str) -> None:
    assert slide_frames.deck_type(about) == kind
    payload = slides.guide_payload("paper", about=about)
    assert payload["deck_type"] == kind and payload["order"].startswith(kind) and "cover" in payload["order"]
    assert slide_frames.deck_type("주간 보고", "교육") == "교육"  # 사람이 정했으면 그것


def test_frame_shape_mistakes_with_one_answer_are_fixed_by_code() -> None:
    spec = {"head": "제목만 head 에", "label": "이 문장은 머리 말 칸에 넣기엔 너무 길어서 부제로 가야 한다", "meta": {"발표": "박가람", "날짜": "10.26"}}
    html, sig, _, fixed = slide_parts.build_with_fixes(spec, "paper", 1, 5)
    assert sig.startswith("frame:cover") and "제목만 head 에" in html and "fr-sub" in html
    assert any("head → title" in item for item in fixed) and any("부제로 옮겼다" in item for item in fixed)
    assert "<dt>발표</dt><dd>박가람</dd>" in html
    many = dict(COVER, meta=[[str(n), "값"] for n in range(6)])
    _, _, _, fixed = slide_parts.build_with_fixes(many, "paper", 1, 5)
    assert any("앞 4쌍" in item for item in fixed)
    # 자리를 보고 표지 · 마무리를 붙인다(frame 이름이 없을 때).
    assert slide_parts.build_with_fixes({"title": "다음 걸음"}, "paper", 5, 5)[1].startswith("frame:closing")


@pytest.mark.parametrize("change, problem", [({"title": ""}, "제목"), ({"title": "가" * 70}, "60자"),
                                             ({"sub": "가" * 200}, "160자"), ({"title": "○○ 소개"}, "자리 표시")])
def test_frame_problems_that_need_the_writer_are_sent_back(change: dict, problem: str) -> None:
    with pytest.raises(slide_parts.PartsError, match=problem):
        slide_parts.build_with_fixes(dict(COVER, **change), "paper", 1, 5)


def test_the_title_size_follows_its_length_and_the_arrangement_width() -> None:
    short, long = slide_frames.title_px("손자리", "left"), slide_frames.title_px("국내 AI 에이전트 관련 이번 주 소식을 한 번에 정리", "left")
    assert short > long and slide_frames.title_px("국내 AI 에이전트 최근 소식", "side") < slide_frames.title_px("국내 AI 에이전트 최근 소식", "left")


def test_a_template_cover_sent_as_html_is_sent_back_once_then_moved_into_parts(tmp_path: Path, monkeypatch) -> None:
    """실제 판 c81a10dd 표지와 같은 짜임 — 두 번째로 또 틀째 html 이 오면 받지 않고 글만 뽑아 표지 부품으로 옮긴다."""
    monkeypatch.setattr(slides, "fit_in_subprocess", lambda path, **_: {"overflow": 0, "base_px": 20})
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "cobalt-grid", "__job_id": "j"})
    raw = ('<section class="slide s-cover hairlines"><div class="titlewrap"><h1 class="title">국내 AI 에이전트<br/>최근 소식</h1>'
           '<div class="subkicker"><div class="l caption">국내 뉴스 브리핑 · 3건</div>'
           '<div class="ed">2026년 10월 26일 기준, 네이버 뉴스에서 확인한 국내 AI 에이전트 관련 최근 소식.</div></div></div>'
           '<div class="cfooter"><div class="colf"><div class="ftag caption">정리</div><div>로보메타핏 · 대표이사 보고용</div></div></div>'
           '<div class="pagenum">01 / 04</div></section>')
    with pytest.raises(ValueError, match="frame_required"):
        tools.make_slide({"title": "x", "index": 1, "total": 4, "theme": "cobalt-grid", "html": raw, "__job_id": "j"})
    out = tools.make_slide({"title": "x", "index": 1, "total": 4, "theme": "cobalt-grid", "html": raw, "__job_id": "j"})
    assert out["mode"] == "parts" and out["layout"] == "cover" and any("부품으로 옮겼다" in item for item in out["fixed"])
    saved = (tmp_path / "out/slides/j/x/slide_01.html").read_text(encoding="utf-8")
    body = saved.split("<body>", 1)[1]
    assert "pz-frame" in body and "s-cover" not in body and "국내 AI 에이전트 최근 소식" in body
    assert "<p class=\"fr-kicker\">국내 뉴스 브리핑 · 3건</p>" in body and "<dt>정리</dt><dd>로보메타핏 · 대표이사 보고용</dd>" in body
    assert "네이버 뉴스에서 확인한" in saved and 'class="fr-sub"' in saved


def test_overlap_that_code_cannot_untangle_is_sent_back_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(slides, "fit_in_subprocess",
                        lambda path, **_: {"overflow": 0, "base_px": 20, "overlap_before": 30, "overlap": 12, "overlap_where": "div.ed × div"})
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "paper", "__job_id": "j"})
    with pytest.raises(ValueError, match="slide_overlap: 1번 장의 글이 서로 12px"):
        tools.make_slide({"title": "x", "index": 1, "total": 2, "parts": COVER, "__job_id": "j"})
    again = tools.make_slide({"title": "x", "index": 1, "total": 2, "parts": COVER, "__job_id": "j"})
    assert again["saved"]


def test_overlap_untangled_by_code_is_reported_as_fixed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(slides, "fit_in_subprocess",
                        lambda path, **_: {"overflow": 0, "base_px": 20, "overlap_before": 11, "overlap": 0, "overlap_fixed": 7,
                                           "overlap_where": "div.ed × div"})
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "paper", "__job_id": "j"})
    out = tools.make_slide({"title": "x", "index": 1, "total": 2, "parts": COVER, "__job_id": "j"})
    assert any("11px 겹쳐" in item for item in out["fixed"])


def test_cover_preview_is_the_cover_that_will_actually_be_built() -> None:
    preview = slides_style.cover_preview("카페 3분기 보고", "코발트 연구지", "동네 카페 분기 매출", theme="cobalt-grid")
    built = slide_parts.build_with_fixes({"frame": "cover", "kicker": "코발트 연구지", "title": "카페 3분기 보고",
                                          "sub": "동네 카페 분기 매출"}, "cobalt-grid")[0]
    assert preview == built


@pytest.mark.skipif(not _HAS_CHROME, reason="브라우저 없음")
def test_real_fit_finds_and_untangles_overlapping_text(tmp_path: Path) -> None:
    """진짜 브라우저: 절대 위치 글 둘이 겹친 장(c81a10dd 표지 꼴) — 긴 쪽을 줄여 풀고, 파일에 그 크기를 남긴다."""
    page = tmp_path / "slide_01.html"
    page.write_text(
        '<!DOCTYPE html><html><head><meta charset="utf-8"><style data-sonjari-theme="x">/* sonjari-template */'
        "section{position:relative;width:1280px;height:720px;font-family:'Malgun Gothic'}"
        ".ed{position:absolute;left:72px;bottom:60px;width:900px;font-size:40px;line-height:1.2}"
        ".foot{position:absolute;left:72px;bottom:70px;font-size:14px}</style></head><body>"
        '<section class="slide"><div class="ed">2026년 10월 26일 기준, 네이버 뉴스에서 확인한 국내 AI 에이전트 관련 최근 소식.</div>'
        '<div class="foot">로보메타핏 · 대표이사 보고용</div></section></body></html>', encoding="utf-8")
    shape = slides.fit_slide(page)
    assert shape["overlap_before"] > 0 and shape["overlap_fixed"] >= 1
    assert "overlap" in shape and shape["overlap_where"]


@pytest.mark.skipif(not _HAS_CHROME, reason="브라우저 없음")
@pytest.mark.parametrize("theme", ["cobalt-grid", "daisy-days", "scatterbrain", "ir-brief", "editorial-tri-tone", "paper"])
def test_real_fit_frames_neither_overflow_nor_overlap(tmp_path: Path, theme: str) -> None:
    for kind, index in (("cover", 1), ("closing", 6)):
        spec = dict(COVER, frame=kind, figure={"label": "시험 기간", "value": "4주", "note": "한 부서 · 10명"})
        html = slide_parts.build_with_fixes(spec, theme, index, 6)[0]
        page = tmp_path / f"{theme}_{kind}.html"
        page.write_text(slides.clean_slide_html(slides_style.wrap_fragment(html, theme, title="t", index=index, total=6)[0]),
                        encoding="utf-8")
        shape = slides.fit_slide(page)
        assert shape["overflow"] == 0 and shape["overlap"] == 0, (theme, kind, shape)


def test_the_typo_check_reads_only_the_visible_words_not_the_css(tmp_path: Path, monkeypatch) -> None:
    """HEAD 부터 있던 버그(10-26 찾음): 장 html 에서 <style> 을 지우는 정규식에 백스페이스 글자(\x08)가 박혀 있어
    CSS 가 그대로 오타 표시에 들어갔다 — 결 CSS 주석의 「앉는다」를 자료의 「않는다」 오타로 표시했다."""
    monkeypatch.setattr(slides, "fit_in_subprocess", lambda path, **_: {"overflow": 0, "base_px": 20})
    tools = _tools(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr(tools, "_typo_check", lambda text, job_id: seen.append(text) or [])
    tools.make_slide({"title": "x", "index": 1, "total": 2, "theme": "paper", "parts": COVER, "__job_id": "j"})
    assert "국내 AI 에이전트 최근 소식" in seen[0] and "{" not in seen[0] and "var(--" not in seen[0]
    source = (Path(__file__).resolve().parents[1] / "src/alture_jarvis/local_computer.py").read_bytes()
    assert b"\x08" not in source


# ── 본문 무늬 한 점 (10-26 대표 14:20 「작게 하나만 · 글이 먼저」) ─────────────────────────────────────
BODY = {"head": "왜 지금", "lede": ["학원 412곳이 쓰고 있다"], "layout": "1",
        "cols": [[{"part": "stat", "label": "유료 학원", "value": "412", "unit": "곳"}]]}


def test_body_slides_get_one_small_mark_of_their_theme_except_ir_and_plain_themes() -> None:
    marked = {theme: slide_frames.body_mark(theme, 3) for theme in THEMES}
    assert 'class="pz-deco pz-mark"' in marked["cobalt-grid"] and "url(#pzm)" in marked["cobalt-grid"]
    assert "ellipse" in marked["daisy-days"] and "03" in marked["grove"]
    assert marked["ir-brief"] == "" and marked["paper"] == "" and marked["broadside"] == ""  # IR 은 자기 디자인 · 면 띠 · 무늬 없음
    assert all(item.count('class="pz-deco pz-mark"') == 1 for item in marked.values() if item)  # 한 점만
    html = slide_parts.build_with_fixes(BODY, "daisy-days", 2, 5)[0]
    body = slides_style.wrap_fragment(html, "daisy-days", title="t", index=2, total=5)[0]
    assert body.count('class="pz-deco pz-mark"') == 1 and "data-optional" in body
    cover = slides_style.wrap_fragment(slide_parts.build_with_fixes(COVER, "daisy-days", 1, 5)[0], "daisy-days", index=1, total=5)[0]
    assert "pz-mark" not in cover.split("<body>", 1)[1]  # 표지 · 마무리는 자기 장식이 따로 있다


@pytest.mark.skipif(not _HAS_CHROME, reason="브라우저 없음")
def test_real_fit_keeps_the_mark_when_clear_and_drops_it_when_text_reaches_the_corner(tmp_path: Path) -> None:
    """글이 먼저 — 무늬 자리에 글이 닿으면 글을 줄이지 않고 무늬를 지운다. 양쪽을 다 본다."""
    for head, kept in (("왜 지금", True), ("학원 원장님이 매주 여섯 시간을 돌려받는 학부모 알림 자동화 — 지금 시작해야 하는 까닭 셋과 근거", False)):
        spec = dict(BODY, head=head)
        html = slide_parts.build_with_fixes(spec, "cobalt-grid", 2, 5)[0]
        page = tmp_path / f"{kept}.html"
        page.write_text(slides.clean_slide_html(slides_style.wrap_fragment(html, "cobalt-grid", title="t", index=2, total=5)[0]),
                        encoding="utf-8")
        shape = slides.fit_slide(page)
        saved = page.read_text(encoding="utf-8").split("<body", 1)[1]
        assert shape["deco_kept"] == int(kept) and shape["deco_dropped"] == int(not kept), (head, shape)
        assert ('class="pz-deco pz-mark"' in saved) == kept
        assert shape["overflow"] == 0 and shape["overlap"] == 0


# ── 칸 영역 밑으로 넘침 (10-26 16:09 실제 판 5c0a3d8d 4번 장) ─────────────────────────────────────────
_QUOTE = "로봇·피지컬AI의 '기억' 기술이 성숙 — 우리 로봇 사업과 접점을 볼 가치가 있다."
ETRI = {"head": "소식 3 · ETRI·GIST", "sub": "환경을 기억했다 필요한 순간 꺼내 쓰는 로봇 AI",
        "lede": ["필요한 정보만 찾아 쓰는 로봇 AI '씬쿼리플래너' 개발", "가정·서비스 로봇 활용 기대 — <u>추측이 아닌 확인된 정보로 행동</u>"],
        "layout": "2:1", "source": "동아사이언스 2026.10.26 · 문혜원 기자",
        "cols": [[{"part": "text", "title": "핵심 3줄", "items": ["환경을 3D 장면 그래프로 기억, 필요한 정보만 스스로 조회",
                                                              "공개 모델에서 임무 성공률 20%p 이상 향상 (LLaMA 3.1: 46.8→69.6%)",
                                                              "EMNLP 2026 파인딩스에 25일 발표, 코드·벤치마크 공개"]}],
                 [{"part": "kv", "title": "출처", "items": [["매체", "동아사이언스"], ["날짜", "2026.10.26"], ["주소", "dongascience.com/news/80533"]]},
                  {"part": "text", "title": "시사점", "quote": _QUOTE}]]}


def _fit_page(tmp_path: Path, spec: dict, name: str) -> tuple[dict, str]:
    html = slide_parts.build_with_fixes(spec, "cobalt-grid", 4, 5)[0]
    page = tmp_path / f"{name}.html"
    page.write_text(slides.clean_slide_html(slides_style.wrap_fragment(html, "cobalt-grid", title="t", index=4, total=5)[0]), encoding="utf-8")
    return slides.fit_slide(page), page.read_text(encoding="utf-8")


def _grid_overrun(html: str) -> float:
    """저장된 장을 다시 그려 칸 영역 바닥 밑으로 내려간 글의 깊이(px)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = slides._launch(pw)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(html)
            slides._settle(page)
            return page.evaluate("""() => { const g = document.querySelector('.pz-grid').getBoundingClientRect();
              return Math.max(0, ...Array.from(document.querySelectorAll('.pz-grid *')).filter((e) => Array.from(e.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim()))
                .map((e) => e.getBoundingClientRect().bottom - g.bottom)); }""")
        finally:
            browser.close()


@pytest.mark.skipif(not _HAS_CHROME, reason="브라우저 없음")
def test_growing_type_stops_before_a_column_runs_below_the_grid(tmp_path: Path) -> None:
    """키우기가 오른쪽 칸 「시사점」을 1.5배로 키워 바닥 가로선 · 출처 줄까지 내려갔다 — 칸 영역 바닥도 넘침으로 잰다."""
    shape, saved = _fit_page(tmp_path, ETRI, "etri")
    assert shape["overflow"] == 0 and shape["grown"] < 7
    assert _grid_overrun(saved) <= 2


@pytest.mark.skipif(not _HAS_CHROME, reason="브라우저 없음")
def test_a_column_too_long_from_the_start_is_shrunk_by_code_not_sent_back(tmp_path: Path) -> None:
    """모델이 처음부터 칸에 비해 긴 큰 글을 넣었다 — 그 칸의 글만 큰 것부터 줄여 칸 안에 넣는다(사다리 0단)."""
    long = dict(ETRI, cols=[ETRI["cols"][0], [*ETRI["cols"][1][:1], {"part": "text", "title": "시사점", "quote": _QUOTE * 3},
                                              {"part": "stat", "label": "성공률", "value": "69.6", "unit": "%"}]])
    shape, saved = _fit_page(tmp_path, long, "long")
    assert shape["overflow_before"] > 0 and shape["column_shrunk"] >= 1 and shape["overflow"] == 0, shape
    assert _grid_overrun(saved) <= 2
    head = saved.split('class="ir-head"', 1)[1][:80]
    assert "font-size" not in head  # 장 제목은 건드리지 않는다
