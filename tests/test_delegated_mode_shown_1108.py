"""맡긴 판이 무슨 모드로 돌았는지 맡긴 쪽이 늘 본다 (2026-11-08 대표 「코드면 코드 · 코워크면 코워크」).
유니티 일을 repo 없이 던져 코워크로 돈 것을 던진 클로드도 몰랐다. 결과에 mode 칸 · 코드 일인데 repo 가 없으면 알림(막지 않음)."""
from __future__ import annotations

from typing import Any

from alture_jarvis.delegation import summarize_job


def _job(prompt: str, *, code: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"prompt": prompt}
    if code:
        payload.update({"workspace_mode": "code", "code_workspace": "/repo"})
    return {"id": "j1", "status": "completed", "payload": payload,
            "result": {"answer": "끝", "completion_state": "complete",
                       "agent_trace": {"steps": [], "tool_numbers": [], "tool_numbers_body": []}}}


def _notes(summary: dict[str, Any]) -> str:
    return " ".join(summary.get("review_notes") or [])


def test_every_result_says_its_mode() -> None:
    assert summarize_job(_job("공고 3개 엑셀로"))["mode"] == "cowork"
    assert summarize_job(_job("report.py 고쳐서 테스트 통과시켜", code=True))["mode"] == "code"


def test_code_work_without_repo_is_flagged_not_blocked() -> None:
    summary = summarize_job(_job("유니티 C# 스크립트로 포탑을 짜서 프로젝트에 넣어 줘"))
    assert "repo" in _notes(summary) and "git init" in _notes(summary)


def test_plain_cowork_and_code_jobs_get_no_mode_note() -> None:
    for summary in (summarize_job(_job("보고서 문장 좀 고쳐 줘")), summarize_job(_job("엑셀 표의 합계가 틀렸어 고쳐 줘")),
                    summarize_job(_job("report.py 고쳐서 테스트 통과시켜", code=True))):
        assert "코워크로 돌았습니다" not in _notes(summary)
