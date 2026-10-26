"""IR 브리프 결 (2026-10-25 대표: 「IR 은 PPT 로 붙어야」) — 우리가 쓴 템플릿 · 장 이름 · 추천 · 장 순서 · 자리 표시 돌려보내기."""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis import slides, slides_style
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.slide_catalog import recommend

IR_IDS = ["ir-cover", "ir-questions", "ir-model", "ir-traction", "ir-market", "ir-competition", "ir-unit", "ir-edge",
          "ir-roadmap", "ir-pnl", "ir-team", "ir-summary", "ir-closing"]


@pytest.fixture(autouse=True)
def _no_browser_fit(monkeypatch):
    monkeypatch.setattr(slides, "fit_in_subprocess", lambda path, **_: {"overflow": 0, "base_px": 20})


def test_the_ir_template_ships_from_its_own_folder_with_thirteen_named_slides() -> None:
    meta = slides_style.TEMPLATES["ir-brief"]
    assert meta["own"] and "own" in meta["_dir"] and meta["flow"].startswith("IR 장 순서")
    assert slides_style.template_layout_ids("ir-brief") == IR_IDS
    _, css = slides_style.theme_css("ir-brief")
    assert css.startswith("/* sonjari-template */") and "fonts.googleapis" not in css and "<script" not in css


def test_ported_templates_get_one_name_per_slide_not_slide_for_all() -> None:
    """옮긴 템플릿은 첫 클래스가 전부 `slide` 라 이야기판 카드가 모두 「slide」였다 — 장을 가르는 클래스를 이름으로 쓴다."""
    assert slides_style.template_layout_ids("emerald-editorial") == [f"s{i}" for i in range(1, 9)]
    assert slides_style.template_layout_ids("mat")[0] == "slide--cover" and "light" not in slides_style.template_layout_ids("mat")
    assert "### s2 — " in slides_style.layout_menu("emerald-editorial")
    layout, _ = slides_style.section_layout('<section class="slide dark slide--stats"><h2>x</h2></section>', "mat")
    assert layout == "slide--stats"


def test_ir_words_put_the_ir_theme_first_and_hand_over_the_order() -> None:
    for ask in ("시드 투자 유치 IR 장표", "피치덱 만들어줘", "예비창업패키지 발표평가 자료"):
        assert recommend(ask)[0]["theme"] == "ir-brief", ask
    assert recommend("동네 카페 분기 매출 보고")[0]["theme"] != "ir-brief"
    payload = slides.guide_payload(None, about="시드 투자 IR")
    assert payload["theme"] == "ir-brief" and "points" in payload["order"]
    # 부품 결: 틀(html)은 하나도 주지 않는다 — 표지 · 마무리도 frames 조립표(10-26). IR 흐름은 결에 정해진 order 가 먼저다.
    assert "### ir-cover" not in payload["layouts"] and "frame" in payload["frames"] and "cover 부품" in payload["order"]
    assert "bars" in payload["parts"] and "조립" in payload["assembly"]


def test_a_slide_with_korean_placeholders_left_is_sent_back_once(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=str(tmp_path / "docs"))
    tools = LocalComputerTools(config)
    tools.make_slide({"title": "x", "theme": "ir-brief", "__job_id": "j"})
    # 10-26 부터 표지는 부품이다 — 자리 표시(「○○억」)가 남은 표지 조립표는 돌려보낸다.
    with pytest.raises(ValueError, match="자리 표시"):
        tools.make_slide({"title": "x", "index": 1, "total": 3, "theme": "ir-brief", "__job_id": "j",
                          "parts": {"frame": "cover", "title": "학원 알림 자동화", "figure": {"label": "요청", "value": "○○억"}}})
    out = tools.make_slide({"title": "x", "index": 1, "total": 3, "theme": "ir-brief", "__job_id": "j",
                            "parts": {"frame": "cover", "title": "학원 알림 자동화", "figure": {"label": "요청", "value": "12억"}}})
    assert out["saved"] and out["layout"] == "cover" and out["mode"] == "parts"
    # 틀째 표지 html 은 한 번 돌려보낸다(frame_required).
    raw = slides_style.template_sections("ir-brief")[0]["html"]
    with pytest.raises(ValueError, match="frame_required"):
        tools.make_slide({"title": "x", "index": 3, "total": 3, "theme": "ir-brief", "html": raw, "__job_id": "j"})
