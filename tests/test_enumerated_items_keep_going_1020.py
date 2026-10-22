"""번호로 적어 준 항목은 하나하나가 할 일이다 (2026-10-20 AI 큐레이션 측정 · 잡 eec113c2 · 2812c5a7).

「아래 질문 5개를 하나씩 물어보고 … 1) … 5)」에서 다음 질문을 넣는 걸음이 「남은 요구에 진척 없음」으로 읽혀, 두 판 다 37~38걸음째에
「파일 만들 차례」가 걸려 마지막 질문이 잘렸다. 「N개 처리」 칸은 3개 한 것을 1개로 셌다.
"""

from __future__ import annotations

from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.tool_roster import _artifact_turn_is_due

PROMPT = (
    "ChatGPT(https://chatgpt.com)에서 아래 질문 5개를 하나씩 물어보고 답을 읽어서 엑셀 파일 하나로 정리해 줘. "
    "엑셀은 5개를 다 물어본 뒤에 만들어 줘.\n"
    "1) What local AI agent can I use with Claude Code to save my usage limits?\n"
    "2) Is there a free local AI agent for Windows that works with Claude Code over MCP?\n"
    "3) What tools let a local model on my own GPU do web research and make Excel files?\n"
    "4) 클로드 코드 사용 한도 아끼는 방법 알려줘\n"
    "5) 윈도우에서 내 그래픽카드로 도는 무료 AI 에이전트 추천해줘\n"
)
ITEMS = plan.enumerated_items(PROMPT)


def _ask(n: int) -> list[dict]:
    """질문 하나에 걸음 열: 새 대화 · 입력 · 보내기 · 기다리기 · 읽기 · 링크 · 스냅샷 …"""
    return [
        {"ok": True, "tool": "browser_click", "arguments": {"ref": "new"}},
        {"ok": True, "tool": "browser_fill", "arguments": {"ref": "box", "value": ITEMS[n]}},
        {"ok": True, "tool": "browser_click", "arguments": {"ref": "send"}},
        {"ok": True, "tool": "browser_wait", "arguments": {}},
        {"ok": True, "tool": "browser_read", "arguments": {}},
        {"ok": True, "tool": "browser_links", "arguments": {}},
        {"ok": True, "tool": "browser_snapshot", "arguments": {}},
        {"ok": True, "tool": "browser_snapshot", "arguments": {}},
        {"ok": True, "tool": "browser_click", "arguments": {"ref": "x"}},
        {"ok": True, "tool": "browser_snapshot", "arguments": {}},
    ]


def test_numbered_lines_are_items() -> None:
    assert len(ITEMS) == 5 and ITEMS[3].startswith("클로드 코드")


def test_count_action_counts_items_typed_in() -> None:
    reqs = plan.extract(PROMPT)
    count = next(req for req in reqs if req.kind == "count_action")
    steps = _ask(0) + _ask(1) + _ask(2)
    result = next(saw for req, _ok, saw in plan.check(reqs, sources=[], steps=steps) if req is count)
    assert result.startswith("3개 처리함")


def test_starting_the_next_item_is_progress_even_when_only_the_file_is_left() -> None:
    reqs = [req for req in plan.extract(PROMPT) if req.kind == "artifact"]
    steps = _ask(0) + _ask(1) + _ask(2) + _ask(3)[:5]
    results = plan.check(reqs, sources=[], steps=steps)
    assert not BrowserAgent._progress_matches_remaining_plan(steps, results)          # 예전: 진척 없음
    assert BrowserAgent._progress_matches_remaining_plan(steps, results, items=ITEMS)   # 이제: 넷째 질문을 시작함


def test_artifact_turn_waits_while_items_are_left_but_not_at_the_end() -> None:
    steps = _ask(0) + _ask(1) + _ask(2) + _ask(3)
    assert plan.items_still_going(steps, ITEMS)
    assert not _artifact_turn_is_due(stage_says=True, deliver_turn=False, web_research=True, read_sources=3, items_left=True)
    assert _artifact_turn_is_due(stage_says=True, deliver_turn=True, web_research=True, read_sources=3, items_left=True)


def test_numbered_instructions_never_used_as_input_hold_nothing_back() -> None:
    """이어받기 · 코드 일의 번호 줄은 지시문이다 — 입력으로 안 쓰였으면 아무것도 미루지 않는다."""
    items = plan.enumerated_items("다음을 해 줘.\n1. 시험을 먼저 돌려 본다\n2. 실패한 곳을 고친다\n3. 다시 돌린다\n")
    steps = [{"ok": True, "tool": "local_run_project_command", "arguments": {"command": "pytest -q"}}]
    assert items and not plan.items_still_going(steps, items)


def test_all_items_done_long_ago_hold_nothing_back() -> None:
    steps = _ask(0) + _ask(1) + _ask(2) + _ask(3) + _ask(4) + [{"ok": True, "tool": "browser_snapshot", "arguments": {}}] * 25
    assert not plan.items_still_going(steps, ITEMS)
