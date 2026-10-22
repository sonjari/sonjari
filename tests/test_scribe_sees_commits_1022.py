"""서기가 커밋을 「끝났다」 신호로 본다 (2026-10-22 · r/ClaudeCode kincaidDev · Emotional-Ad8388).

10-22 아침 압축 뒤 다시 넣은 「남은 일」에 이미 끝난 일이 남아 있었다. 서기는 글만 읽고 도구 호출은 안 봐서, 「끝났다」의 가장
확실한 신호인 `git commit` 을 못 봤다. 이제 커밋 명령은 「커밋」 줄로 보이고, 닫기의 근거로 쓸 수 있다. 새 카드의 근거는 아니다.
"""

from __future__ import annotations

import json

from alture_jarvis.scribe import Turn, _turn_of, draft_and_close


def _assistant_tool(command: str) -> str:
    return json.dumps({"type": "assistant", "timestamp": "2026-10-22T08:00:00Z", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": command, "description": "커밋"}}]}}, ensure_ascii=False)


def test_a_commit_command_becomes_a_commit_turn() -> None:
    turn = _turn_of(42, _assistant_tool('cd x && git -c user.name="a" commit -q -m "perf(code-index): 색인 따라잡기 빠르게"'))
    assert turn is not None and turn.role == "커밋" and "색인 따라잡기 빠르게" in turn.text and turn.line == 42


def test_other_tool_calls_and_amends_stay_hidden() -> None:
    assert _turn_of(1, _assistant_tool("git status --short")) is None
    assert _turn_of(2, _assistant_tool("pytest -q")) is None
    assert _turn_of(3, _assistant_tool('git commit --amend -m "x"')) is None


def test_a_commit_line_can_close_an_open_card_but_never_starts_one() -> None:
    turns = [Turn(10, "사람", "색인 고쳐 줘", "10-22 17:40"),
             Turn(11, "커밋", "git commit — -m \"perf(code-index): 색인 따라잡기 초당 6개 → 121개\"", "10-22 17:58")]
    open_card = {"kind": "open", "text": "색인 따라잡기를 빠르게 고친다", "line": 3, "quote": "색인", "session": "s1"}
    reply = json.dumps({
        "items": [{"kind": "decided", "text": "색인 고침을 커밋", "line": 11, "quote": "색인 따라잡기 초당 6개"}],
        "closes": [{"id": "c1", "status": "done", "line": 11, "quote": "색인 따라잡기 초당 6개"}],
    }, ensure_ascii=False)
    items, closes = draft_and_close(turns, lambda system, body: reply, [open_card])
    assert items == [], "커밋 줄만 근거인 새 카드는 만들지 않는다"
    assert len(closes) == 1 and closes[0]["status"] == "done" and closes[0]["line"] == 11


def test_the_close_rules_mention_commit_lines() -> None:
    from alture_jarvis import scribe

    assert "「커밋」 줄은 실제로 커밋한 기록" in scribe._CLOSE_RULES
