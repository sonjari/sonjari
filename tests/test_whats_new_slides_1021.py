"""업데이트 뒤 「바뀐 것」 슬라이드 (2026-10-21 대표 「그림에 글을 넣어 피피티마냥 한눈에 알아보고 이쁘게」).

0.4.29.0 의 목록은 22줄이었다 — 아무도 안 읽는다. 판마다 3~4장의 슬라이드를 둔다.
여기서 지키는 것: 슬라이드가 없는 옛 판은 그대로 목록으로 · 한 · 영 둘 다 있고 칸이 맞음 · **숫자에는 잰 조건** ·
그림은 실제로 있는 파일만.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis import whats_new

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "ui" / "public"
NOTE_FILES = sorted(whats_new.NOTES_DIR.glob("*.json"))
HANGUL = lambda text: any("가" <= ch <= "힣" for ch in text)  # noqa: E731


def _raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── 판의 글 파일 자체 ───────────────────────────────────────────────────────

def test_there_are_note_files() -> None:
    assert len(NOTE_FILES) >= 4  # 0.4.27 ~ 0.4.30


@pytest.mark.parametrize("path", NOTE_FILES, ids=lambda p: p.stem)
def test_slides_exist_in_both_languages_with_matching_shape(path: Path) -> None:
    data = _raw(path)
    ko, en = data["ko"].get("slides"), data["en"].get("slides")
    if ko is None and en is None:
        return  # 슬라이드 없는 옛 판 — 목록으로 떨어진다
    assert isinstance(ko, list) and isinstance(en, list), "슬라이드는 한 · 영 둘 다 있어야 한다"
    assert 1 <= len(ko) <= 6 and len(ko) == len(en)
    for one_ko, one_en in zip(ko, en):
        for slide in (one_ko, one_en):
            assert set(slide) <= {"title", "body", "try", "visual"}, slide
            assert str(slide.get("title") or "").strip() and str(slide.get("body") or "").strip()
        # 한 장에 무엇이 있는지는 두 말에서 같아야 한다(한쪽만 그림 · 막대 · 「이렇게 말해 보세요」가 있으면 안 된다)
        assert ("try" in one_ko) == ("try" in one_en)
        # 숫자 막대는 두 말에 똑같이 — 같은 잰 값이다. 그림은 말마다 따로 찍으므로 한쪽에만 있어도 된다
        # (그 말의 화면을 못 찍었으면 그 장은 「이렇게 말해 보세요」를 위쪽 칸에 크게 둔다).
        stat_ko = one_ko.get("visual") if (one_ko.get("visual") or {}).get("kind") == "stat" else None
        stat_en = one_en.get("visual") if (one_en.get("visual") or {}).get("kind") == "stat" else None
        assert (stat_ko is None) == (stat_en is None)
        if stat_ko:
            assert (stat_ko["before"], stat_ko["after"]) == (stat_en["before"], stat_en["after"])
        for slide in (one_ko, one_en):
            if (slide.get("visual") or {}).get("kind") == "image":
                assert "try" in slide or slide["visual"]["alt"], slide
        assert not HANGUL(json.dumps(one_en, ensure_ascii=False)), one_en


@pytest.mark.parametrize("path", NOTE_FILES, ids=lambda p: p.stem)
def test_every_number_has_a_basis_and_every_picture_is_a_real_file(path: Path) -> None:
    data = _raw(path)
    for lang in ("ko", "en"):
        for slide in data[lang].get("slides") or []:
            visual = slide.get("visual")
            if visual is None:
                continue
            assert visual["kind"] in {"stat", "image"}, visual
            if visual["kind"] == "stat":
                assert str(visual.get("basis") or "").strip(), f"잰 조건 없는 숫자: {visual}"
                assert str(visual.get("label") or "").strip()
                assert isinstance(visual["before"], (int, float)) and isinstance(visual["after"], (int, float))
                assert visual["before"] > 0 and visual["after"] >= 0
            else:
                assert visual["src"].startswith(f"whats_new/{path.stem}/"), visual["src"]
                assert (PUBLIC / visual["src"]).is_file(), f"그림 파일이 없다: ui/public/{visual['src']}"
                assert str(visual.get("alt") or "").strip()
            # 화면에 나가는 모양(정리한 뒤)에서도 빠지지 않아야 한다 — 칸이 모자라 조용히 버려지면 안 된다
    for lang in ("ko", "en"):
        raw_count = len(data[lang].get("slides") or [])
        notes = whats_new.notes_for(path.stem, lang)
        assert notes is not None and len(notes["slides"]) == raw_count
        raw_visuals = sum(1 for slide in data[lang].get("slides") or [] if "visual" in slide)
        assert sum(1 for slide in notes["slides"] if "visual" in slide) == raw_visuals


def test_this_release_has_three_or_four_slides_and_the_number_slide_says_how_it_was_measured() -> None:
    for lang in ("ko", "en"):
        slides = whats_new.notes_for("0.4.30.0", lang)["slides"]
        assert 3 <= len(slides) <= 4
        stats = [slide["visual"] for slide in slides if slide.get("visual", {}).get("kind") == "stat"]
        assert stats and stats[0]["before"] == 16.0 and stats[0]["after"] == 4.3  # 설계 문서 §10-6 그대로
    assert "3권" in whats_new.notes_for("0.4.30.0", "ko")["slides"][1]["visual"]["basis"]


# ── 뒤로 호환 · 정리 규칙 ─────────────────────────────────────────────────────

def test_an_old_release_without_slides_still_gives_the_list() -> None:
    for lang in ("ko", "en"):
        notes = whats_new.notes_for("0.4.29.0", lang)
        assert notes["slides"] == [] and notes["changes"].strip() and notes["tour"].strip()


def test_status_carries_the_slides(tmp_path: Path) -> None:
    whats_new.mark_seen(tmp_path, "0.4.29.0")
    got = whats_new.status(tmp_path, "0.4.30.0", setup_done=True, lang="en")
    assert got["show"] is True and len(got["slides"]) >= 3 and got["changes"]
    old = whats_new.status(tmp_path, "0.4.29.0", setup_done=True)
    assert old["show"] is False  # 이미 본 판


def _write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict) -> None:
    (tmp_path / "1.0.0.0.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(whats_new, "NOTES_DIR", tmp_path)


def test_english_without_slides_falls_back_to_korean_slides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slide = {"title": "제목", "body": "한 줄"}
    _write(tmp_path, monkeypatch, {"ko": {"changes": "- 하나", "slides": [slide]}, "en": {"changes": "- one"}})
    assert whats_new.notes_for("1.0.0.0", "en")["slides"] == [slide]
    assert whats_new.notes_for("1.0.0.0", "en")["changes"] == "- one"


def test_a_number_without_a_basis_or_an_odd_picture_never_reaches_the_screen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slides = [
        {"title": "a", "body": "b", "visual": {"kind": "stat", "label": "첫 글자", "before": 16, "after": 4}},
        {"title": "a", "body": "b", "visual": {"kind": "image", "src": "../../secret.png", "alt": "x"}},
        {"title": "a", "body": "b", "visual": {"kind": "image", "src": "C:/x.png", "alt": "x"}},
        {"title": "a", "body": "b", "visual": {"kind": "chart", "src": "whats_new/x.png"}},
        {"title": "", "body": "제목이 없다"},
        "글자 하나",
    ]
    _write(tmp_path, monkeypatch, {"ko": {"changes": "- 하나", "slides": slides}})
    got = whats_new.notes_for("1.0.0.0", "ko")["slides"]
    assert got == [{"title": "a", "body": "b"}] * 4


def test_ui_fixture_matches_the_backend() -> None:
    """화면 리허설(`?fixture=…&whatsnew=<판>`)의 글은 진짜 백엔드 출력이어야 한다 — 글을 고치면 이 표본도 다시 뽑는다."""
    fixture = json.loads((ROOT / "ui" / "src" / "fixtures" / "whatsNewFixture.json").read_text(encoding="utf-8"))
    assert fixture
    for version, by_lang in fixture.items():
        for lang, shown in by_lang.items():
            assert shown == {"show": True, "version": version, **whats_new.notes_for(version, lang)}, (version, lang)
