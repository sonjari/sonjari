"""사다리 0~1단(`fix`) — 정답이 하나로 정해지는 모양 잘못은 돌려보내지 않고 코드가 고친다 (2026-10-26 최소 개입 설계 ①②).

지난 장표 22판의 돌려보내기 42번 중 11번이 이것이었다(조립표 칸 목록 모양 4 · 칸 수 2 · 「1:1:1:1」 1 · 이야기판 틀 이름 4).
"""

import json
from pathlib import Path

from alture_jarvis import slide_parts
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

STAT = {"part": "stat", "label": "월 인건비", "value": "120", "unit": "만 원"}
TEXT = {"part": "text", "title": "왜", "items": ["근거 한 줄"]}


def test_head_keys_spilled_into_cols_are_restored() -> None:
    """실제 판 d4df8a28 의 모양 — 괄호를 하나 잘못 닫아 머리 칸이 칸 목록 안으로 들어갔다."""
    spec = {"lede": ["첫 줄", "둘째 줄"],
            "cols": [[STAT], [TEXT], "head", "경쟁", "layout", "1", "source", "에듀콜 · 2026.9.30", "sub", "가격과 이익"]}
    html, _, names, fixed = slide_parts.build_with_fixes(spec)
    assert names == ["stat", "text"] and "경쟁" in html and "가격과 이익" in html and "에듀콜" in html
    assert any("머리 칸" in note for note in fixed)
    assert any("칸 나눔" in note for note in fixed)  # 「1」에 칸이 둘 — 같은 너비로 고쳤다


def test_junk_strings_in_cols_are_dropped_and_reported() -> None:
    """실제 판 e5844c85 의 모양 — 「head}: 」 · 「source**: 」 같은 조각."""
    spec = {"head": "비용", "cols": [[STAT], "source", "head}: ", "source**: "]}
    _, _, _, fixed = slide_parts.build_with_fixes(spec)
    assert fixed and "조각 글 3개를 뺐다" in fixed[0]


def test_a_flat_cols_list_is_wrapped() -> None:
    _, _, names, fixed = slide_parts.build_with_fixes({"head": "x", "cols": [STAT, TEXT]})
    assert names == ["stat", "text"] and "감쌌다" in fixed[0]


def test_a_clean_sheet_reports_nothing() -> None:
    _, _, _, fixed = slide_parts.build_with_fixes({"head": "x", "layout": "1:1", "cols": [[STAT], [TEXT]]})
    assert fixed == []


def test_a_missing_head_is_still_sent_back() -> None:
    """고칠 정답이 없는 것(머리 칸이 아예 없음)은 예전처럼 돌려보낸다 — 지어내지 않는다."""
    try:
        slide_parts.build_with_fixes({"cols": [[STAT]]})
    except slide_parts.PartsError as exc:
        assert "head" in str(exc)
    else:
        raise AssertionError("머리 칸 없는 조립표가 통과했다")


def _tools(tmp_path: Path) -> LocalComputerTools:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=str(tmp_path / "docs"))
    tools = LocalComputerTools(config)
    tools.publish = lambda event, payload: None
    return tools


def test_unknown_outline_names_become_parts_slides_with_a_note(tmp_path: Path) -> None:
    """이야기판의 「1:2」 · 「points 3」 · 「slide--points」 — 부품 결에서는 부품 장으로 받고 바꾼 것을 알린다."""
    tools = _tools(tmp_path)
    tools.make_slide({"title": "x", "theme": "grove", "__job_id": "j"})
    out = tools.make_slide({"title": "x", "__job_id": "j", "outline": [
        {"layout": "slide--cover", "claim": "표지"}, {"layout": "1:2", "claim": "숫자"},
        {"layout": "points 3", "claim": "요점"}, {"layout": "slide--points", "claim": "지어낸 틀"},
        {"layout": "slide--end", "claim": "마무리"}]})
    # 10-26: 부품 결의 장 이름은 cover · parts · closing 셋 — 그 결의 첫 · 마지막 틀 이름은 표지 · 마무리로 옮긴다.
    assert [card["layout"] for card in out["outline"]] == ["cover", "parts", "parts", "parts", "closing"]
    assert "slide--points → parts" in out["fixed"][0]


