"""하네스 탓 9 (2026-11-08 게임 시험 4단계 · 맥 job f731e765): 이 PC 에서 셸로 일하던 판이 조사 뒤 「파일 만들 차례」에 걸려
컴파일 셸이 not_this_stage 로 막혔다. PC 기록에도 같은 모양이 코드 모드 판 둘(27bb56f9 · 3f659137, local_run_project_command 포함).
그 판에서 이미 써 온 실행 손은 차례에도 남긴다 — 코워크 · 코드 모드 같은 고리라 둘 다 적용된다."""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import _run_hands_in_use
from alture_jarvis.tool_roster import _focused_tool_definitions


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


def test_run_hands_used_with_real_commands_are_kept() -> None:
    steps = [
        {"tool": "local_run_shell", "ok": True, "arguments": {"command": "Unity -batchmode -createProject x -quit"}},
        {"tool": "local_run_project_command", "ok": True, "arguments": {"command": ["python", "-m", "pytest"]}},
    ]
    assert _run_hands_in_use(steps) == {"local_run_shell", "local_run_project_command"}


def test_failed_empty_or_status_checks_do_not_count() -> None:
    steps = [
        {"tool": "local_run_shell", "ok": False, "arguments": {"command": "ls"}},
        {"tool": "local_run_shell", "ok": True, "arguments": {"background_id": "bg1", "wait_sec": 60}},
        {"tool": "local_run_project_command", "ok": True, "arguments": {"command": []}},
        {"tool": "browser_open", "ok": True, "arguments": {"url": "https://x"}},
    ]
    assert _run_hands_in_use(steps) == frozenset()


def test_artifact_turn_keeps_the_shell_when_it_was_the_work() -> None:
    tools = [_tool("local_write_file"), _tool("local_run_shell"), _tool("browser_open")]
    focused = _focused_tool_definitions(tools, "artifact", also=frozenset({"local_run_shell"}))
    names = {t["function"]["name"] for t in focused}
    assert "local_run_shell" in names and "browser_open" not in names, "더 찾기는 그대로 막는다"


def test_the_loop_feeds_run_hands_into_the_turn() -> None:
    source = (Path(__file__).parents[1] / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    assert "also=_unmet_action_tools(current_plan_results) | shell_work" in source
    assert "shell_work = _run_hands_in_use(steps)" in source
