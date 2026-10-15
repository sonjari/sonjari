"""실패한 위임 작업도 **실패하기 전까지 한 일**을 호스트에게 돌려준다 (2026-09-22, 사장님 승인).

## 어떻게 찾았나

노트북 4B 사다리(`pat3`)에서 잡 상태가 `failed` 인 판 4개 중 **3개는 만든 파일이 채점을 통과했다.**
실패한 잡의 요약은 상태와 오류 500자뿐이었다 — 만든 파일도, 읽은 주소도, 검증을 했는지도, 왜 멈췄는지도 안 실렸다.
큰 플랫폼이 온텔릭에게 일을 맡겼다가 「실패」만 받으면 쓸 만한 결과를 버리고 처음부터 다시 한다 —
위임의 값(호스트 토큰을 아끼는 것)이 실패하는 순간 0 이 된다. 조사(Cowork)에서 중간에 죽은 판도 같다.

## 지킬 것

1. 실패·취소 요약에도 만든 파일(`files`)·읽은 주소(`sources`)·이어갈 자리(`resume`)가 실린다.
2. **검증 못 한 결과를 검증된 것처럼 내보내지 않는다** — 이유를 말하고, 모델의 마지막 말은 `unverified_claim` 으로 격리한다.
3. 만든 뒤 **지운 파일**(검증용 임시 스크립트)은 산출물에서 뺀다.
4. 상태는 그대로 `failed`/`cancelled` 다 — 호스트의 오류 표시(`is_error`)가 유지된다.
5. 만들어 놓고 부르는 자리가 없으면 아무 일도 안 한다 — 실제 실패 기록 경로까지 이어서 확인한다.
"""

from __future__ import annotations

import inspect
from typing import Any

from alture_jarvis.delegation import STATUS_TOOL, partial_work, summarize_job


def _failed_job(**over: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "failed": True,
        "error": "coding_verification_missing",
        "agent_trace": {"steps": [
            {"step": 1, "tool": "local_index_codebase", "ok": True, "error": ""},
            {"step": 2, "tool": "local_write_file", "ok": True, "error": ""},
            {"step": 3, "tool": "local_run_project_command", "ok": False,
             "error": "command_argument_blocked — 인자 `&&` 에 셸 문자가 있다"},
        ]},
        "partial": {"files": ["index.html"], "sources": []},
        "diagnosis": {"coding_pushbacks": 2, "verified": False, "mutated": True,
                      "final_answer": "✅ 완료했습니다. index.html 이 만들어졌습니다."},
    }
    result.update(over.pop("result", {}))
    job: dict[str, Any] = {
        "id": "j9", "status": "failed", "error": "coding_verification_missing",
        "payload": {"code_workspace": "C:/Users/u/ws"}, "result": result,
    }
    job.update(over)
    return job


def test_a_failed_job_still_reports_the_files_it_made() -> None:
    summary = summarize_job(_failed_job())

    assert summary["status"] == "failed"  # 상태는 그대로 — 호스트의 오류 표시가 유지된다
    assert summary["error"] == "coding_verification_missing"
    assert summary["files"] == ["index.html"]
    assert summary["workspace"] == "C:/Users/u/ws"  # 상대 경로가 어디 기준인지
    assert summary["stopped"] == {"verified": False, "mutated": True, "coding_pushbacks": 2}


def test_the_message_says_the_files_were_not_verified() -> None:
    message = summarize_job(_failed_job())["message"]

    assert "검증" in message and "검증되지 않은" in message


def test_the_models_last_words_are_quarantined_not_presented_as_the_result() -> None:
    """검증에 실패한 판의 마지막 말은 「완료했습니다」다 — 그대로 결과로 내보내면 안 된다."""
    summary = summarize_job(_failed_job())

    assert "answer" not in summary  # 답 칸에 실리지 않는다
    assert "완료했습니다" in summary["unverified_claim"]
    assert "사실로 전하지 마세요" in summary["message"]


def test_the_claim_is_clipped() -> None:
    long_claim = "완료했습니다. " * 500
    summary = summarize_job(_failed_job(result={"diagnosis": {"final_answer": long_claim, "verified": False}}))

    assert len(summary["unverified_claim"]) <= 601


def test_a_failure_without_files_does_not_pretend_there_is_work() -> None:
    summary = summarize_job(_failed_job(result={"partial": {"files": [], "sources": []}}))

    assert "files" not in summary and "workspace" not in summary
    assert "만든 파일 없음" in summary["message"]


def test_resume_shows_what_was_done_and_where_it_was_blocked() -> None:
    resume = summarize_job(_failed_job())["resume"]

    assert "local_write_file ×1" in resume["did"]
    assert resume["files"] == ["index.html"]
    assert "command_argument_blocked" in resume["blocked"]


def test_a_research_job_that_died_keeps_the_pages_it_had_read() -> None:
    job = _failed_job(
        error="browser_stuck",
        result={"error": "browser_stuck", "diagnosis": {},
                "partial": {"files": [], "sources": ["https://www.saramin.co.kr/a", "https://www.saramin.co.kr/b"]}},
    )
    summary = summarize_job(job)

    assert summary["status"] == "failed"
    assert summary["sources"] == ["https://www.saramin.co.kr/a", "https://www.saramin.co.kr/b"]
    assert "files·sources" in summary["message"]
    assert "unverified_claim" not in summary  # 검증 문제가 아니면 안 만든다


def test_an_expired_approval_tells_the_host_to_look_at_the_window() -> None:
    summary = summarize_job({"id": "j", "status": "cancelled", "error": "approval_expired", "result": None})

    assert summary["status"] == "cancelled"
    assert "승인" in summary["message"]


