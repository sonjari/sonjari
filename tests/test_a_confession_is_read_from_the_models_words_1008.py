"""자백은 모델의 글에서만 읽는다 — 우리가 붙인 경고는 읽지 않는다 (2026-10-08 전수조사 4-1).

판 끝에서 경고·대조표를 답에 붙인 **뒤에** 그 답을 「스스로 못 했다고 말했나」로 다시 읽고 있었다. 우리 문장
「N개 중 M개만 실제로 열어 읽었습니다. 나머지는 **확인하지 못했**으니 …」가 자백 꼴에 걸려, 바깥 AI 에는
「답 스스로 하지 못한 것이 있다고 밝혔습니다」가 갔다 — 답은 그런 말을 한 적이 없다.

운영 판 2,261개: 그 판정이 선 166판 중 64판은 모델의 글만으로는 서지 않았고, 29판이 그 한 문구였다.
이제 자백은 모델의 글로만 보고, 우리가 걸음 기록으로 센 미달은 제 이름(`harness_shortfall`)으로 따로 적는다.
"""
from __future__ import annotations

import inspect
from typing import Any

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import (
    _ADMITS_NOT_DONE,
    _COMMIT_UNCONFIRMED_MARK,
    _READ_SHORT_MARK,
    BrowserAgent,
)
from alture_jarvis.delegation import summarize_job

_FOUR = "두 곳에서 공고를 최소 4개는 직접 열어 읽고 예산·기간을 표로 정리해줘"
_FOUR_EN = "Open and read at least 4 postings on the two sites and put budget and duration in a table"


def _read(url: str) -> dict[str, Any]:
    return {"tool": "browser_extract", "ok": True, "error": "", "status": "", "arguments": {}, "evidence": {"url": url}}


_TWO_READ = [_read("https://jobs.example/project/1"), _read("https://jobs.example/project/2")]


def test_our_own_warning_is_shaped_like_a_confession() -> None:
    """이것이 함정이었다 — 그래서 붙인 뒤의 글로 자백을 판정하면 안 된다."""
    note = BrowserAgent._goal_shortfall_check(_FOUR, _TWO_READ)
    assert "4개 중 2개" in note
    assert _ADMITS_NOT_DONE.search(note)


def test_the_read_count_warning_is_known_by_its_own_name_in_both_languages() -> None:
    assert _READ_SHORT_MARK.search(BrowserAgent._goal_shortfall_check(_FOUR, _TWO_READ))
    english = BrowserAgent._goal_shortfall_check(_FOUR_EN, _TWO_READ)
    assert english and _READ_SHORT_MARK.search(english)


def test_the_harder_warning_makes_no_new_partial() -> None:
    """「하나도 안 읽음」은 예전에도 판을 「일부」로 만들지 않았다 — 이번 고침이 새 「일부」를 만들지 않는다."""
    none_read = BrowserAgent._goal_shortfall_check(_FOUR, [])
    assert none_read and not _READ_SHORT_MARK.search(none_read)
    assert not _READ_SHORT_MARK.search("")


def test_the_unconfirmed_commit_mark_is_tied_to_the_real_sentence() -> None:
    source = inspect.getsource(BrowserAgent._commit_reality_check)
    assert _COMMIT_UNCONFIRMED_MARK.search(source)
    assert not _COMMIT_UNCONFIRMED_MARK.search("⚠ 아직 실제로 실행되지 않았습니다. 준비 단계까지만 끝났고")


def test_the_verdict_reads_the_models_words_not_the_answer_with_our_tail() -> None:
    source = inspect.getsource(agent_module)
    assert "_ADMITS_NOT_DONE.search(own_words)" in source
    assert "_answer_reports_shortfall(own_words, final_plan_results)" in source
    assert "_ADMITS_NOT_DONE.search(answer)" not in source


def _job(harness_shortfall: str) -> dict[str, Any]:
    return {
        "id": "job-1",
        "status": "completed",
        "result": {
            "answer": "표로 정리했습니다.",
            "completion_state": "partial",
            "agent_trace": {
                "steps": [dict(step) for step in _TWO_READ],
                "verification": {
                    "plan": {"items": [{"kind": "count", "label": "4개 이상 직접 열어 읽기", "met": True, "saw": "답에 4개"}]},
                    "reported_shortfall": False,
                    "harness_shortfall": harness_shortfall,
                },
            },
        },
    }


def test_the_host_is_told_who_counted() -> None:
    why = (summarize_job(_job("read_count")).get("resume") or {}).get("why_partial") or []
    assert any("손자리가 센" in item for item in why)
    assert not any("답 스스로" in item for item in why)


def test_an_unconfirmed_commit_is_told_as_ours_too() -> None:
    why = (summarize_job(_job("commit_unconfirmed")).get("resume") or {}).get("why_partial") or []
    assert any("확인하지 못했습니다" in item and "손자리가" in item for item in why)
