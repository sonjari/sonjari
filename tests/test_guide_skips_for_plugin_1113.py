"""손자리 클로드 플러그인이 깔려 있으면 앱은 가이드 사본을 깔지 않는다 (2026-11-13 대표 「중복으로 들어가는 거 아니가」).

플러그인(`plugin/skills/sonjari-guide/` + cards)과 앱 사본(`~/.claude/skills/sonjari-guide/`)은 같은 render_skill 로 만든다 —
둘 다 있으면 클로드 스킬 목록에 같은 가이드가 두 줄로 뜬다. 플러그인이 있으면: 깔지 않는다 · 예전에 깐 **우리** 사본은 걷는다 ·
남이 만든 같은 이름 파일은 둔다 · 전역 지침은 플러그인 쪽 가이드를 가리킨다 · 플러그인을 지우면 다시 깐다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.guide_skill import GuideSkillService

TOOLS = [{"name": "sonjari_task", "description": "hand off one task"}]
#: conftest 가 실제 사용자 폴더를 지키려고 refresh_installed 를 빈 함수로 바꿔 둔다 — 이 시험은 tmp 집에서 진짜를 쓴다.
_REAL_REFRESH = GuideSkillService.refresh_installed


@pytest.fixture(autouse=True)
def _real_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GuideSkillService, "refresh_installed", _REAL_REFRESH)


def _service(home: Path) -> GuideSkillService:
    service = GuideSkillService(home=home, clock=lambda: 1.0)
    cards = home / "cards_src"
    (cards / "game").mkdir(parents=True)
    (cards / "game" / "a.md").write_text("# card\n", encoding="utf-8")
    service.cards_source = cards
    return service


def _install_plugin(home: Path, name: str = "sonjari@claude-plugins") -> Path:
    install = home / ".claude" / "plugins" / "cache" / "x" / name.split("@")[0] / "0.4.44"
    guide = install / "skills" / "sonjari-guide" / "SKILL.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("---\nname: sonjari-guide\n---\nplugin copy\n", encoding="utf-8")
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    registry.write_text(json.dumps({"version": 2, "plugins": {name: [{"scope": "user", "installPath": str(install)}]}}),
                        encoding="utf-8")
    return guide


def test_without_the_plugin_the_app_installs_its_copy(tmp_path: Path) -> None:
    service = _service(tmp_path)
    (tmp_path / ".claude").mkdir()
    done = service.install_claude_code(TOOLS)
    assert done["ok"] and "skipped" not in done
    assert service.claude_code_path().is_file()
    assert service.status()["claude_code"]["plugin"] == ""


def test_with_the_plugin_the_app_skips_and_points_the_note_at_the_plugin(tmp_path: Path) -> None:
    service = _service(tmp_path)
    plugin_guide = _install_plugin(tmp_path)
    done = service.install_claude_code(TOOLS)
    assert done == {"ok": True, "path": str(plugin_guide), "skipped": "plugin", "removed_copy": False}
    assert not service.claude_code_path().exists()
    assert service.status()["claude_code"]["plugin"] == str(plugin_guide)
    service.install_note("claude_code", TOOLS)
    note = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8-sig")
    assert str(plugin_guide) in note and str(service.claude_code_path()) not in note


def test_plugin_installed_later_removes_our_copy_on_app_start(tmp_path: Path) -> None:
    service = _service(tmp_path)
    (tmp_path / ".claude").mkdir()
    service.install_claude_code(TOOLS)
    service.install_note("claude_code", TOOLS)
    ours = service.claude_code_path()
    assert ours.is_file() and (ours.parent / "cards").is_dir()

    plugin_guide = _install_plugin(tmp_path)
    done = service.refresh_installed(TOOLS)
    assert done.get("claude_code_skill_removed_for_plugin") == str(ours), done
    assert not ours.exists() and not (ours.parent / "cards").exists()
    note = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8-sig")
    assert str(plugin_guide) in note


def test_a_foreign_skill_with_the_same_name_is_left_alone(tmp_path: Path) -> None:
    service = _service(tmp_path)
    mine = service.claude_code_path()
    mine.parent.mkdir(parents=True)
    mine.write_text("---\nname: sonjari-guide\n---\nwritten by the user\n", encoding="utf-8")
    _install_plugin(tmp_path)
    done = service.install_claude_code(TOOLS)
    assert done["skipped"] == "plugin" and done["removed_copy"] is False
    assert mine.read_text(encoding="utf-8") == "---\nname: sonjari-guide\n---\nwritten by the user\n"


def test_other_plugins_and_a_broken_registry_do_not_count(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _install_plugin(tmp_path, name="sonjari-animator@claude-plugins")  # 이름이 다르면 손자리 가이드 플러그인이 아니다
    assert service.plugin_guide_path() is None
    (tmp_path / ".claude" / "plugins" / "installed_plugins.json").write_text("{not json", encoding="utf-8")
    assert service.plugin_guide_path() is None