def test_an_empty_failure_is_still_a_plain_failure() -> None:
    summary = summarize_job({"id": "j", "status": "failed", "error": "boom", "result": None})

    assert summary["status"] == "failed" and summary["error"] == "boom"
    assert "files" not in summary and "unverified_claim" not in summary


def test_the_status_tool_tells_the_host_not_to_throw_away_a_failed_jobs_work() -> None:
    assert "unverified_claim" in STATUS_TOOL["description"]
    assert "failed" in STATUS_TOOL["description"]


# --- 걸음 기록에서 복원 -----------------------------------------------------

def _steps() -> list[dict[str, Any]]:
    return [
        {"step": 1, "tool": "local_write_file", "ok": True},
        {"step": 2, "tool": "local_write_file", "ok": True},          # 검증용 임시 스크립트
        {"step": 3, "tool": "local_delete_file", "ok": True},         # …지웠다
        {"step": 4, "tool": "local_apply_edit", "ok": False},         # 실패한 편집은 산출물이 아니다
        {"step": 5, "tool": "browser_open", "ok": True},
        {"step": 6, "tool": "local_read_text_file", "ok": True},      # 읽기는 산출물이 아니다
    ]


_FULL = {
    1: {"arguments": {"path": "index.html"}},
    2: {"arguments": {"path": "verify.py"}},
    3: {"arguments": {"path": "verify.py"}},
    4: {"arguments": {"path": "app.py"}},
    5: {"arguments": {"url": "https://example.com/a"}, "payload": {"url": "https://example.com/final"}},
    6: {"arguments": {"path": "README.md"}},
}


def test_partial_work_lists_kept_files_and_read_pages_only() -> None:
    work = partial_work(lambda number: _FULL.get(number), _steps())

    assert work["files"] == ["index.html"]  # verify.py 는 지웠고 app.py 편집은 실패했다
    assert work["sources"] == ["https://example.com/final"]  # 실제 도착한 주소가 우선


def test_partial_work_survives_a_step_that_cannot_be_read() -> None:
    def flaky(number: int) -> dict[str, Any] | None:
        if number == 1:
            raise KeyError(number)
        return _FULL.get(number)

    work = partial_work(flaky, _steps())

    assert "index.html" not in work["files"]  # 못 읽은 걸음만 빠진다
    assert work["sources"] == ["https://example.com/final"]  # 나머지는 복원된다


# --- 실제 실패 기록 경로 -----------------------------------------------------

def test_the_failure_trace_stores_the_partial_work_in_the_job_result() -> None:
    """복원 함수만 있고 실패 기록이 안 부르면 아무 일도 안 일어난다(이 저장소가 여섯 번 겪은 모양)."""
    from alture_jarvis.runtime import JarvisRuntime

    class _Observations:
        def list_steps(self, job_id: str) -> list[dict[str, Any]]:
            return _steps()

        def get(self, job_id: str, number: int) -> dict[str, Any] | None:
            return _FULL.get(number)

    class _Store:
        saved: dict[str, Any] = {}

        def attach_result(self, job_id: str, result: dict[str, Any]) -> None:
            self.saved = result

    class _Fake:
        observations = _Observations()
        store = _Store()

    error = RuntimeError("coding_verification_missing")
    error.diagnosis = {"coding_pushbacks": 2, "verified": False, "mutated": True}  # type: ignore[attr-defined]
    JarvisRuntime._attach_failure_trace(_Fake(), {"id": "j1"}, error)  # type: ignore[arg-type]

    saved = _Fake.store.saved
    assert saved["partial"]["files"] == ["index.html"]
    assert saved["diagnosis"]["verified"] is False
    # 그리고 그 기록이 그대로 호스트 요약이 된다.
    summary = summarize_job({"id": "j1", "status": "failed", "error": "coding_verification_missing", "result": saved})
    assert summary["files"] == ["index.html"]
    assert "검증되지 않은" in summary["message"]


def test_the_runtime_calls_the_restorer() -> None:
    from alture_jarvis.runtime import JarvisRuntime

    assert "partial_work(" in inspect.getsource(JarvisRuntime._attach_failure_trace)


def test_a_job_the_user_stopped_reports_its_files_as_unchecked() -> None:
    """사람이 멈춘 판(2026-09-30 e7dd3831) — 41걸음·엑셀 1개를 만들었는데 `steps: 0`·파일 없음으로 돌아갔다.

    멈춘 판도 파일·걸음을 돌려주되, 끝까지 검사하지 않았다는 것을 먼저 말한다(그 엑셀은 5행 중 1행만 원문과 맞았다).
    """
    job = _failed_job(status="cancelled", error="", result={
        "failed": False, "cancelled": True, "error": "", "diagnosis": {},
        "partial": {"files": [r"C:\Users\u\Documents\JARVIS\초기_마케팅_회고_5건.xlsx"], "sources": ["https://tiiny.host/blog/first-paying-users/"]},
    })
    job["payload"] = {}

    summary = summarize_job(job)

    assert summary["status"] == "cancelled"
    assert summary["files"] and summary["sources"]
    assert "끝까지 검사하지 않았습니다" in summary["message"]
    assert "실패했습니다" not in summary["message"]


def test_the_runtime_records_a_stopped_job_too() -> None:
    from alture_jarvis.runtime import JarvisRuntime

    guard = inspect.getsource(JarvisRuntime._guard_job)
    cancelled = guard[guard.index("except AgentCancelled"):guard.index("except Exception as exc")]

    assert "_attach_failure_trace(job, exc, cancelled=True)" in cancelled
