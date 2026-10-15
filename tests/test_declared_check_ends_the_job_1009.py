"""바깥 AI 가 코드 일을 맡기며 준 「확인 명령」이 끝을 가른다 (2026-10-09).

그 밤의 숙제에서 과제 글 속 예시 문장이 판을 읽기 전용으로 묶었고(hw3), 시험이 통과한 판이 「읽은 원문에 없는 이름」으로 partial 이
됐다(사다리 L7). 둘 다 요구를 글에서 읽어서 생긴 일이다. 맡기는 쪽이 「이 명령이 통과하면 끝」을 **칸으로** 주면, 하네스는 글을
읽지 않고 그 명령만 본다 — 답을 내려 할 때 직접 돌려서.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import BrowserAgent, _DECLARED_CHECK_RUNS
from alture_jarvis.code_runtime import declared_check_is_current
from alture_jarvis.config import JarvisConfig
from alture_jarvis.delegation import TASK_TOOL, summarize_job
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import ToolResult
from alture_jarvis.runtime import JarvisRuntime

_CHECK = "python -m pytest -q tests/test_value.py"


# ── 판정 ────────────────────────────────────────────────────────────────────────


def _ran(command: Any, *, verified: bool = True, ok: bool = True) -> dict:
    return {"tool": "local_run_project_command", "ok": ok, "arguments": {"command": command}, "evidence": {"verified": verified}}


def _edited() -> dict:
    return {"tool": "local_apply_edit", "ok": True, "arguments": {"path": "a.py"}}


def test_a_pass_after_the_last_change_is_current() -> None:
    assert declared_check_is_current([_edited(), _ran(_CHECK)], _CHECK) is True


def test_a_pass_before_a_later_change_is_not() -> None:
    assert declared_check_is_current([_ran(_CHECK), _edited()], _CHECK) is False


def test_a_failed_run_or_another_command_does_not_count() -> None:
    assert declared_check_is_current([_edited(), _ran(_CHECK, verified=False)], _CHECK) is False
    assert declared_check_is_current([_edited(), _ran("python -m pytest -q tests/other.py")], _CHECK) is False
    assert declared_check_is_current([], _CHECK) is False
    assert declared_check_is_current([_ran(_CHECK)], "") is False


def test_the_same_command_given_as_a_list_or_with_other_spacing_is_the_same() -> None:
    assert declared_check_is_current([_ran(_CHECK.split())], _CHECK) is True
    assert declared_check_is_current([_ran("python  -m pytest   -q tests/test_value.py")], _CHECK) is True


# ── 실제 판 ─────────────────────────────────────────────────────────────────────

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
    """파일에 `fixed` 가 있어야 확인 명령이 통과한다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.checks: list[dict] = []

    def execute(self, name, arguments, *, job_id=""):  # noqa: ANN001, ANN201
        target = self.root / "value.py"
        if name == "local_write_file":
            target.write_text(str(arguments.get("content") or ""), encoding="utf-8")
            return ToolResult(True, name, result={"action": name, "path": str(target), "verified": True, "created": True})
        if name == "local_run_project_command":
            self.checks.append(dict(arguments))
            passed = target.is_file() and "fixed" in target.read_text(encoding="utf-8")
            return ToolResult(True, name, result={
                "action": name, "command": arguments.get("command"), "exit_code": 0 if passed else 1,
                "stdout": "1 passed" if passed else "1 failed", "verified": passed,
            })
        return ToolResult(True, name, result={"action": name, "text": "x"})


def _agent(tmp_path: Path, model) -> tuple[BrowserAgent, JobStore, _Gateway]:  # noqa: ANN001
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False,
    )
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _Gateway(tmp_path)
    browser = SimpleNamespace(status=lambda: {"started": True})
    return BrowserAgent(config, model, gateway, browser, _Tools(), store, EventBus()), store, gateway


def _call(name: str, **arguments: Any) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def _say(text: str) -> dict:
    return {"role": "assistant", "content": text}


