"""이름 2단계(2026-09-29, Ontelic → Sonjari 설치 이름): **옛 자리가 있는 PC 는 그 자리를 이어 쓴다.**

노트북 베타엔 `~\Ontelic\engine`(받아 둔 AI 엔진)·`%LOCALAPPDATA%\Ontelic`(토큰·DB)·기억 복제본이 있다.
새 이름 폴더로 갈라지면 모델을 다시 받고, 화면이 토큰을 못 찾고, 기억이 비어 보인다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alture_jarvis import brand
from alture_jarvis.guide_skill import GuideSkillService


def test_a_fresh_pc_gets_the_new_name(tmp_path: Path) -> None:
    assert brand.runtime_dir(tmp_path) == tmp_path / "Sonjari"
    assert brand.engine_dir(tmp_path) == tmp_path / "Sonjari" / "engine"
    assert brand.downloads_dir(tmp_path) == tmp_path / "Downloads" / "Sonjari"


def test_an_ontelic_pc_keeps_every_old_place(tmp_path: Path) -> None:
    (tmp_path / "Ontelic" / "engine").mkdir(parents=True)
    (tmp_path / "Downloads" / "Ontelic").mkdir(parents=True)
    local = tmp_path / "Local"
    (local / "Ontelic").mkdir(parents=True)
    assert brand.runtime_dir(local) == local / "Ontelic"
    # 엔진·업데이트·기억 복제본은 **한 규칙**으로 같은 자리 — 따로 정하면 한 PC 에서 둘로 갈린다.
    assert brand.engine_dir(tmp_path) == tmp_path / "Ontelic" / "engine"
    assert brand.update_dir(tmp_path) == tmp_path / "Ontelic" / "update"
    assert brand.backup_dir(tmp_path) == tmp_path / "Ontelic" / "backup"
    assert brand.downloads_dir(tmp_path) == tmp_path / "Downloads" / "Ontelic"


def test_the_oldest_app_data_still_wins(tmp_path: Path) -> None:
    (tmp_path / "AltureJarvis").mkdir()
    (tmp_path / "Ontelic").mkdir()
    assert brand.runtime_dir(tmp_path) == tmp_path / "AltureJarvis"


def test_rust_and_python_agree_on_the_app_data_chain() -> None:
    package_rs = (Path(__file__).resolve().parents[1] / "ui" / "src-tauri" / "src" / "package.rs").read_text(encoding="utf-8")
    assert f'RUNTIME_DIR_NAME: &str = "{brand.RUNTIME_DIR_NAME}"' in package_rs
    assert '[LEGACY_RUNTIME_DIR_NAME, "Ontelic"]' in package_rs
    assert brand.LEGACY_RUNTIME_DIR_NAMES == ("AltureJarvis", "Ontelic")


def test_the_old_guide_is_swapped_not_duplicated(tmp_path: Path) -> None:
    """옛 `ontelic-guide` 지침이 남으면 클로드가 없는 이름(ontelic_task)을 부른다 — 새 것으로 갈아 끼운다."""
    home = tmp_path / "home"
    old_skill = home / ".claude" / "skills" / "ontelic-guide" / "SKILL.md"
    old_skill.parent.mkdir(parents=True)
    old_skill.write_text("---\nname: ontelic-guide\n---\n<!-- ontelic-guide: generated -->\n", encoding="utf-8")
    note = home / ".claude" / "CLAUDE.md"
    note.write_text("# 내 지침\n\n<!-- ontelic-guide:start -->\n옛 블록\n<!-- ontelic-guide:end -->\n", encoding="utf-8")
    foreign = home / ".claude" / "skills" / "ontelic-notes" / "SKILL.md"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("사용자가 직접 쓴 것", encoding="utf-8")

    service = GuideSkillService(home=home, documents=tmp_path / "docs", clock=lambda: 7)
    tools = [{"name": "sonjari_task", "description": "맡기기"}]
    assert service.install_claude_code(tools)["ok"]
    assert service.install_note("claude_code", tools)["ok"]

    text = note.read_text(encoding="utf-8-sig")
    assert "옛 블록" not in text and text.count("sonjari-guide:start") == 1 and "# 내 지침" in text
    assert not old_skill.exists(), "옛 가이드가 남았다"
    assert foreign.exists(), "표시 없는 남의 파일을 지웠다"
    assert (home / ".claude" / "skills" / "sonjari-guide" / "SKILL.md").is_file()


def test_the_old_tool_names_still_work() -> None:
    from alture_jarvis.mcp_server import LEGACY_TOOL_NAMES, JarvisMcpBridge

    assert set(LEGACY_TOOL_NAMES) == {"ontelic_task", "ontelic_task_status", "ontelic_guide"}
    bridge = JarvisMcpBridge("http://sonjari.test", "t")
    text, error = asyncio.run(bridge.call("ontelic_task", {"task": ""}))
    assert error and "task 가 비어" in text, "옛 이름이 맡기기 문으로 안 갔다"


def test_connecting_claude_does_not_break_codex(tmp_path: Path) -> None:
    """클로드만 이어도 코덱스의 옛 가이드를 지웠다 — 코덱스 지침은 그 파일을 가리켜 끊겼다(코덱스 교차 검사)."""
    home = tmp_path / "home"
    old_codex = home / ".codex" / "ontelic-guide.md"
    old_codex.parent.mkdir(parents=True)
    old_codex.write_text("<!-- ontelic-guide: generated -->\n옛 가이드", encoding="utf-8")
    service = GuideSkillService(home=home, documents=tmp_path / "docs", clock=lambda: 7)
    assert service.install_claude_code([{"name": "sonjari_task", "description": "x"}])["ok"]
    assert old_codex.exists(), "클로드를 잇다가 코덱스 가이드를 지웠다"
    assert service.install_note("codex", [{"name": "sonjari_task", "description": "x"}])["ok"]
    assert not old_codex.exists() and (home / ".codex" / "sonjari-guide.md").is_file()


def test_a_foreign_codex_guide_is_not_overwritten(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mine = home / ".codex" / "sonjari-guide.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("사용자가 직접 쓴 메모", encoding="utf-8")
    service = GuideSkillService(home=home, documents=tmp_path / "docs", clock=lambda: 7)
    result = service.install_note("codex", [{"name": "sonjari_task", "description": "x"}])
    assert result == {"ok": False, "error": "foreign_guide_exists", "path": str(mine)}
    assert mine.read_text(encoding="utf-8") == "사용자가 직접 쓴 메모"
