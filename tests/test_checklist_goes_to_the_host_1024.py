"""「시킨 것 대조」 덩어리는 바깥 AI 에게만 — 창에는 한 줄이거나 아무것도 (2026-10-24 · 전략안 §55-44).

판 끝에 하네스가 붙이는 대조표(「시킨 것 대조」 · 「Checklist」)와 「읽었나」 경고가 손자리 창에도, 바깥 AI(MCP)에게 가는 결과에도
똑같이 들어갔다. 창에서 읽는 사람에게 덩어리가 너무 컸다.

- 바깥 AI 가 맡긴 판: 창에 남는 답에는 덩어리가 없다. 바깥 AI 는 지금까지와 같은 글을 받는다 — 옛 MCP 연결 프로세스도
  백엔드의 토큰 없는 일 조회 문(`outbound.outbound_job_view`)으로 읽으니 같다.
- 사람이 시킨 판(창 · 디스코드): 덩어리 대신 한 줄. 다 했으면 아무것도.
- 판 기록: 둘 다 남는다(`answer` · `host_answer` · `verification.checks_line`).

시험은 행동으로 쓴다 — 실제 판(가짜 모델)을 돌리고, 칠해진 글 · 저장된 대화 · 바깥으로 나가는 사본을 본다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import test_forced_commit as base
from alture_jarvis import check_notes
from alture_jarvis import plan as P
from alture_jarvis.agent import AgentRunResult, BrowserAgent
from alture_jarvis.api import create_app
from alture_jarvis.delegation import summarize_job
from alture_jarvis.jobs import JobStatus, JobStore
from alture_jarvis.memory import without_our_tail
from alture_jarvis.outbound import outbound_job_view

from test_api import _config

#: 스위치를 끄면 이 판은 「3개 이상 직접 열어 읽기」를 못 채워 대조표가 붙는다(`test_requirement_grades_1024` 의 짝 판).
_PROMPT = "네이버 블로그에 '점검' 이라는 제목으로 세 줄 쓰고 임시저장까지 해줘. 발행은 하지 마. 어제 글 3개를 읽었는데 반응이 좋더라."


def _agent_run(tmp_path: Path, origin: str):
    config = base._Config(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = base._EventBus()
    painted: list[str] = []
    events.add_listener(lambda record: painted.append(str(record.payload.get("delta") or ""))
                        if record.event == "agent_answer_delta" else None)
    runner = BrowserAgent(config, base._StopsAfterPreparing(), base._RecordingGateway(), base._FakeBrowser(), base._FakeTools(), store, events)
    job = store.create_job("chat", "agent", {"prompt": _PROMPT})
    store.claim_next()
    return runner.run(_PROMPT, job_id=job["id"], origin=origin), "".join(painted)


@pytest.mark.parametrize("origin", ["chat", "mcp"])
def test_the_run_keeps_the_block_but_paints_the_window_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    monkeypatch.setattr(P, "GRADE_REQUIREMENTS", False)
    result, painted = _agent_run(tmp_path, origin)
    assert result.verification["completion_state"] == "partial"
    # 판이 돌려주는 답에는 덩어리가 표로 감싸여 그대로 있다 — 지금까지 바깥 AI 가 받던 글과 같다.
    full = check_notes.full(result.answer)
    assert "**시킨 것 대조**" in full and "❌ 3개 이상 직접 열어 읽기" in full
    line = result.verification["checks_line"]
    assert line.startswith("시킨 것 ") and "못 한 것: 3개 이상 직접 열어 읽기" in line
    # 창에 칠해지는 글에는 덩어리가 없다. 사람이 시킨 판은 한 줄, 바깥 AI 가 맡긴 판은 아무것도.
    assert painted and "시킨 것 대조" not in painted
    assert check_notes.OPEN not in painted and check_notes.CLOSE not in painted
    assert (line in painted) is (origin != "mcp")


def test_a_run_with_everything_done_gets_no_line(tmp_path: Path) -> None:
    result, painted = _agent_run(tmp_path, "chat")  # 등급을 켠 채 — 헛 요구가 흐림이라 다 채운 판
    assert result.verification["completion_state"] == "complete"
    assert result.verification["checks_line"] == ""
    assert "시킨 것" not in painted


# ── 판이 끝나는 한 자리(runtime)와 바깥으로 나가는 사본 ────────────────────────────────────

_BODY = "임시저장했습니다. 제목은 '점검'입니다."
_BLOCK = ("\n\n⚠ **화면 목록에서 옮겨 적은 이름이 있습니다: OpenScreen** — 그 페이지를 열어 읽지는 않았습니다."
          "\n\n**시킨 것 대조**\n- ✅ 실제 산출물 파일 만들기 — 1개\n- ❌ 3개 이상 직접 열어 읽기 — 1개 실제로 읽음")
_LINE = "시킨 것 2개 중 1개 ✓ · 못 한 것: 3개 이상 직접 열어 읽기"


def _finished_job(tmp_path: Path, origin: str, caller: str = ""):
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    runtime._learn_facts = lambda *_a, **_k: None
    runtime.agent.run = lambda *_a, **_k: AgentRunResult(
        answer=_BODY + check_notes.wrap(_BLOCK), steps=[{"tool": "browser_open", "ok": True}],
        verification={"completion_state": "partial", "checks_line": _LINE}, plan={},
        contract={"version": "task-contract-shadow-v1", "clauses": []},
    )
    payload = {"prompt": "블로그 임시저장", "session_id": f"s-{origin}-{caller}", "origin": origin, "agent_mode": "browser",
               **({"caller": caller} if caller else {})}
    job = runtime.enqueue("chat", "일", payload)
    result = runtime._chat_job(runtime.store.get_job(job["id"]))
    runtime.store.set_status(job["id"], JobStatus.COMPLETED, result=result)
    window = [row["content"] for row in runtime.memory.recent(payload["session_id"]) if row["role"] == "assistant"]
    return runtime.store.get_job(job["id"]), window[-1]


def test_a_host_task_leaves_the_window_clean_and_the_host_gets_everything(tmp_path: Path) -> None:
    job, window = _finished_job(tmp_path, "mcp", "claude-code")
    assert window.strip() == _BODY  # 창(대화 기록)에는 덩어리도 한 줄도 없다
    assert job["result"]["answer"].strip() == _BODY
    assert job["result"]["host_answer"] == _BODY + _BLOCK  # 판 기록에는 다 남는다 — 지금까지의 답과 글자까지 같다
    # 옛 MCP 연결 프로세스가 읽는 문: 토큰 없는 일 조회의 사본 → 그 사본의 `answer` 를 그대로 쓴다.
    outside = outbound_job_view(job)
    assert outside["result"]["answer"] == _BODY + _BLOCK
    assert "host_answer" not in outside["result"]
    summary = summarize_job(outside)
    assert "**시킨 것 대조**" in summary["answer"] and "화면 목록에서 옮겨 적은 이름" in summary["answer"]
    # 기록을 바로 읽는 셈(영수증)도 바깥 AI 가 받은 글로 센다.
    assert "**시킨 것 대조**" in summarize_job(job)["answer"]


@pytest.mark.parametrize(("origin", "caller"), [("workspace", ""), ("chat", ""), ("mcp", "Discord")])
def test_a_person_sees_one_line_in_place_of_the_block(tmp_path: Path, origin: str, caller: str) -> None:
    job, window = _finished_job(tmp_path, origin, caller)
    assert "시킨 것 대조" not in window and "화면 목록에서 옮겨 적은 이름" not in window
    assert window.rstrip().endswith(_LINE)
    assert job["result"]["host_answer"] == _BODY + _BLOCK
    # 다음 턴에 모델에게 갈 때는 그 한 줄도 우리 꼬리로 뗀다.
    assert without_our_tail(window).strip() == _BODY
    if caller == "Discord":
        # 디스코드 다리도 토큰 없는 문으로 읽는다 — 사람이 폰으로 시킨 판이라 창과 같은 한 줄을 받는다.
        summary = summarize_job(outbound_job_view(job))
        assert "시킨 것 대조" not in summary["answer"] and _LINE in summary["answer"]
        # 그 줄의 「2개 중 1개」는 하네스가 센 것이다 — 「도구가 준 적 없는 숫자」로 세지 않는다.
        assert summary["unsupported_numbers"] == []


def test_english_line_and_the_block_marks_never_leak() -> None:
    req = P.Requirement("count", "3개 이상 직접 열어 읽기", 3)
    line = P.summary_line([(req, False, "1개 실제로 읽음"), (P.Requirement("artifact", "실제 산출물 파일 만들기", ()), True, "1개")], "en")
    assert line == "Requested 2 · done 1 ✓ · not done: Open and read at least 3 yourself"
    assert P.summary_line([(req, True, "3개")], "en") == ""
    text = "답" + check_notes.wrap("\n\n**Checklist**\n- ❌ x") + "\n\n만든 파일:\n- `a.xlsx`"
    assert check_notes.screen(text, line) == "답\n\n" + line + "\n\n만든 파일:\n- `a.xlsx`"
    assert check_notes.screen(text) == "답\n\n만든 파일:\n- `a.xlsx`"
    assert check_notes.full(text) == "답\n\n**Checklist**\n- ❌ x\n\n만든 파일:\n- `a.xlsx`"
