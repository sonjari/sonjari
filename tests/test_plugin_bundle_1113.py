"""클로드 플러그인 폴더가 앤트로픽 디렉터리의 막히는 규칙을 지키는가 (2026-11-13 · 설계 docs/설계_클로드플러그인_2026-11-13.ko.md).

규칙 원문: claude.com/docs/plugins/pre-submission-checklist (11-13 읽음). 「막힘(Blocks)」 줄만 시험으로 박는다 —
보류(Held)는 검토자가 읽는 것이라 거절이 아니다(우리 MCP 명령이 앱이 깐 `sonjari-mcp` 라 보류가 예상된다).
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_plugin_skill", ROOT / "scripts" / "build_plugin_skill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_the_manifest_has_a_valid_distinctive_name_and_license() -> None:
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", manifest["name"])
    assert manifest["name"] not in {"claude", "anthropic", "official", "plugin", "mcp", "test"}
    assert manifest["license"] == "Apache-2.0" and (PLUGIN / "LICENSE").is_file()
    assert manifest.get("description") and manifest.get("version") and manifest.get("author")
    assert manifest["displayName"].isascii() and manifest["author"]["name"].isascii()


def test_the_readme_is_long_enough_and_says_what_it_runs_and_talks_to() -> None:
    text = re.sub(r"```.*?```", "", (PLUGIN / "README.md").read_text(encoding="utf-8"), flags=re.S)
    assert len(text.split()) >= 40
    for must in ("127.0.0.1", "sonjari-mcp", "control.token", "does nothing on its own"):
        assert must in text, must


def test_the_mcp_command_has_no_variables_shell_or_inline_program() -> None:
    config = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["sonjari"]
    words = [server["command"], *server.get("args", [])]
    assert not any("$" in w or "`" in w or "*" in w for w in words), "변수 · 명령 치환 · 와일드카드는 막힘"
    assert "-c" not in server.get("args", []), "인라인 프로그램(python -c)은 막힘"
    assert server["command"] == "sonjari-mcp" and "env" not in server, "토큰 · 경로를 설정에 적지 않는다(다리가 스스로 찾는다)"


def test_only_small_text_files_and_no_system_junk() -> None:
    files = [p for p in PLUGIN.rglob("*") if p.is_file()]
    assert 0 < len(files) <= 512
    for path in files:
        assert path.name not in {".DS_Store", "Thumbs.db", "desktop.ini"}
        assert path.stat().st_size < 256 * 1024, path
        assert b"\0" not in path.read_bytes()[:8192], f"바이너리는 보류: {path}"
        assert not re.search(r'[:<>"|?*]|[ .]$', path.name), path


def test_the_skill_is_the_same_guide_the_app_installs() -> None:
    """두 벌 금지 — 가이드를 고치고 `python scripts/build_plugin_skill.py` 를 안 돌리면 여기서 떨어진다."""
    saved = (PLUGIN / "skills" / "sonjari-guide" / "SKILL.md").read_text(encoding="utf-8")
    assert saved == _load_builder().render()
    assert saved.startswith("---\nname: sonjari-guide\ndescription: ")