class _FixesWhenTheCheckFails:
    """처음엔 틀리게 쓰고 「끝났다」고 한다. 확인 명령이 떨어진 것을 보면 고친다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        last = str(messages[-1].get("content") or "")
        if self.calls == 1:
            return _call("local_write_file", path="value.py", content="VALUE = 'broken'\n")
        if "1 failed" in last:
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
        return _say("고쳤습니다.")


def _run(agent: BrowserAgent, store: JobStore, tmp_path: Path, prompt: str, **extra: Any):  # noqa: ANN201
    job = store.create_job("chat", "맡긴 일", {"prompt": prompt})
    store.claim_next()
    return agent.run(
        prompt, job_id=job["id"], origin="mcp", model_role="code", code_mode=True,
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True, **extra,
    )


def test_the_harness_runs_the_check_itself_and_the_job_ends_when_it_passes(tmp_path: Path) -> None:
    model = _FixesWhenTheCheckFails()
    agent, store, gateway = _agent(tmp_path, model)

    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)

    # 모델은 확인 명령을 한 번도 스스로 부르지 않았다 — 두 번 다 하네스가 돌렸다(떨어짐 → 고침 → 통과).
    assert [check["command"] for check in gateway.checks] == [_CHECK, _CHECK]
    assert all(check.get("__declared_check") for check in gateway.checks)
    check = result.verification["declared_check"]
    assert check == {"command": _CHECK, "passed": True, "runs_by_harness": 2}
    assert result.verification["completion_state"] == "complete"
    assert "fixed" in (tmp_path / "value.py").read_text(encoding="utf-8")
    assert result.answer.strip().startswith("고쳤습니다")
    assert model.calls == 4, "통과한 뒤에 모델을 한 번 더 불러 답을 다시 쓰게 하지 않는다"


class _ReportsOnceThenHasNothingToSay:
    """보고는 한 번 낸다. 그 뒤에 또 물으면 할 말이 없어 엉뚱한 한 줄을 낸다 — 새 길의 첫 실제 판(4f03eedb)이 그랬다."""

    report = "바꾼 파일: value.py · 돌려 본 시험: tests/test_value.py 통과 · 확신이 없는 것: 없음"

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if self.calls == 1:
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
        if self.calls == 2:
            return _say(self.report)
        return _say("현재 시각은 오후 3시입니다.")


def test_when_the_harness_run_passes_the_report_given_just_before_it_is_the_answer(tmp_path: Path) -> None:
    model = _ReportsOnceThenHasNothingToSay()
    agent, store, gateway = _agent(tmp_path, model)

    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)

    assert len(gateway.checks) == 1 and result.verification["declared_check"]["passed"] is True
    assert model.report in result.answer, "보고는 이미 받았다 — 통과를 확인했으니 그대로 내보낸다"
    assert "현재 시각" not in result.answer
    assert model.calls == 2
    assert result.verification["completion_state"] == "complete"


class _ClaimsDoneThenFixes:
    """「다 됐다」고 했지만 확인 명령이 떨어진다 — 그 보고는 틀렸다. 고친 뒤의 보고가 답이다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if self.calls == 1:
            return _call("local_write_file", path="value.py", content="VALUE = 'broken'\n")
        if self.calls == 2:
            return _say("첫 보고: 다 됐습니다.")
        if self.calls == 3:
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
        return _say("둘째 보고: 값을 고쳤고 시험이 통과합니다.")


def test_a_report_that_the_check_proved_wrong_is_not_brought_back(tmp_path: Path) -> None:
    agent, store, _ = _agent(tmp_path, _ClaimsDoneThenFixes())
    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)
    assert "둘째 보고" in result.answer and "첫 보고" not in result.answer
    assert result.verification["declared_check"] == {"command": _CHECK, "passed": True, "runs_by_harness": 2}


def test_no_requirements_are_read_out_of_the_task_text(tmp_path: Path) -> None:
    """과제 글에 개수·사이트·「읽어라」가 있어도 요구로 서지 않는다 — 끝은 확인 명령이다."""
    agent, store, _ = _agent(tmp_path, _FixesWhenTheCheckFails())
    result = _run(agent, store, tmp_path, "사람인에서 공고 3개를 직접 열어 읽는 코드를 value.py 에 고쳐줘", declared_check=_CHECK)
    assert result.verification["plan"]["items"] == [] and result.verification["plan"]["total"] == 0
    assert result.verification["completion_state"] == "complete"


def test_an_example_of_a_prohibition_in_the_task_text_does_not_lock_the_job(tmp_path: Path) -> None:
    """그 밤의 hw3 그대로 — 과제 글이 「파일은 만들지 마」를 말해도, 확인 명령을 받은 판은 고치라고 맡긴 판이다."""
    agent, store, gateway = _agent(tmp_path, _FixesWhenTheCheckFails())
    result = _run(agent, store, tmp_path, "조사만 해줘. 파일은 만들지 마 — 같은 말을 잘못 읽는 버그를 고쳐줘", declared_check=_CHECK)
    assert "fixed" in (tmp_path / "value.py").read_text(encoding="utf-8"), "쓰기가 막혔다"
    assert result.verification["declared_check"]["passed"] is True
    assert not [step for step in result.steps if step.get("error") == "explicit_read_only_contract"]
    assert len(gateway.checks) == 2


class _NeverFixes:
    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if self.calls == 1:
            return _call("local_write_file", path="value.py", content="VALUE = 'broken'\n")
        return _say("다 됐습니다.")


