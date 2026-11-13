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


def test_the_readme_is_long_enough_and_says_how_to_connect() -> None:
    text = re.sub(r"```.*?```", "", (PLUGIN / "README.md").read_text(encoding="utf-8"), flags=re.S)
    assert len(text.split()) >= 40
    for must in ("127.0.0.1", "Settings › Connect", "does nothing on its own", "ships no MCP server"):
        assert must in text, must


def test_the_plugin_ships_no_local_mcp_server() -> None:
    """11-13 디렉터리가 v0.4.43 을 거절: 「Local MCP servers accepted only from Verified organizations」.
    인증 조직이 될 때까지 플러그인은 스킬만 싣는다 — 연결은 앱의 설정 › 연결 › Connect(mcp_connect.py)."""
    assert not (PLUGIN / ".mcp.json").exists()
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "mcpServers" not in manifest


def test_the_skill_tells_the_user_how_to_connect_and_never_installs_itself() -> None:
    """서버가 없으니 도구가 안 보이는 세션이 기본이다 — 스킬 첫머리가 사람이 할 세 걸음을 말하고, 클로드는 설치하지 않는다
    (동의 항목 「선언한 서버 밖에서 코드를 실행하지 않는다」)."""
    head = (PLUGIN / "skills" / "sonjari-guide" / "SKILL.md").read_text(encoding="utf-8")[:2000]
    for must in ("Microsoft Store", "Settings › Connect", "new Claude session", "Do not install the app"):
        assert must in head, must


def test_only_small_text_files_and_no_system_junk() -> None:
    files = [p for p in PLUGIN.rglob("*") if p.is_file()]
    assert 0 < len(files) <= 512
    for path in files:
        assert path.name not in {".DS_Store", "Thumbs.db", "desktop.ini"}
        assert path.stat().st_size < 256 * 1024, path
        assert not re.search(r'[:<>"|?*]|[ .]$', path.name), path
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            continue  # 완전한 그림 파일은 허용(체크리스트 「Files in the plugin folder」)
        assert b"\0" not in path.read_bytes()[:8192], f"바이너리는 보류: {path}"


def test_the_icon_is_a_square_png_the_directory_accepts() -> None:
    """아이콘은 처음 저장 · 제출할 때 한 번만 정해진다(포털 경고 원문) — 제출 전에 있어야 한다. 512~2048px 정사각 · 2MB 미만."""
    import struct

    data = (PLUGIN / ".claude-plugin" / "icon.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert width == height and 512 <= width <= 2048 and len(data) < 2 * 1024 * 1024


def test_readme_links_are_https_only() -> None:
    """포털 경고(11-13): 「Use an https:// or mailto: URL」 — README 의 http:// 주소가 걸렸다."""
    assert "http://" not in (PLUGIN / "README.md").read_text(encoding="utf-8")


def test_the_plugin_carries_the_same_capability_cards_the_app_installs() -> None:
    """가이드가 「이 스킬 폴더의 cards/ 를 grep」 하라고 한다 — 플러그인을 깐 사람에게 앱은 카드를 따로 깔지 않으므로 여기 있어야 한다."""
    source = ROOT / "capabilities"
    shipped = PLUGIN / "skills" / "sonjari-guide" / "cards"
    want = {p.relative_to(source).as_posix(): p.read_text(encoding="utf-8-sig") for p in source.rglob("*.md")}
    have = {p.relative_to(shipped).as_posix(): p.read_text(encoding="utf-8") for p in shipped.rglob("*.md")}
    assert want and have == want, "카드를 고치고 `python scripts/build_plugin_skill.py` 를 안 돌렸다"


def test_the_skill_is_the_same_guide_the_app_installs() -> None:
    """두 벌 금지 — 가이드를 고치고 `python scripts/build_plugin_skill.py` 를 안 돌리면 여기서 떨어진다."""
    saved = (PLUGIN / "skills" / "sonjari-guide" / "SKILL.md").read_text(encoding="utf-8")
    assert saved == _load_builder().render()
    assert saved.startswith("---\nname: sonjari-guide\ndescription: ")


def test_the_manifest_links_a_privacy_policy_and_support() -> None:
    """포털 경고(11-13 main 검증): 「No privacy policy URL found」 — 규정 준수 동의 둘째 줄이 처리방침을 전제로 한다."""
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    for key in ("privacyPolicyUrl", "supportUrl", "documentationUrl"):
        assert manifest.get(key, "").startswith("https://"), key
