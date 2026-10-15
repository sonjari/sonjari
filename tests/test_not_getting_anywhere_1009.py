"""맡긴 코드 판은 시간이 아니라 「나아가는가」로 접는다 (2026-10-09).

대표: 「저렇게 어려운 과제를 22분 만에 제한을 걸어 두는 것도 이상하지 않나 — 회귀 한 번에도 물리적인 시간이 든다」.
시간은 일한 양이 아니라 기다린 양까지 센다. 접는 기준을 「무엇을 되풀이하는가」로 옮긴다 — 확인 명령을 받은 판에 먼저.
눈금(4 · 5 · 20)은 운영 코드 판 520개에 대 본 값이다(`agent.not_getting_anywhere` 의 설명).
"""
from __future__ import annotations

import inspect
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alture_jarvis.agent import (
    BrowserAgent,
    _DELEGATED_STEPS_BACKSTOP,
    _IDLE_STEPS_LIMIT,
    _REWRITES_WITHOUT_RUN_LIMIT,
    _SAME_FAILURE_LIMIT,
    _code_budget_head,
    not_getting_anywhere,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.delegation import summarize_job
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

_CHECK = "python -m pytest -q tests/test_value.py"


# ── 판정 ─────────────────────────────────────────────────────────────────────


def _failed(fingerprint: str = "AssertionError@test_value") -> dict:
    return {"tool": "local_run_project_command", "ok": True, "arguments": {"command": _CHECK},
            "evidence": {"verified": False, "failure_fingerprint": fingerprint}}


def _passed() -> dict:
    return {"tool": "local_run_project_command", "ok": True, "arguments": {"command": _CHECK}, "evidence": {"verified": True}}


def _edit(path: str = "a.py") -> dict:
    return {"tool": "local_apply_edit", "ok": True, "arguments": {"path": path}}


def _write(path: str = "a.py", *, ok: bool = True) -> dict:
    return {"tool": "local_write_file", "ok": ok, "arguments": {"path": path}}


def _read(path: str, start: int = 1) -> dict:
    return {"tool": "local_read_text_file", "ok": True, "arguments": {"path": path, "line_start": start}}


def test_the_same_failure_in_a_row_is_standing_still_whatever_was_edited_between() -> None:
    steps: list[dict] = []
    for _ in range(_SAME_FAILURE_LIMIT - 1):
        steps += [_edit(), _failed()]
    assert not_getting_anywhere(steps) == "", "한 번 모자라면 아직이다"
    steps += [_edit(), _failed()]
    assert not_getting_anywhere(steps) == "same_failure"


def test_a_different_failure_or_a_pass_means_it_moved() -> None:
    same = [_failed()] * (_SAME_FAILURE_LIMIT - 1)
    assert not_getting_anywhere([*same, _failed("ImportError@conftest")]) == "", "실패가 바뀌었다 — 나아간 것이다"
    assert not_getting_anywhere([*same, _passed(), _failed()]) == "", "통과가 끼면 거기서 끊는다"
    assert not_getting_anywhere([_failed(), _failed(), _passed()]) == ""


def test_rewriting_one_file_whole_without_ever_running_it() -> None:
    steps = [_write()] * _REWRITES_WITHOUT_RUN_LIMIT
    assert not_getting_anywhere(steps) == "rewriting"
    assert not_getting_anywhere(steps[:-1]) == ""
    # 경로 표기가 달라도 같은 파일이다.
    mixed = [_write("src/A.py"), _write("src\\a.py")] * 3
    assert not_getting_anywhere(mixed) == "rewriting"


def test_what_does_not_count_as_rewriting() -> None:
    limit = _REWRITES_WITHOUT_RUN_LIMIT
    # 돌려 보면 다시 센다.
    assert not_getting_anywhere([*[_write()] * (limit - 1), _failed("a"), _write()]) == ""
    # 부분 고치기는 안 센다 — 큰 파일을 여러 군데 고치는 정상 판이 같은 파일을 열 번도 고친다.
    assert not_getting_anywhere([_edit()] * (limit * 3)) == ""
    # 서로 다른 파일을 새로 쓰는 것은 만드는 중이다.
    assert not_getting_anywhere([_write(f"f{index}.py") for index in range(limit * 2)]) == ""
    # 실패한 쓰기는 다시 쓴 것이 아니다.
    assert not_getting_anywhere([_write(ok=False)] * (limit * 2)) == ""


def test_twenty_steps_with_nothing_new_nothing_changed_nothing_run() -> None:
    first = [_read("a.py"), _read("b.py"), _edit()]
    again = [_read("a.py"), _read("b.py")] * (_IDLE_STEPS_LIMIT // 2)
    assert len(again) == _IDLE_STEPS_LIMIT
    assert not_getting_anywhere([*first, *again]) == "nothing_new"


def test_one_new_look_or_one_change_or_one_run_inside_the_window_is_progress() -> None:
    first = [_read("a.py"), _read("b.py"), _edit()]
    again = [_read("a.py"), _read("b.py")] * (_IDLE_STEPS_LIMIT // 2)
    assert not_getting_anywhere([*first, *again[:-1], _read("c.py")]) == "", "처음 보는 파일"
    assert not_getting_anywhere([*first, *again[:-1], _read("a.py", 400)]) == "", "같은 파일의 다른 자리"
    assert not_getting_anywhere([*first, *again[:-1], _edit()]) == ""
    assert not_getting_anywhere([*first, *again[:-1], _failed("x")]) == ""
    # 탐색 — 서로 다른 곳 서른 군데를 읽는 것은 제자리가 아니다(그 밤의 숙제 2 가 37군데를 읽었다).
    assert not_getting_anywhere([_read(f"f{index}.py") for index in range(30)]) == ""


def test_a_short_job_is_never_called_idle() -> None:
    assert not_getting_anywhere([_read("a.py")] * (_IDLE_STEPS_LIMIT - 1)) == ""
    assert not_getting_anywhere([]) == ""


# ── 머리말 ────────────────────────────────────────────────────────────────────


def test_the_head_names_the_reason_and_does_not_offer_to_continue() -> None:
    stop = {"why": "same_failure", "steps": 41, "elapsed_sec": 1900}
    head = _code_budget_head(stop, ["C:/w/a.py"])
    assert "같은 확인 실패가 되풀이돼" in head and "41걸음" in head and "a.py" in head
    assert "확인 명령을 통과하지 못했습니다" in head
    assert "이어서 해줘" not in head, "같은 자리에서 다시 돌 뿐이다 — 무엇을 할지는 맡긴 쪽이 정한다"
    assert "작업 시간" not in head
    english = _code_budget_head({**stop, "why": "rewriting"}, [], english=True)
    assert "rewriting the same file" in english and "continue" not in english
    # 시간으로 접힌 판(사람이 시킨 판)의 글은 그대로다.
    assert "작업 시간" in _code_budget_head({"why": "time", "elapsed_sec": 1200}, [])
    assert "작업 시간" in _code_budget_head({"elapsed_sec": 1200}, []), "옛 기록(why 없음)도 그대로 읽힌다"


# ── 실제 판 ───────────────────────────────────────────────────────────────────

_TOOL_NAMES = {"local_read_text_file", "local_grep", "local_write_file", "local_apply_edit", "local_delete_file", "local_run_project_command"}


class _Tools:
    names = set(_TOOL_NAMES)
    ollama_tools = [
        {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}}}
        for name in sorted(_TOOL_NAMES)
    ]

    def authorize_code_workspace(self, job_id, root):  # noqa: ANN001, ANN201
        assert job_id and root


class _Gateway:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.checks = 0

    def execute(self, name, arguments, *, job_id=""):  # noqa: ANN001, ANN201
        target = self.root / "value.py"
        if name == "local_write_file":
            target.write_text(str(arguments.get("content") or ""), encoding="utf-8")
            return ToolResult(True, name, result={"action": name, "path": str(target), "verified": True, "created": True})
        if name == "local_run_project_command":
            self.checks += 1
            passed = target.is_file() and "fixed" in target.read_text(encoding="utf-8")
            return ToolResult(True, name, result={
                "action": name, "command": arguments.get("command"), "exit_code": 0 if passed else 1,
                "stdout": "1 passed" if passed else "1 failed", "verified": passed,
            })
        return ToolResult(True, name, result={"action": name, "text": "x"})


def _agent(tmp_path: Path, model, **config: Any) -> tuple[BrowserAgent, JobStore, _Gateway]:  # noqa: ANN001
    settings = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False, **config,
    )
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _Gateway(tmp_path)
    browser = SimpleNamespace(status=lambda: {"started": True})
    return BrowserAgent(settings, model, gateway, browser, _Tools(), store, EventBus()), store, gateway


