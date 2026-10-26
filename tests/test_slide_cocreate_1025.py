"""장표 같이 만들기 — 결 고르기 · 이야기판 · 한마디 · 멈춤 (2026-10-25 대표 2차 시안 · `slide_inbox`)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from alture_jarvis import slide_inbox, slides
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.slide_inbox import DeckInbox

COVER = """<section class="cover"><p class="kicker">처음 쓰는 분께</p><h1>내 PC에서 일하는 AI</h1>
<p class="lede">본문은 이 PC에서 읽는다.</p></section>"""
BIG = """<section class="bignum"><p class="kicker">첫 걸음</p><h2>첫 걸음이 빨라졌다</h2>
<div class="hero"><p class="was">30.6초</p><p class="num">1.08<small>초</small></p><p class="desc">한 판 기준.</p></div></section>"""
#: 10-26 부터 모든 결이 표지까지 부품 — 같은 내용을 조립표로.
COVER_PARTS = {"frame": "cover", "kicker": "처음 쓰는 분께", "title": "내 PC에서 일하는 AI", "sub": "본문은 이 PC에서 읽는다."}
BIG_PARTS = {"head": "첫 걸음", "lede": ["첫 걸음이 빨라졌다"],
             "cols": [[{"part": "stat", "label": "한 판 기준", "value": "1.08", "unit": "초", "note": "전에는 30.6초"}]]}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(slides, "fit_in_subprocess", lambda path, **_: {"overflow": 0, "base_px": 20})
    monkeypatch.setattr(slide_inbox, "THEME_WAIT", 1.5)
    monkeypatch.setattr(slide_inbox, "OUTLINE_WAIT", 1.5)


def _tools(tmp_path: Path, origin: str = "workspace", status: str = "running") -> tuple[LocalComputerTools, list]:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=str(tmp_path / "docs"))
    tools = LocalComputerTools(config)
    sent: list = []
    tools.publish = lambda event, payload: sent.append((event, payload))
    state = {"status": status}
    tools.job_info = lambda job_id: {"status": state["status"], "payload": {"origin": origin}}
    tools._state = state  # 시험에서 판 상태를 바꾸려고
    return tools, sent


def _later(seconds: float, fn) -> threading.Thread:
    def run() -> None:
        time.sleep(seconds)
        fn()
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


# ── 받은 편지함 ──────────────────────────────────────────────────────────────
def test_inbox_returns_the_answer_posted_while_waiting_and_none_on_timeout() -> None:
    inbox = DeckInbox()
    _later(0.2, lambda: inbox.post("j", "t", "theme", "ink"))
    assert inbox.wait("j", "t", "theme", 3.0) == "ink"
    started = time.monotonic()
    assert inbox.wait("j", "t", "theme", 0.3) is None
    assert time.monotonic() - started < 1.5


def test_touching_extends_the_wait_but_not_forever(monkeypatch) -> None:
    """사람이 이야기판을 만지는 중이면 기다림이 늘어난다 — 상한(HARD_CAP)은 지킨다."""
    monkeypatch.setattr(slide_inbox, "TOUCH_GRACE", 0.8)
    monkeypatch.setattr(slide_inbox, "HARD_CAP", 1.2)
    inbox = DeckInbox()
    _later(0.3, lambda: inbox.post("j", "t", "touch"))
    started = time.monotonic()
    assert inbox.wait("j", "t", "outline", 0.5) is None
    waited = time.monotonic() - started
    assert 0.9 < waited < 2.0, waited


def test_a_cancelled_job_stops_the_wait() -> None:
    inbox = DeckInbox()
    stop = {"now": False}
    _later(0.2, lambda: stop.update(now=True))
    started = time.monotonic()
    assert inbox.wait("j", "t", "theme", 10.0, stop=lambda: stop["now"]) is None
    assert time.monotonic() - started < 2.0


def test_screen_values_are_cut_and_checked() -> None:
    inbox = DeckInbox()
    with pytest.raises(ValueError):
        inbox.post("j", "t", "explode", 1)
    with pytest.raises(ValueError):
        inbox.post("j", "t", "note", {"index": 0, "text": "x"})
    with pytest.raises(ValueError):
        inbox.post("j", "t", "outline", [])
    inbox.post("j", "t", "note", {"index": 2, "text": "가" * 999})
    assert len(inbox.take_notes("j", "t")[2]) == slide_inbox.MAX_NOTE


def test_pause_holds_until_resumed() -> None:
    inbox = DeckInbox()
    inbox.post("j", "t", "pause")
    _later(0.4, lambda: inbox.post("j", "t", "resume"))
    waited = inbox.hold_while_paused("j", "t")
    assert 0.3 <= waited < 2.0


# ── ① 결 고르기 ─────────────────────────────────────────────────────────────
def test_the_person_picks_a_style_and_the_model_gets_that_styles_layouts(tmp_path: Path) -> None:
    tools, sent = _tools(tmp_path)
    _later(0.3, lambda: tools.deck_inbox.post("j", "카페 보고", "theme", "ink"))
    out = tools.make_slide({"title": "카페 보고", "about": "동네 카페 분기 매출 보고", "say": "숫자가 많아 차분한 결을 권합니다",
                            "__job_id": "j"})
    assert out["theme"] == "ink" and out["person"]["theme"] == "ink" and "골랐다" in out["person"]["said"]
    assert "outline" in out["next"]
    shown = next(payload for event, payload in sent if event == "deck_themes")
    assert shown["say"] == "숫자가 많아 차분한 결을 권합니다" and shown["wait_s"] > 0 and len(shown["picks"]) == 3
    assert (tmp_path / "out/slides/j/카페 보고/theme.txt").read_text(encoding="utf-8") == "ink"
    # 사람이 고른 결을 모델이 다른 결로 덮으면 돌려보낸다.
    with pytest.raises(ValueError, match="theme_person_chose"):
        tools.make_slide({"title": "카페 보고", "index": 1, "total": 2, "theme": "paper", "html": COVER, "__job_id": "j"})
    assert (tmp_path / "out/slides/j/카페 보고/theme.txt").read_text(encoding="utf-8") == "ink"


def test_without_a_pick_it_goes_with_the_suggested_style(tmp_path: Path) -> None:
    tools, sent = _tools(tmp_path)
    out = tools.make_slide({"title": "x", "about": "동네 카페 분기 매출 보고", "__job_id": "j"})
    assert out["theme"] == out["recommended"][0]["theme"] and out["person"]["theme"] == ""
    assert ("deck_theme_set", {"job_id": "j", "title": "x", "theme": out["theme"], "by": "default"}) in sent


def test_a_job_claude_handed_over_does_not_wait(tmp_path: Path) -> None:
    """클로드가 맡긴 판(mcp)은 보는 사람이 없다 — 곧바로 넘어간다."""
    tools, sent = _tools(tmp_path, origin="mcp")
    started = time.monotonic()
    out = tools.make_slide({"title": "x", "about": "보고", "__job_id": "j"})
    assert time.monotonic() - started < 1.0 and "보는 사람이 없는" in out["person"]["said"]
    assert next(payload for event, payload in sent if event == "deck_themes")["wait_s"] == 0


def test_a_second_guide_call_does_not_ask_again(tmp_path: Path) -> None:
    tools, sent = _tools(tmp_path, origin="mcp")
    tools.make_slide({"title": "x", "__job_id": "j"})
    tools.make_slide({"title": "x", "theme": "ink", "__job_id": "j"})
    assert [event for event, _ in sent].count("deck_themes") == 1


# ── ② 이야기판 ──────────────────────────────────────────────────────────────
def test_an_unknown_outline_name_becomes_a_parts_slide(tmp_path: Path) -> None:
    """10-26 사다리 1단: 모든 결이 부품 결이 된 뒤로 이야기판의 모르는 틀 이름은 돌려보내지 않고 부품 장으로 받는다(알림과 함께)."""
    tools, _ = _tools(tmp_path, origin="mcp")
    tools.make_slide({"title": "x", "theme": "paper", "__job_id": "j"})
    out = tools.make_slide({"title": "x", "outline": [{"layout": "nope", "claim": "a"}], "__job_id": "j"})
    assert out["outline"][0]["layout"] == "parts" and "nope → parts" in out["fixed"][0]


def test_the_person_reorders_and_rewrites_the_outline(tmp_path: Path) -> None:
    tools, sent = _tools(tmp_path)
    tools.deck_inbox.post("j", "x", "theme", "paper")  # 결 고르기는 바로 끝나게(지난 답은 지워지므로 아래에서 다시)
    _later(0.2, lambda: tools.deck_inbox.post("j", "x", "theme", "paper"))
    tools.make_slide({"title": "x", "__job_id": "j"})
    plan = [{"layout": "cover", "claim": "AI 소개"}, {"layout": "parts", "claim": "빨라졌다"}, {"layout": "closing", "claim": "다음 걸음"}]
    edited = [plan[0], {"layout": "closing", "claim": "이번 주에 깔아 보기"}]
    _later(0.3, lambda: tools.deck_inbox.post("j", "x", "outline", edited))
    out = tools.make_slide({"title": "x", "outline": plan, "say": "숫자 장을 가운데에", "__job_id": "j"})
    assert out["outline"] == edited and out["total"] == 2 and out["person"]["changed"]
    shown = next(payload for event, payload in sent if event == "deck_outline")
    assert shown["cards"] == plan and shown["say"] == "숫자 장을 가운데에" and shown["layouts"] == ["cover", "parts", "closing"]
    assert ("deck_outline_set", {"job_id": "j", "title": "x", "cards": edited, "by": "person"}) in sent


# ── ③ 만들기 — 한마디 · 굽기 ─────────────────────────────────────────────────
def test_a_note_on_a_slide_is_handed_over_and_blocks_baking_until_fixed(tmp_path: Path, monkeypatch) -> None:
    baked: list = []
    monkeypatch.setattr(slides, "render_in_subprocess", lambda deck, out: baked.append(out) or {"slides": 2})
    tools, sent = _tools(tmp_path, origin="mcp")
    first = tools.make_slide({"title": "x", "index": 1, "total": 2, "parts": COVER_PARTS, "note": "표지는 짧게", "__job_id": "j"})
    assert first["next"].startswith("2번")
    assert next(payload for event, payload in sent if event == "deck_slide")["note"] == "표지는 짧게"
    tools.deck_inbox.post("j", "x", "note", {"index": 1, "text": "제목을 더 짧게"})
    last = tools.make_slide({"title": "x", "index": 2, "total": 2, "parts": BIG_PARTS, "__job_id": "j"})
    assert last["person_notes"] == [{"index": 1, "text": "제목을 더 짧게"}] and "1번 장" in last["next"]
    assert not baked and "path" not in last
    fixed = tools.make_slide({"title": "x", "index": 1, "total": 2, "parts": COVER_PARTS, "__job_id": "j"})
    assert baked and fixed.get("path"), fixed