def test_a_lede_list_and_an_unwrapped_text_card_are_revived() -> None:
    """실제 판 d4df8a28 6번 장 — lede 문장 목록이 칸으로, 글 부품은 껍데기 없이 들어왔다. 내용을 잃지 않고 되살린다."""
    table = {"part": "table", "columns": ["회사", "고객"], "rows": [["A", "1"], ["우리", "2"]]}
    spec = {"cols": [[table], ["items", "우리 고객 412곳 = 6,000곳의 7%"], "head", "경쟁", "layout", "1", "lede",
                     ["같은 시장에서 1/7 가격", "학원로그는 영업손실"], "source", "에듀콜 · 2026.9.30", "sub", "가격과 이익"]}
    html, _, names, fixed = slide_parts.build_with_fixes(spec)
    assert names == ["table", "text"] and "412곳" in html and "1/7 가격" in html and "가격과 이익" in html
    assert "글 부품으로 되살렸다" in fixed[0] and "lede" in fixed[0]


def test_slides_with_their_own_heading_as_title_land_in_one_deck(tmp_path: Path, monkeypatch) -> None:
    """10-26 소개 PPT 판 6ddef60f — 장마다 title 에 그 장의 제목을 넣어 장 8개가 장표 8개로 흩어졌다. 한 판의 장표는 한 폴더로."""
    from alture_jarvis import slides

    monkeypatch.setattr(slides, "fit_in_subprocess", lambda path, **_: {"overflow": 0, "base_px": 20})
    monkeypatch.setattr(slides, "render_in_subprocess", lambda deck, out: {"slides": 3})
    tools = _tools(tmp_path)
    tools.make_slide({"title": "손자리 소개", "theme": "paper", "__job_id": "j"})
    tools.make_slide({"title": "손자리 소개", "__job_id": "j", "outline": [
        {"layout": "cover", "claim": "표지"}, {"layout": "parts", "claim": "본문"}, {"layout": "closing", "claim": "끝"}]})
    first = tools.make_slide({"title": "손자리 — 내 PC 의 AI", "index": 1, "total": 3, "__job_id": "j",
                              "parts": {"frame": "cover", "title": "손자리", "sub": "내 PC 에서"}})
    assert first["title"] == "손자리 소개" and "이 판의 장표" in first["fixed"][0]
    second = tools.make_slide({"title": "왜 필요한가", "index": 2, "total": 3, "__job_id": "j",
                               "parts": {"head": "왜", "cols": [[STAT]]}})
    assert second["title"] == "손자리 소개" and second["slides_ready"] == 2
    decks = [d.name for d in (tmp_path / "out/slides/j").iterdir()]
    assert decks == ["손자리 소개"]


def test_kv_items_sent_as_wrapped_objects_become_pairs() -> None:
    """10-26 소개 판 be78277a 3 · 7번 장 — kv 가 [[{title, text}, …]] 로 와 장에 「{'text': …}」 코드 글자가 찍혔다."""
    kv = {"part": "kv", "items": [[{"title": "설치", "text": "스토어에서 설치"}, {"title": "공개", "text": "Apache-2.0"}]]}
    html, _, _, fixed = slide_parts.build_with_fixes({"head": "설치와 공개", "cols": [[kv]]})
    assert "<dt>설치</dt><dd>스토어에서 설치</dd>" in html and "<dt>공개</dt>" in html
    assert "{'" not in html and '{"' not in html and any("짝으로 폈다" in note for note in fixed)


def test_no_part_ever_prints_a_raw_object() -> None:
    """바닥 장치: 어느 부품의 글 칸에 객체 · 목록이 와도 코드 글자를 찍지 않는다."""
    odd = {"part": "steps", "items": [{"title": {"title": "속도", "text": "견적 3일"}}, {"title": ["사례", "매달 2건"]}]}
    html, _, _, _ = slide_parts.build_with_fixes({"head": "내년", "cols": [[odd]]})
    assert "{'" not in html and "['" not in html and "속도 — 견적 3일" in html and "사례 · 매달 2건" in html
