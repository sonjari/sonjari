"""장표 부품 조립 (2026-10-25 대표: 템플릿을 부품으로 증류 · 모델은 골라 배치) — 검사 · 그리기 · 장표 도구 연결 · 기록."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from alture_jarvis import slide_parts, slides, slides_style
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

SAMPLE = json.loads((Path(__file__).with_name("fixtures_ir_parts_sample.json")).read_text(encoding="utf-8"))
UNIT = next(spec for spec in SAMPLE if spec.get("sub") == "수요와 수익 요인")


@pytest.fixture(autouse=True)
def _no_browser_fit(monkeypatch):
    monkeypatch.setattr(slides, "fit_in_subprocess", lambda path, **_: {"overflow": 0, "base_px": 20})


def _tools(tmp_path: Path) -> LocalComputerTools:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=str(tmp_path / "docs"))
    tools = LocalComputerTools(config)
    tools.publish = lambda event, payload: None
    return tools


def _cover() -> str:
    cover = slides_style.template_sections("ir-brief")[0]["html"].replace("○○억", "12억")
    for left in sorted(slides_style.template_texts("ir-brief"), key=len, reverse=True):
        cover = cover.replace(left, "클래스노트")
    return cover


def test_every_sample_slide_builds_and_names_its_shape() -> None:
    sigs = []
    for spec in SAMPLE:
        html, sig, used = slide_parts.build(spec)
        assert html.startswith('<section class="slide ir-parts pz-slide">') and used and sig.startswith("parts:")
        sigs.append(sig)
    assert len(set(sigs)) >= 9  # 장마다 짜임이 다르다


def test_bars_are_drawn_to_one_scale_by_code_not_by_the_model() -> None:
    html, _, _ = slide_parts.build(UNIT)
    heights = [float(h) for h in re.findall(r"--h:([\d.]+)%", html)]
    assert heights[0] == 100.0 and abs(heights[2] - 9.9 / 120 * 100) < 0.1


@pytest.mark.parametrize("change, problem", [
    (lambda s: s["cols"][0].append({"part": "chart3d"}), "없음"),
    (lambda s: s["cols"][0][0]["items"].append({"name": "x", "value": "많음"}), "숫자만"),
    (lambda s: s["cols"][1].append({"part": "stat", "role": "anchor", "value": "1"}), "anchor"),
    (lambda s: s["cols"][1][0].update(value="○○%"), "자리 표시"),
    (lambda s: s.update(lede=["이 장은 숫자를 보여 준다", "둘째 줄"]), "연출 지시"),
    (lambda s: s.update(layout="4:4"), None),  # 모르는 칸 나눔은 같은 너비로 고쳐 받는다(10-25 밤 grove 판이 「1:1:1:1」 거절에 판을 접었다)
    (lambda s: s["cols"][1].pop(), None),  # 칸에서 하나 빼는 것은 문제없다
])
def test_bad_assembly_sheets_are_sent_back_with_every_reason(change, problem) -> None:
    spec = json.loads(json.dumps(UNIT))
    change(spec)
    if problem is None:
        slide_parts.build(spec)
        return
    with pytest.raises(slide_parts.PartsError, match=problem):
        slide_parts.build(spec)


def test_text_is_escaped_but_underline_bold_and_mark_survive() -> None:
    spec = {"head": "x <script>alert(1)</script>", "lede": ["<u>핵심</u> 과 <mark>형광</mark>"], "layout": "1",
            "cols": [[{"part": "text", "text": "<b>굵게</b> <img src=x onerror=1>"}]]}
    html, _, _ = slide_parts.build(spec)
    assert "<script>" not in html and "<img" not in html and "<u>핵심</u>" in html and "<b>굵게</b>" in html


def test_the_slide_tool_assembles_parts_and_records_the_mode(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "ir-brief", "__job_id": "j"})
    out = tools.make_slide({"title": "x", "index": 2, "total": 3, "theme": "ir-brief", "parts": UNIT, "__job_id": "j"})
    assert out["saved"] and out["layout"] == "parts" and out["mode"] == "parts"
    record = json.loads((tmp_path / "out/slides/j/x/layouts.json").read_text(encoding="utf-8"))
    assert record["2"]["mode"] == "parts" and record["2"]["parts"] == ["bars", "panel", "text"]
    saved = (tmp_path / "out/slides/j/x/slide_02.html").read_text(encoding="utf-8")
    assert 'data-sonjari-theme="ir-brief"' in saved and "pz-bar" in saved
    # 조립표를 JSON 글로 줘도 받는다.
    again = tools.make_slide({"title": "x", "index": 2, "total": 3, "theme": "ir-brief",
                              "parts": json.dumps(UNIT, ensure_ascii=False), "__job_id": "j"})
    assert again["mode"] == "parts"


def test_copying_a_body_template_is_sent_back_once_toward_parts(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "ir-brief", "__job_id": "j"})
    body = ('<section class="slide ir-questions"><h2 class="ir-head">들어가며 <small>_ 질문</small></h2>'
            '<p class="ir-lede">학원이 돈을 낼지 묻습니다.<br>답은 <u>매주 6시간</u>입니다.</p></section>')
    with pytest.raises(ValueError, match="parts_required"):
        tools.make_slide({"title": "x", "index": 2, "total": 3, "theme": "ir-brief", "html": body, "__job_id": "j"})
    out = tools.make_slide({"title": "x", "index": 2, "total": 3, "theme": "ir-brief", "html": body, "__job_id": "j"})
    # 두 번째도 틀째로는 받지 않는다(10-26) — 고리가 되지 않게 받되, 글만 뽑아 부품으로 옮기고 그 사실을 알린다.
    assert out["saved"] and out["mode"] == "parts" and any("부품으로 옮겼다" in item for item in out["fixed"])
    saved = (tmp_path / "out/slides/j/x/slide_02.html").read_text(encoding="utf-8")
    assert "pz-slide" in saved and "매주 6시간" in saved


def test_every_theme_now_takes_parts_even_our_own(tmp_path: Path) -> None:
    """10-25 저녁: 결 24개 모두 부품을 받는다(묶음 넷). 예전에는 IR 밖 결이 parts_not_supported 로 거절됐다."""
    tools = _tools(tmp_path)
    out = tools.make_slide({"title": "x", "index": 2, "total": 3, "theme": "paper", "parts": UNIT, "__job_id": "j"})
    assert out["saved"] and out["mode"] == "parts"
    saved = (tmp_path / "out/slides/j/x/slide_02.html").read_text(encoding="utf-8")
    assert "data-sonjari-parts" in saved and "pz-bar" in saved


def test_the_baked_deck_reports_how_many_slides_were_assembled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(slides, "render_in_subprocess", lambda deck, out: {"slides": 2})
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "ir-brief", "__job_id": "j"})
    tools.make_slide({"title": "x", "index": 1, "total": 2, "theme": "ir-brief", "__job_id": "j",
                      "parts": {"frame": "cover", "kicker": "클래스노트", "title": "학원 알림 자동화", "figure": {"label": "요청", "value": "12억 원"}}})
    done = tools.make_slide({"title": "x", "index": 2, "total": 2, "theme": "ir-brief", "parts": UNIT, "__job_id": "j"})
    assert done["assembly"] == {"parts": 2, "template": 0}  # 표지도 부품이다(10-26)


def test_the_outline_for_a_parts_theme_takes_parts_cards(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "ir-brief", "__job_id": "j"})
    out = tools.make_slide({"title": "x", "__job_id": "j", "outline": [
        {"layout": "ir-cover", "claim": "학원 알림 자동화"}, {"layout": "parts", "claim": "한 곳에서 5.6만 원"},
        {"layout": "ir-closing", "claim": "12억으로 6,000곳"}]})
    assert out["total"] == 3


# ── 계산 검사 (10-25 실제 판 fde0be39: 맞는 511억을 모델이 「10배 오타」라며 5,108억으로 고쳤다) ──────────
@pytest.mark.parametrize("text, wrong", [
    ("4.3만 곳 × 월 9.9만 × 12 = 연 5,108억", True),
    ("4.3만 곳 × 월 9.9만 × 12 = 연 511억", False),
    ("6,000곳 × 9.9만 원 × 12 = 71.3억", False),
    ("연 시장 대비 1.39% (71.3 ÷ 511)", True),
    ("연 시장 대비 13.9% (71.3 ÷ 511)", False),
    ("MRR 4,079만(412×9.9)", False),
    ("이익률 27% (5.6 ÷ 9.9)", True),
    ("7.4곳 (412 × 1.8%)", False),
    ("1% 미만 (412 ÷ 43,000)", False),  # 실제 판 d4df8a28 헛걸림(옛 판정) — 「미만」은 식의 값이 아니다
    ("약 1%(412 ÷ 43,000)", False),     # 적힌 자릿수만큼 봐준다(1% 는 ±0.5)
    ("5%(412 ÷ 43,000)", True),
    ("21,000곳 × 72.2만 = 182억", True),  # 실제 판 d4df8a28 진짜(151.6억)
    ("월 이익 5.6만 × 60개월 = 3,360만 원", True),
    ("시간제 120만 원의 1/12 · 2026.9.30 기준 · 010-1234-5678 · 기준(2026.9) · 50~300명", False),
])
def test_the_arithmetic_on_a_slide_is_checked_both_ways(text, wrong) -> None:
    assert bool(slide_parts.arithmetic_problems([text])) is wrong


def test_a_slide_with_wrong_arithmetic_is_sent_back_once(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "ir-brief", "__job_id": "j"})
    bad = json.loads(json.dumps(UNIT))
    bad["cols"][1][0]["text"] = "4.3만 곳 × 9.9만 원 × 12 = 5,108억"
    with pytest.raises(ValueError, match="slide_math.*510.8억"):
        tools.make_slide({"title": "x", "index": 2, "total": 3, "theme": "ir-brief", "parts": bad, "__job_id": "j"})
    out = tools.make_slide({"title": "x", "index": 2, "total": 3, "theme": "ir-brief", "parts": bad, "__job_id": "j"})
    assert out["saved"]  # 검사가 틀릴 수도 있어 두 번째는 받는다


def test_a_sparse_parts_slide_is_only_marked_not_sent_back(tmp_path: Path, monkeypatch) -> None:
    """글자를 키워도 부품 칸이 40% 넘게 비면 — 10-25 엔 한 번 돌려보냈고, 10-26(대표 14:20)부터 표시만 한다(사다리 3단).
    다시 시켜 고쳐지는 비율이 39%(아침 재기) · 실제 판 돌려보내기 10번 중 8번이 이것이었다. 굽기 결과의 검사 요약에 남는다."""
    monkeypatch.setattr(slides, "fit_in_subprocess", lambda path, **_: {"overflow": 0, "base_px": 20, "empty": 0.61, "grown": 7})
    monkeypatch.setattr(slides, "render_in_subprocess", lambda deck, out: {"slides": 3})
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "ir-brief", "__job_id": "j"})
    out = tools.make_slide({"title": "x", "index": 2, "total": 3, "theme": "ir-brief", "parts": UNIT, "__job_id": "j"})
    assert out["saved"] and "61%" in out["sparse_check"] and "표시만" in out["sparse_check"]
    for index in (1, 3):
        done = tools.make_slide({"title": "x", "index": index, "total": 3, "theme": "ir-brief", "parts": UNIT, "__job_id": "j"})
    assert done["check_summary"] == "비어 보이는 장 3(1 · 2 · 3번)" and done["sparse_slides"] == [1, 2, 3]


def test_real_fit_grows_type_on_an_empty_parts_slide(tmp_path: Path, monkeypatch) -> None:
    """실제 브라우저로 잰다 — 숫자 하나뿐인 장은 글자가 커지고, 넘치지는 않는다."""
    monkeypatch.undo()
    spec = {"head": "견인", "lede": ["유료 학원 412곳", "월 반복 매출 <u>4,079만 원</u>"], "layout": "1",
            "cols": [[{"part": "stat", "label": "유료 학원", "value": "412", "unit": "곳"}]]}
    html, _, _ = slide_parts.build(spec)
    page, _ = slides_style.wrap_fragment(html, "ir-brief")
    path = tmp_path / "s.html"
    path.write_text(page, encoding="utf-8")
    shape = slides.fit_slide(path)
    assert shape["grown"] > 0 and shape["overflow"] == 0 and shape["empty"] > 0.4


# ── 사진 넣기 (10-25 대표 「사진은 사용자가 실시간으로 넣을 수 있게」) ──────────────────────────
def _png_data_url() -> str:
    import base64
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


PHOTO_SPEC = {"head": "매장", "lede": ["광주 본점", "첫 매장 <u>2026년 9월</u>"], "layout": "1:1",
              "cols": [[{"part": "photo", "label": "매장 \"전경\"", "caption": "광주 본점", "ratio": "4:3"}],
                       [{"part": "metrics", "items": [{"label": "학원", "value": "412", "unit": "곳", "evidence": "관리자 화면"}]}]]}


def test_photo_slots_are_named_and_a_picture_replaces_the_placeholder() -> None:
    html, _, used = slide_parts.build(PHOTO_SPEC)
    assert "photo" in used
    slots = slide_parts.slots_of(html)
    assert [s["id"] for s in slots] == ["s1", "s2"] and slots[0]["label"] == '매장 "전경"' and not slots[0]["filled"]
    filled = slide_parts.put_photo(html, "s1", "data:image/jpeg;base64,AAAA", alt="매장")
    after = slide_parts.slots_of(filled)
    assert after[0]["filled"] and not after[1]["filled"] and "has-photo" in filled
    with pytest.raises(slide_parts.PartsError):
        slide_parts.put_photo(html, "s9", "data:image/jpeg;base64,AAAA")


def test_a_dropped_photo_is_stored_shrunk_and_the_baked_deck_is_rebaked(tmp_path: Path, monkeypatch) -> None:
    baked: list = []
    monkeypatch.setattr(slides, "render_in_subprocess", lambda deck, out: baked.append(out) or {"slides": 1})
    tools = _tools(tmp_path)
    sent: list = []
    tools.publish = lambda event, payload: sent.append((event, payload))
    tools.make_slide({"title": "x", "theme": "ir-brief", "__job_id": "j"})
    done = tools.make_slide({"title": "x", "index": 1, "total": 1, "theme": "ir-brief", "parts": PHOTO_SPEC, "__job_id": "j"})
    assert done.get("path") and len(baked) == 1
    slide_event = next(payload for event, payload in sent if event == "deck_slide")
    assert [s["id"] for s in slide_event["slots"]] == ["s1", "s2"]
    out = tools.deck_put_photo("j", "x", 1, "s1", _png_data_url())
    saved = (tmp_path / "out/slides/j/x/slide_01.html").read_text(encoding="utf-8")
    assert out["ok"] and "<img src=\"data:image/jpeg;base64," in saved and (tmp_path / "out/slides/j/x/assets/slide01_s1.jpg").exists()
    assert out["rebaked"].endswith("x (사진).pptx") and len(baked) == 2
    assert sent[-1][0] == "deck_built" and any(e == "deck_slide" and p.get("photo") for e, p in sent)
    record = json.loads((tmp_path / "out/slides/j/x/built.json").read_text(encoding="utf-8"))
    assert len(record["paths"]) == 2
    with pytest.raises(ValueError, match="photo_not_image"):
        tools.deck_put_photo("j", "x", 1, "s2", "data:text/html;base64,PGI+")
