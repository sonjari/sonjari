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

# 2026-11-13: 디렉터리가 v0.4.43 을 거절했다 — 「PC 에서 도는 MCP 서버는 인증된 조직만」. 그래서 플러그인은 스킬만 싣고,
#   손자리 연결은 앱의 설정 › 연결 › Connect 단추가 한다(mcp_connect.py: Claude Desktop 설정 파일 · Claude Code `claude mcp add-json`).
#   설치 · 연결을 클로드가 직접 하게 쓰지 않는다 — 동의 항목 「선언한 서버 밖에서 코드를 실행하지 않는다」.
PLUGIN_NOTE = (
    "> **If the Sonjari MCP tools (`sonjari_task` and the rest) are not available in this session**, Sonjari is not\n"
    "> connected to this Claude yet. This plugin carries only this guide; the connection is made by the Sonjari desktop app.\n"
    "> Tell the user these three steps, then stop and wait for them:\n"
    f"> 1. Install Sonjari from the Microsoft Store ({STORE_URL}). Windows 10/11 with an NVIDIA GPU; macOS is in beta.\n"
    "> 2. Open the app, go to **Settings › Connect**, and press **Connect** next to Claude Code or Claude Desktop.\n"
    "> 3. Start a new Claude session (Claude Desktop restarts itself when you press Connect).\n"
    ">\n"
    "> Do not install the app, edit Claude's settings, or run any setup command yourself. The user does these steps.\n\n"
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
