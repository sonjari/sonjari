"""클로드 플러그인의 스킬 파일을 만든다 (2026-11-13 · 설계 docs/설계_클로드플러그인_2026-11-13.ko.md).

본문은 앱이 클로드 코드에 깔아 주는 가이드와 **같은 함수**(`guide_skill.render_skill`)로 만든다 — 두 벌이 갈리면 안 된다.
플러그인만 깐 사람(앱 없음)을 위해 머리말 바로 밑에 「MCP 가 안 보이면 앱부터」 한 단락만 더한다.
`tests/test_plugin_bundle_1113.py` 가 저장된 파일이 지금 만든 것과 같은지 본다(가이드를 고치고 이 스크립트를 안 돌리면 시험이 떨어진다).

    python scripts/build_plugin_skill.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SKILL_PATH = ROOT / "plugin" / "skills" / "sonjari-guide" / "SKILL.md"
STORE_URL = "https://apps.microsoft.com/detail/9N458V8HPTR2"

PLUGIN_NOTE = (
    "> **If the Sonjari MCP tools (`sonjari_task` and the rest) are not available in this session**, the Sonjari desktop app\n"
    "> is not installed or not running on this computer. This plugin only connects Claude to that app. Tell the user to\n"
    f"> install it from the Microsoft Store ({STORE_URL}, Windows 10/11 with an NVIDIA GPU; macOS is in beta), open it once,\n"
    "> and start a new session. Do not try to install or start it yourself.\n\n"
)


def render() -> str:
    from alture_jarvis.delegation import DELEGATION_TOOLS, GUIDE_TOOL, localized_tool
    from alture_jarvis.guide_skill import render_skill

    body = render_skill([localized_tool(tool, "en") for tool in (*DELEGATION_TOOLS, GUIDE_TOOL)], "en")
    head, sep, rest = body.partition("\n---\n")
    if not sep or not head.startswith("---"):
        raise SystemExit("render_skill 머리말 모양이 바뀌었다 — 이 스크립트를 고칠 것")
    return f"{head}{sep}\n{PLUGIN_NOTE}{rest.lstrip()}"


def main() -> int:
    SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SKILL_PATH.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {SKILL_PATH.relative_to(ROOT)} ({SKILL_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
