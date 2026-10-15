"""끝내지 못한 판(실패·멈춤)도 대화에 남는다 (2026-10-04 새벽).

운영 기록을 세어 보니 실패한 실제 판 84개·멈춘 판 129개 가운데 **대화에 남은 것이 0개**였다. 질문·답이 판이 끝날 때만
저장됐기 때문이다. 화면은 「이어서 해줘라고 보내면 이어갑니다」라고 하는데, 다음 판의 계획 층은 「이어서 해줘」를
**바로 앞 사람 말**에 붙여 읽는다(`plan.planning_prompt`) — 실패한 판의 질문이 없으니 그 전 질문에 붙었다.

여기서 지키는 것:
- 남기는 글은 모델이 쓰지 않는다. 걸음 기록에 있는 것만 적고, 만든 파일은 **검증되지 않았다**고 적는다.
- 상태는 안 바꾼다(실패는 실패다) — 대화에 남길 뿐이다.
- 남기다 실패해도 원래 실패를 덮지 않는다.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from alture_jarvis.delegation import unfinished_turn_note
from alture_jarvis.memory import ConversationMemory
from alture_jarvis.plan import planning_prompt
from alture_jarvis.runtime import JarvisRuntime


# --- 메모 한 줄 ---------------------------------------------------------------

def test_a_budget_stop_says_what_was_made_and_that_it_is_unverified() -> None:
    note = unfinished_turn_note(
        "code_budget_exhausted",
        cancelled=False,
        files=["index.html", "style.css"],
        sources=[],
        last_failure="local_run_project_command — exit 1",
    )

    assert note.startswith("(") and note.endswith(")")  # 다음 판의 모델이 「답이 아님」을 알게
    assert "작업 시간" in note and "검증은 통과하지 못했습니다" in note
    assert "index.html, style.css" in note and "검증되지 않음" in note
    assert "마지막으로 걸린 것: local_run_project_command — exit 1" in note
    assert "이어서 해줘" in note
    # 지어내지 않는다 — 끝났다·고쳤다는 말이 없다.
    assert "완료" not in note and "성공" not in note


def test_a_stopped_task_is_not_called_a_failure() -> None:
    note = unfinished_turn_note("", cancelled=True, files=[], sources=["https://a.example/1", "https://a.example/2"])

    assert "도중에 멈췄습니다" in note
    assert "읽은 주소 2곳" in note
    assert "마지막으로 걸린 것" not in note


def test_other_errors_do_not_leak_the_raw_error_name() -> None:
    timed = unfinished_turn_note("timed out", cancelled=False, files=[], sources=[])
    other = unfinished_turn_note("'NoneType' object has no attribute 'split'", cancelled=False, files=[], sources=[])

    assert "제한 시간" in timed
    assert "끝내지 못했습니다" in other and "NoneType" not in other


def test_many_files_are_folded() -> None:
    note = unfinished_turn_note("coding_verification_missing", cancelled=False, files=[f"f{i}.py" for i in range(9)], sources=[])

    assert "f5.py" in note and "f6.py" not in note
    assert "외 3개" in note


def test_an_english_request_gets_an_english_note() -> None:
    note = unfinished_turn_note("code_budget_exhausted", cancelled=False, files=["app.py"], sources=[], english=True)

    assert "not verified" in note and "app.py" in note
    assert 'Send "continue"' in note
    assert not any("가" <= ch <= "힣" for ch in note)


# --- 실제 대화 저장소까지 -------------------------------------------------------

class _Store:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    def get_job(self, job_id: str) -> dict[str, Any]:
        return {"id": job_id, "result": self._result}


def _fake(memory: ConversationMemory, result: dict[str, Any]) -> Any:
    class _Fake:
        pass

    fake = _Fake()
    fake.memory = memory
    fake.store = _Store(result)
    fake._session_id = lambda payload: str(payload.get("session_id") or "default")
    return fake


def _job(prompt: str, **extra: Any) -> dict[str, Any]:
    return {"id": "job-1", "kind": "chat", "payload": {"prompt": prompt, "session_id": "s1", **extra}}


def test_a_failed_turn_leaves_the_question_and_a_note(tmp_path: Path) -> None:
    memory = ConversationMemory(tmp_path / "m.db")
    result = {
        "partial": {"files": ["index.html"], "sources": []},
        "agent_trace": {"steps": [
            {"step": 1, "tool": "local_write_file", "ok": True, "error": ""},
            {"step": 2, "tool": "local_run_project_command", "ok": False, "error": "exit 1"},
        ]},
    }

    JarvisRuntime._record_unfinished_turn(
        _fake(memory, result), _job("가게 소개 페이지를 만들어줘"), RuntimeError("code_budget_exhausted")
    )

    rows = memory.recent("s1")
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[0]["content"] == "가게 소개 페이지를 만들어줘"
    assert rows[0]["metadata"]["job_id"] == "job-1"  # 화면이 작업 기록 상자를 이 질문 뒤에 붙인다
    assert "index.html" in rows[1]["content"] and "exit 1" in rows[1]["content"]
    assert rows[1]["metadata"]["unfinished"] == "failed"
    assert rows[1]["metadata"]["error"] == "code_budget_exhausted"


def test_the_next_turn_continues_the_failed_question(tmp_path: Path) -> None:
    """이 고침의 목적 — 「이어서 해줘」가 실패한 판의 질문에 붙는다(전에는 그 앞 질문에 붙었다)."""
    memory = ConversationMemory(tmp_path / "m.db")
    memory.add_exchange("s1", "오늘 서울 날씨 알려줘", "맑습니다.")
    JarvisRuntime._record_unfinished_turn(
        _fake(memory, {}), _job("사람인에서 마케팅 공고 3개 찾아 엑셀로 정리해줘"), RuntimeError("timed out")
    )

    joined = planning_prompt("이어서 해줘", memory.recent("s1"))

    assert "사람인" in joined and "날씨" not in joined


def test_a_stopped_turn_is_recorded_as_stopped(tmp_path: Path) -> None:
    memory = ConversationMemory(tmp_path / "m.db")

    JarvisRuntime._record_unfinished_turn(
        _fake(memory, {"partial": {"files": [], "sources": ["https://a.example"]}}),
        _job("레딧에서 후기 찾아줘"), RuntimeError("agent_cancelled"), cancelled=True,
    )

    rows = memory.recent("s1")
    assert rows[1]["metadata"]["unfinished"] == "cancelled"
    assert rows[1]["metadata"]["error"] == ""
    assert "agent_cancelled" not in rows[1]["content"]


def test_only_chat_turns_are_recorded_and_a_broken_store_does_not_raise(tmp_path: Path) -> None:
    memory = ConversationMemory(tmp_path / "m.db")
    fake = _fake(memory, {})

    JarvisRuntime._record_unfinished_turn(fake, {"id": "j", "kind": "schedule", "payload": {"prompt": "x", "session_id": "s1"}}, RuntimeError("e"))
    assert memory.recent("s1") == []

    fake.store = None  # 저장소가 망가져도 원래 실패를 덮지 않는다
    JarvisRuntime._record_unfinished_turn(fake, _job("질문"), RuntimeError("e"))


def test_the_instruction_the_model_got_is_kept_when_it_differs(tmp_path: Path) -> None:
    memory = ConversationMemory(tmp_path / "m.db")

    JarvisRuntime._record_unfinished_turn(
        _fake(memory, {}), _job("긴 인계문 …", display_prompt="이어받기: 보고서 마무리"), RuntimeError("timed out")
    )

    row = memory.recent("s1")[0]
    assert row["content"] == "이어받기: 보고서 마무리"
    assert row["metadata"]["model_prompt"] == "긴 인계문 …"


# --- 배선 ---------------------------------------------------------------------

def test_the_guard_records_both_failures_and_stops() -> None:
    guard = inspect.getsource(JarvisRuntime._guard_job)
    cancelled = guard[guard.index("except AgentCancelled"):guard.index("except Exception as exc")]
    failed = guard[guard.index("except Exception as exc"):]

    assert "_record_unfinished_turn(job, exc, cancelled=True)" in cancelled
    assert "_record_unfinished_turn(job, exc)" in failed
    # 기록(만든 파일 복원)이 먼저다 — 메모가 그 결과를 읽는다.
    assert failed.index("_attach_failure_trace(job, exc)") < failed.index("_record_unfinished_turn(job, exc)")
