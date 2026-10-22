"""코드 일 나눔 스위치 (2026-10-22 대표 · `guide_skill.code_delegation_broad`).

기본은 예전 그대로(좁게 · 파일 한두 개). `JARVIS_CODE_DELEGATION=broad` 이면 스킬 지침과 MCP 안내문이 **같이** 「버그 · 기능 단위,
클로드는 판단 · 손자리는 읽기와 돌리기」로 바뀐다. 둘이 다른 말을 하면 클로드가 어느 쪽을 따를지 모른다.
"""

from __future__ import annotations

from alture_jarvis import mcp_server
from alture_jarvis.guide_skill import code_delegation_broad, render_skill
from alture_jarvis.mcp_server import DELEGATION_TOOLS, GUIDE_TOOL, INSTRUCTIONS, instructions_ko

TOOLS = [dict(t) for t in DELEGATION_TOOLS] + [dict(GUIDE_TOOL)]


def test_default_stays_narrow(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_CODE_DELEGATION", raising=False)
    assert not code_delegation_broad()
    skill = render_skill(TOOLS)
    assert "한 번에 파일 한두 개 크기" in skill
    assert instructions_ko() == INSTRUCTIONS


def test_broad_flips_skill_and_instructions_together(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CODE_DELEGATION", "broad")
    skill = render_skill(TOOLS)
    text = instructions_ko()
    assert "버그 하나 · 기능 하나" in skill and "버그 하나 · 기능 하나" in text
    assert "한 번에 파일 한두 개 크기" not in skill
    assert "파일 한두 개 크기로 쪼개" not in text
    assert "여러 파일에 걸친 고치기" not in skill, "「안 맡길 것」 칸도 같이 바뀌어야 한다"
    # 처음 보는 API 는 여전히 클로드 몫이다 — 웹에서 공부하느라 오래 걸린 기록(10-01)은 그대로다.
    assert "처음 보는 API" in skill and "처음 보는 API" in text
    assert text.count("\n") == INSTRUCTIONS.count("\n"), "안내문은 두 줄만 바뀌고 나머지는 그대로다"


def test_server_uses_the_switch(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CODE_DELEGATION", "broad")
    assert mcp_server.instructions_ko() != INSTRUCTIONS