def test_a_check_that_never_passes_ends_as_partial_and_says_so(tmp_path: Path) -> None:
    model = _NeverFixes()
    agent, store, gateway = _agent(tmp_path, model)

    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)

    assert len(gateway.checks) == _DECLARED_CHECK_RUNS, "정해진 횟수만큼만 대신 돌린다"
    assert result.verification["declared_check"] == {"command": _CHECK, "passed": False, "runs_by_harness": _DECLARED_CHECK_RUNS}
    assert result.verification["completion_state"] == "partial", "「다 됐습니다」라고 해도 완료가 아니다"


def test_a_job_without_a_declared_check_is_exactly_as_before(tmp_path: Path) -> None:
    agent, store, gateway = _agent(tmp_path, _NeverFixes())
    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘")
    assert result.verification["declared_check"] is None
    assert gateway.checks == [], "확인 명령을 안 받은 판에서는 하네스가 아무것도 대신 돌리지 않는다"
    assert result.verification["stop_reason"] == "wrapped_up:coding_verification_missing"


def test_the_old_verification_gate_steps_aside_only_for_declared_jobs() -> None:
    source = inspect.getsource(BrowserAgent.run)
    assert "if require_sandbox and not declared_check.strip() and (not code_verified or not code_mutated):" in source
    assert 'plan = [] if declared_check.strip() else extract_plan(' in source
    assert agent_module._DECLARED_CHECK_RUNS >= 2


# ── 받는 문 · 돌려주는 글 ───────────────────────────────────────────────────────


def test_the_tool_has_the_two_fields() -> None:
    properties = TASK_TOOL["parameters"]["properties"]
    assert {"task", "repo", "check"} <= set(properties)
    assert TASK_TOOL["parameters"]["required"] == ["task"], "칸 둘은 코드 일에만 쓴다"


def _runtime(tmp_path: Path, project: Path) -> SimpleNamespace:
    config = JarvisConfig(
        runtime_root=tmp_path / "installed", data_dir=tmp_path / "installed" / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True,
    )
    return SimpleNamespace(config=config, local_computer=LocalComputerTools(config), events=EventBus())


def test_a_folder_outside_the_allowed_places_is_refused_before_anything_is_made(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    runtime = _runtime(tmp_path, project)
    with pytest.raises((PermissionError, ValueError)):
        JarvisRuntime.prepare_delegated_code(runtime, str(elsewhere), _CHECK)  # type: ignore[arg-type]
    assert not (tmp_path / "outputs" / "workspace" / "delegated").exists()


def test_a_check_we_could_not_run_is_refused_before_the_branch_is_cut(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime = _runtime(tmp_path, project)
    with pytest.raises((PermissionError, ValueError)):
        JarvisRuntime.prepare_delegated_code(runtime, str(project), "format C: /q")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="repo"):
        JarvisRuntime.prepare_delegated_code(runtime, "", _CHECK)  # type: ignore[arg-type]
    assert not (tmp_path / "outputs" / "workspace" / "delegated").exists()


def test_the_caller_is_told_what_changed_and_how_to_take_it() -> None:
    job = {"id": "j1", "status": "completed", "payload": {"prompt": "고쳐줘"}, "result": {
        "answer": "고쳤습니다.", "completion_state": "complete",
        "agent_trace": {"steps": [{"tool": "local_apply_edit", "ok": True, "arguments": {}}], "verification": {}},
        "delegated": {
            "repo": "C:/work/repo", "branch": "sonjari/task-1", "worktree": "C:/out/repo-1", "base": "abcdef1234567890",
            "changed": [{"status": "M", "path": "src/a.py"}], "changed_count": 1, "stat": "1 file changed",
            "check": {"command": _CHECK, "passed": True, "runs_by_harness": 1},
            "take_home": {"review": "git -C ... diff", "take": "git -C ... cherry-pick -n", "discard": "git ..."},
        },
    }}
    summary = summarize_job(job)
    assert summary["branch"]["name"] == "sonjari/task-1" and summary["branch"]["changed_count"] == 1
    assert summary["branch"]["check"]["passed"] is True
    assert summary["branch"]["take_home"]["take"].endswith("cherry-pick -n")
    assert any("아직 원래 폴더에 없습니다" in note for note in summary["review_notes"])


def test_a_failing_check_is_said_out_loud_to_the_caller() -> None:
    job = {"id": "j1", "status": "completed", "payload": {"prompt": "고쳐줘"}, "result": {
        "answer": "다 됐습니다.", "completion_state": "partial",
        "agent_trace": {"steps": [{"tool": "local_apply_edit", "ok": True, "arguments": {}}], "verification": {}},
        "delegated": {"repo": "r", "branch": "sonjari/task-2", "worktree": "w", "base": "b", "changed": [], "changed_count": 0, "stat": "",
                      "check": {"command": _CHECK, "passed": False, "runs_by_harness": 4}, "take_home": {}},
    }}
    notes = summarize_job(job)["review_notes"]
    assert any("확인 명령이 통과하지 않은 채" in note for note in notes)
    assert any("바뀐 파일이 없습니다" in note for note in notes)
