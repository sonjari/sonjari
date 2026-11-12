"""기능 카드 찾기(`sonjari_guide(query)`) · 손님 PC 깔기 (2026-11-12 · 설계_기능카드 §4-5 · §2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis import capability_cards as cc
from alture_jarvis.guide_skill import GuideSkillService, render_skill

# 정해 둔 질문 → 위 3장 안에 있어야 할 카드(설계 §4-5 양방향: 맞는 질문은 찾고, 엉뚱한 질문은 「없음」)
POSITIVE = [
    ("유니티 참조 잇기", "game/unity-reference"),
    ("카메라가 플레이어 따라가게 칸에 넣기", "game/unity-reference"),
    ("unity reference", "game/unity-reference"),
    ("드래그해서 넣는 칸", "game/unity-reference"),
    ("에디터 안 열림", "game/unity-editor-connect"),
    ("유니티 에디터가 연결 안 돼요", "game/unity-editor-connect"),
    ("콘솔 오류 보기", "game/unity-see-screen"),
    ("screenshot game view", "game/unity-see-screen"),
    ("큰 텍스처 점검", "game/unity-checks"),
    ("missing script", "game/unity-checks"),
    ("씬 저장", "game/unity-scene-edit"),
    ("오브젝트 만들기", "game/unity-scene-edit"),
    ("C# 에디터 스크립트 돌려보기", "game/unity-new-script"),
    ("유니티 버전 확인", "game/unity-project-overview"),
]
NEGATIVE = ["포토샵 레이어", "엑셀 피벗", "kubernetes deploy", "ㅋㅋ"]

# conftest 가 모든 시험에서 `refresh_installed` 를 막아 둔다(실제 사용자 가이드를 안 고치게). 이 모듈은 tmp home 만 쓰므로
# 불러올 때(막기 전) 원래 함수를 잡아 둔다.
_REAL_REFRESH = GuideSkillService.refresh_installed


@pytest.mark.parametrize("query,want", POSITIVE)
def test_finds_the_right_card(query: str, want: str) -> None:
    picked, _ = cc.search(query)
    assert want in [card.id for card in picked], f"{query} → {[c.id for c in picked]}"


@pytest.mark.parametrize("query", NEGATIVE)
def test_says_no_card_instead_of_guessing(query: str) -> None:
    picked, _ = cc.search(query)
    assert picked == [], f"{query} → {[c.id for c in picked]}"
    assert "카드가 없습니다" in cc.render_search(query)
    assert "No capability card" in cc.render_search(query, lang="en")


def test_off_pack_gets_a_note_and_on_pack_does_not() -> None:
    off = cc.render_search("유니티 참조", enabled_packs=set())
    on = cc.render_search("유니티 참조", enabled_packs={"game"})
    unknown = cc.render_search("유니티 참조", enabled_packs=None)
    assert "팩이 꺼져 있습니다" in off and "대신 켜지 마세요" in off
    assert "팩이 꺼져 있습니다" not in on
    assert "팩이 꺼져 있습니다" not in unknown, "팩 상태를 모르면 꺼짐이라고 말하지 않는다"


def test_returns_at_most_three_and_lists_the_rest() -> None:
    picked, more = cc.search("unity")
    assert len(picked) == 3 and more, "넓은 낱말이면 3장 + 나머지 id"
    text = cc.render_search("unity")
    assert "더 걸린 카드:" in text


def test_guide_tells_where_cards_are_in_both_languages() -> None:
    ko, en = render_skill([], "ko"), render_skill([], "en")
    assert "## 기능 카드" in ko and "`cards/`" in ko and "sonjari-cards" in ko and 'query="' in ko
    assert "## Capability cards" in en and "`cards/`" in en and "sonjari-cards" in en and 'query="' in en


def test_install_puts_cards_next_to_the_skill_with_bom(tmp_path: Path) -> None:
    service = GuideSkillService(home=tmp_path)
    result = service.install_claude_code([])
    cards = tmp_path / ".claude" / "skills" / "sonjari-guide" / "cards"
    assert result["cards"]["ok"] and (cards / cc.MARK_FILE).exists()
    card = cards / "game" / "unity-reference.md"
    assert card.read_bytes().startswith(b"\xef\xbb\xbf"), "코덱스(PowerShell 5.1)가 한글을 깨뜨리지 않게 BOM"
    assert cc.load_cards(cards), "깐 폴더에서도 카드가 읽힌다"
    # 지우면 카드도 같이
    service.remove_claude_code()
    assert not cards.exists()


def test_refresh_updates_cards_only_where_we_installed(tmp_path: Path) -> None:
    service = GuideSkillService(home=tmp_path)
    _REAL_REFRESH(service, [])
    assert not (tmp_path / ".claude" / "skills" / "sonjari-guide" / "cards").exists(), "잇지 않은 곳엔 새로 만들지 않는다"
    service.install_claude_code([])
    stale = tmp_path / ".claude" / "skills" / "sonjari-guide" / "cards" / "game" / "old-card.md"
    stale.write_text("옛 카드", encoding="utf-8")
    _REAL_REFRESH(service, [])
    assert not stale.exists(), "앱이 켜질 때 이 판의 카드로 통째로 맞춘다"


def test_does_not_touch_a_foreign_folder(tmp_path: Path) -> None:
    foreign = tmp_path / ".codex" / "sonjari-cards"
    foreign.mkdir(parents=True)
    (foreign / "mine.md").write_text("사람이 만든 것", encoding="utf-8")
    result = cc.install_cards(foreign)
    assert result == {"ok": False, "error": "foreign_folder_exists", "path": str(foreign)}
    assert (foreign / "mine.md").exists()
    assert cc.remove_cards(foreign) is False


def test_codex_gets_cards_and_loses_them_on_remove(tmp_path: Path) -> None:
    service = GuideSkillService(home=tmp_path)
    service.install_note("codex", [])
    cards = tmp_path / ".codex" / "sonjari-cards"
    assert (cards / "game" / "unity-reference.md").exists()
    service.remove_note("codex")
    assert not cards.exists()


def test_zip_carries_the_cards(tmp_path: Path) -> None:
    import zipfile

    service = GuideSkillService(home=tmp_path, documents=tmp_path / "docs")
    path = Path(service.build_zip([])["path"])
    names = zipfile.ZipFile(path).namelist()
    assert "sonjari-guide/cards/game/unity-reference.md" in names
