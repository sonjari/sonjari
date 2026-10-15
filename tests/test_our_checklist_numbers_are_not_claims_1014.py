"""답 끝에 우리가 붙인 「시킨 것 대조」의 숫자는 「도구가 준 적 없는 숫자」로 세지 않는다 (2026-10-14).

레딧 홍보 규칙 조사(맡긴 일)에서 대조 칸의 「14개 읽음 · 답에 7개」의 14 가 unsupported_numbers 로 찍혀 결과가
needs_review 가 됐다. 그 숫자는 하네스가 걸음 기록을 센 것이다. 양방향: 모델 글의 지어낸 숫자는 그대로 잡힌다.
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.delegation import summarize_job


def _job(answer: str, tool_numbers: list[str]) -> dict[str, Any]:
    steps = [{"tool": "browser_extract", "ok": True, "evidence": {},
              "evidence_record": {"effect": "read_web", "source_id": "https://old.reddit.com/r/x/about/rules"}}]
    return {"id": "j1", "status": "completed", "payload": {"prompt": "게시판 8곳 규칙 정리"},
            "result": {"answer": answer, "completion_state": "partial",
                       "agent_trace": {"steps": steps, "tool_numbers": tool_numbers, "tool_numbers_body": []}}}


CHECKLIST = "\n\n**시킨 것 대조**\n- ❌ 8개 이상 직접 열어 읽기 — 14개 읽음 · 답에 7개\n- ✅ 레딧에서 하기 — 1건\n"


def test_the_checklist_we_appended_is_not_counted() -> None:
    summary = summarize_job(_job("ClaudeAI 구독자는 1,194,006명입니다." + CHECKLIST, ["1194006"]))
    assert summary["unsupported_numbers"] == [] and summary["status"] == "done"
    assert "시킨 것 대조" in summary["answer"], "돌려주는 답에서는 대조 칸을 지우지 않는다"


def test_the_english_checklist_too() -> None:
    answer = "r/ClaudeAI has 1,194,006 members." + "\n\n**Checklist**\n- ❌ Read 8 or more — read 14 · 7 in the answer\n"
    assert summarize_job(_job(answer, ["1194006"]))["unsupported_numbers"] == []


def test_a_made_up_number_before_the_checklist_is_still_caught() -> None:
    summary = summarize_job(_job("ClaudeAI 구독자는 2,000,000명입니다." + CHECKLIST, ["1194006"]))
    assert summary["status"] == "needs_review" and summary["unsupported_numbers"]