def _call(name: str, **arguments: Any) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def _run(agent: BrowserAgent, store: JobStore, tmp_path: Path, **extra: Any):  # noqa: ANN201
    job = store.create_job("chat", "맡긴 일", {"prompt": "value.py 의 값을 고쳐줘"})
    store.claim_next()
    return agent.run(
        "value.py 의 값을 고쳐줘", job_id=job["id"], origin="mcp", model_role="code", code_mode=True,
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True, **extra,
    )


class _RewritesForever:
    """돌려 보지 않고 같은 파일을 통째로 다시 쓰기만 한다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if kwargs.get("tools") is None and self.calls > _REWRITES_WITHOUT_RUN_LIMIT:
            return {"role": "assistant", "content": "value.py 를 여러 번 고쳤지만 확인 명령은 통과하지 못했습니다."}
        return _call("local_write_file", path="value.py", content=f"VALUE = 'broken{self.calls}'\n")


def test_a_delegated_job_that_only_rewrites_is_folded_with_the_reason(tmp_path: Path) -> None:
    model = _RewritesForever()
    agent, store, _ = _agent(tmp_path, model)

    result = _run(agent, store, tmp_path, declared_check=_CHECK)

    writes = [step for step in result.steps if step.get("tool") == "local_write_file"]
    assert len(writes) == _REWRITES_WITHOUT_RUN_LIMIT, "다섯 번째 다시 쓰기 뒤에 접는다 — 더 돌지 않는다"
    assert result.verification["stop_reason"] == "wrapped_up:code_not_progressing"
    folded = result.verification["code_budget_exhausted"]
    assert folded["why"] == "rewriting" and folded["budget_sec"] == 0 and folded["verified"] is False
    assert result.verification["completion_state"] == "partial"
    assert result.verification["declared_check"]["passed"] is False
    assert result.answer.startswith("⚠ **같은 파일을 돌려 보지 않고 거듭 다시 써서 멈췄습니다")


class _SlowButFixes:
    """오래 걸리지만 나아간다 — 틀리게 쓰고, 한참 뒤에 고친다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if self.calls == 1:
            return _call("local_write_file", path="value.py", content="VALUE = 'broken'\n")
        if self.calls == 2:
            time.sleep(1.2)  # 정해 둔 시간(1초)을 넘긴다
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
        return {"role": "assistant", "content": "고쳤습니다."}


