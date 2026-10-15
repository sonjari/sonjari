"""팩을 켜면 클로드·코덱스 잇기에 그 분야 사용서가 저절로 들어간다 (2026-09-27 · P7).

전역 지침은 매번 읽힌다(09-16 실측: 연결만 하면 안 부른다). 그래서 게임 팩을 켜면 지침에 「게임 일이면 이 사용서」 한 줄,
사용서는 스킬 자리(클로드)·지침 옆(코덱스)에. 끄면 둘 다 빠진다. 잇지 않은 클라이언트에는 아무것도 새로 만들지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.guide_skill import GuideSkillService
from alture_jarvis.packs import PackRegistry

REPO = Path(__file__).resolve().parents[1]


def _guides(enabled: list[bool]):
    registry_guide = (REPO / "packs" / "game" / "guide" / "SKILL.md").read_text(encoding="utf-8")
    return lambda: [{"id": "game", "name": "게임 팩", "text": registry_guide}] if enabled[0] else []


def test_the_game_pack_ships_a_guide_for_outside_ai(tmp_path: Path) -> None:
    registry = PackRegistry(REPO / "packs", tmp_path)
    game = registry.packs["game"]
    assert game.guide_path is not None and game.public()["guide"] is True
    text = game.guide_path.read_text(encoding="utf-8")
    assert text.startswith("---\nname: sonjari-game\n"), "스킬 앞머리 — 클로드 코드가 스킬로 읽는다"
    for tool in ("unity_list_recipes", "unity_run_recipe", "unity_try_script", "unity_editor_look", "unity_editor_change"):
        assert tool in text, tool
    assert "Read·Grep 하지 않는다" in text and "정기 실행" in text


def test_turning_the_pack_on_and_off_updates_connected_clients_only(tmp_path: Path) -> None:
    enabled = [True]
    service = GuideSkillService(home=tmp_path, pack_guides=_guides(enabled), clock=lambda: 1.0)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("# 내 규칙\n사람이 쓴 줄\n", encoding="utf-8")

    service.install_note("claude_code", [])
    skill = tmp_path / ".claude" / "skills" / "sonjari-game" / "SKILL.md"
    note = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8-sig")
    assert skill.is_file() and skill.read_text(encoding="utf-8-sig").startswith("---\nname: sonjari-game")
    assert str(skill) in note and "게임 팩" in note and "사람이 쓴 줄" in note

    enabled[0] = False
    done = service.refresh_packs([])
    assert "claude_code" in done and "codex" not in done, "잇지 않은 코덱스에는 아무것도 만들지 않는다"
    assert not skill.exists() and not skill.parent.exists()
    note = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8-sig")
    assert "sonjari-game" not in note and "사람이 쓴 줄" in note
    assert not (tmp_path / ".codex" / "AGENTS.md").exists()


def test_codex_gets_a_copy_next_to_its_agents_file(tmp_path: Path) -> None:
    service = GuideSkillService(home=tmp_path, pack_guides=_guides([True]), clock=lambda: 1.0)
    service.install_note("codex", [])
    copy = tmp_path / ".codex" / "sonjari-game.md"
    assert copy.is_file() and str(copy) in (tmp_path / ".codex" / "AGENTS.md").read_text(encoding="utf-8-sig")
    assert copy.read_bytes().startswith(b"\xef\xbb\xbf"), "코덱스는 PowerShell 5.1 로 읽는다 — BOM"
    service.remove_note("codex")
    assert not copy.exists()


def test_a_foreign_file_with_the_same_name_is_not_overwritten(tmp_path: Path) -> None:
    mine = tmp_path / ".claude" / "skills" / "sonjari-game" / "SKILL.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("사용자가 직접 만든 스킬", encoding="utf-8")
    service = GuideSkillService(home=tmp_path, pack_guides=_guides([True]), clock=lambda: 1.0)
    service.install_note("claude_code", [])
    assert mine.read_text(encoding="utf-8") == "사용자가 직접 만든 스킬"
    service.remove_note("claude_code")
    assert mine.exists(), "우리 표시가 없는 파일은 지우지 않는다"


def test_the_api_refreshes_notes_when_packs_change() -> None:
    source = (REPO / "src" / "alture_jarvis" / "api.py").read_text(encoding="utf-8")
    assert "runtime.packs.on_change(_refresh_pack_guides)" in source
    assert "pack_guides=lambda: _pack_guides()" in source, "잇기를 누를 때도 켜진 팩의 사용서가 같이 들어간다"