def test_a_delegated_job_is_not_folded_by_time(tmp_path: Path) -> None:
    agent, store, _ = _agent(tmp_path, _SlowButFixes(), code_job_stall_sec=1)
    result = _run(agent, store, tmp_path, declared_check=_CHECK)
    assert result.verification["code_budget_exhausted"] is None, "시간을 넘겼어도 일하는 판은 끝까지 간다"
    assert result.verification["declared_check"]["passed"] is True
    assert result.verification["completion_state"] == "complete"


def test_a_job_a_person_started_still_folds_by_time(tmp_path: Path) -> None:
    """사람이 직접 시킨 판은 아직 그대로다 — 사람은 화면 앞에서 기다린다. 따로 재 보고 옮긴다."""
    agent, store, _ = _agent(tmp_path, _SlowButFixes(), code_job_stall_sec=1)
    result = _run(agent, store, tmp_path)
    folded = result.verification["code_budget_exhausted"]
    assert folded and folded["why"] == "time" and folded["budget_sec"] == 1
    assert result.verification["stop_reason"] == "wrapped_up:code_budget_exhausted"
    assert "작업 시간" in result.answer


def test_the_step_backstop_is_wired_and_far_above_real_jobs() -> None:
    source = inspect.getsource(BrowserAgent.run)
    assert '"step_backstop" if len(steps) >= _DELEGATED_STEPS_BACKSTOP else ""' in source
    assert "and not declared_check.strip()\n                and stall_sec > 0" in source, "시간 접기는 확인 명령이 없는 판에만"
    assert _DELEGATED_STEPS_BACKSTOP >= 130, "운영에서 제대로 끝난 코드 판의 최대는 65걸음이었다 — 그 두 배는 넘겨 둔다"


# ── 맡긴 쪽이 받는 글 ──────────────────────────────────────────────────────────


def _job(why: str) -> dict:
    return {"id": "j1", "status": "completed", "payload": {"prompt": "고쳐줘"}, "result": {
        "answer": "여러 번 고쳤지만 통과하지 못했습니다.", "completion_state": "partial",
        "agent_trace": {"steps": [{"tool": "local_write_file", "ok": True, "arguments": {}}],
                        "verification": {"code_budget_exhausted": {"why": why, "steps": 40}}},
        "delegated": {"repo": "r", "branch": "sonjari/task-3", "worktree": "w", "base": "b",
                      "changed": [{"status": "M", "path": "a.py"}], "changed_count": 1, "stat": "",
                      "check": {"command": _CHECK, "passed": False, "runs_by_harness": 4}, "take_home": {}},
    }}


def test_the_caller_is_told_why_it_stopped_and_what_to_do_instead() -> None:
    summary = summarize_job(_job("same_failure"))
    assert summary["branch"]["stopped_because"] == "same_failure"
    assert any("그대로 다시 맡기면 같은 자리에서 멈춥니다" in note for note in summary["review_notes"])
    assert any("쪼개" in note for note in summarize_job(_job("rewriting"))["review_notes"])


def test_a_time_fold_or_an_unknown_reason_adds_nothing() -> None:
    for why in ("time", "", "something_else"):
        summary = summarize_job(_job(why))
        assert "stopped_because" not in summary["branch"]
