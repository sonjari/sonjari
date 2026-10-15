from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from alture_jarvis.claude_code import (
    CLAUDE_CODE_TOOL,
    ClaudeCodeTools,
    build_command,
    completion_answer,
    delegation_decision,
    initial_delegation_reason,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.plan import wants_code


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(tmp_path),
        claude_code_enabled=True,
        claude_code_lease_sec=30,
    )


def _step(
    tool: str,
    *,
    ok: bool = True,
    arguments: dict | None = None,
    evidence: dict | None = None,
) -> dict:
    return {
        "tool": tool,
        "ok": ok,
        "arguments": arguments or {},
        "evidence": evidence or {},
    }


def test_initial_delegation_is_only_for_explicit_multi_file_or_git_work() -> None:
    assert initial_delegation_reason("여러 파일을 함께 고쳐줘") == "multi_file_request"
    assert initial_delegation_reason("두 파일을 수정하고 pytest를 실행해줘") == "multi_file_request"
    assert initial_delegation_reason("이 git 저장소를 리팩터링해줘") == "git_repository_request"
    assert initial_delegation_reason("파이썬 함수 하나 만들어줘") == ""


def test_real_korean_multi_file_prompt_is_recognized_as_coding() -> None:
    prompt = (
        "E:\\work\\repo 안의 여러 파일을 함께 수정해줘. "
        "alpha.py에 multiply를 추가하고 test_alpha.py에 그 테스트를 추가해서 "
        "pytest를 실제로 통과시켜줘."
    )
    assert wants_code(prompt)
    assert initial_delegation_reason(prompt) == "multi_file_request"


def test_same_file_must_fail_twice_before_delegation() -> None:
    failed = _step(
        "sandbox_run",
        arguments={"code": "python app.py"},
        evidence={"ok": False, "exit_code": 1},
    )
    assert delegation_decision("app.py 고쳐줘", [failed]) is None
    decision = delegation_decision("app.py 고쳐줘", [failed, failed])
    assert decision is not None
    assert decision.reason == "sandbox_same_file_failed_twice"


def test_a_successful_test_rerun_cancels_the_failure_trigger() -> None:
    failed = _step(
        "sandbox_run",
        arguments={"code": "pytest -q"},
        evidence={"ok": False, "exit_code": 1},
    )
    passed = _step(
        "sandbox_run",
        arguments={"code": "pytest -q"},
        evidence={"ok": True, "exit_code": 0},
    )
    assert delegation_decision("테스트를 통과시켜줘", [failed]).reason == "tests_still_failing"
    assert delegation_decision("테스트를 통과시켜줘", [failed, passed]) is None


def test_waiting_session_is_resumed_instead_of_started_again() -> None:
    waiting = _step(
        CLAUDE_CODE_TOOL,
        evidence={"session_id": "session-123", "status": "waiting_continuation"},
    )
    decision = delegation_decision("계속 고쳐줘", [waiting])
    assert decision is not None
    assert decision.reason == "resume_after_budget"
    assert decision.resume_session_id == "session-123"


def test_command_uses_stream_json_subscription_login_and_resume(tmp_path: Path) -> None:
    command = build_command(
        ["claude"],
        prompt="고쳐줘",
        folder=tmp_path,
        resume_session_id="session-123",
    )
    assert command[:3] == ["claude", "-p", "고쳐줘"]
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--allowedTools") + 1] == "Read,Edit,Bash"
    assert command[command.index("--resume") + 1] == "session-123"
    assert "--bare" not in command


def test_current_npm_wrapper_resolves_native_claude_without_a_shell(tmp_path: Path) -> None:
    wrapper = tmp_path / "claude.cmd"
    wrapper.write_text("@echo off", encoding="utf-8")
    native = (
        tmp_path
        / "node_modules"
        / "@anthropic-ai"
        / "claude-code"
        / "bin"
        / "claude.exe"
    )
    native.parent.mkdir(parents=True)
    native.write_bytes(b"native")
    config = _config(tmp_path)
    config.claude_code_command = str(wrapper)
    helper = ClaudeCodeTools(config, EventBus(), LocalComputerTools(config))

    assert helper._command_prefix() == [str(native)]


def test_completed_result_becomes_a_cost_visible_answer_without_session_id() -> None:
    answer = completion_answer(
        {
            "result": "두 파일을 수정했고 pytest 2개가 통과했습니다.",
            "session_id": "private-resume-id",
            "total_cost_usd": 0.2054146,
        }
    )
    assert "pytest 2개가 통과" in answer
    assert "예상비용 $0.2054" in answer
    assert "private-resume-id" not in answer


def test_clean_git_is_autonomous_but_dirty_folder_is_l2(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True)

    config = _config(tmp_path)
    tools = ClaudeCodeTools(config, EventBus(), LocalComputerTools(config))
    arguments = {"folder": str(repo)}
    assert tools._risk(arguments).label() == "L1"
    (repo / "dirty.txt").write_text("dirty", encoding="utf-8")
    assert tools._risk(arguments).label() == "L2"


def test_stream_result_records_session_result_and_cost(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "work"
    folder.mkdir()
    fake = tmp_path / "fake_claude.py"
    events = [
        {"type": "system", "subtype": "init", "session_id": "session-live"},
        {
            "type": "assistant",
            "session_id": "session-live",
            "message": {"content": [{"type": "text", "text": "수정했습니다"}]},
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": "session-live",
            "result": "테스트 통과",
            "total_cost_usd": 0.0123,
            "duration_ms": 20,
        },
    ]
    fake.write_text(
        "import json\n"
        f"events = {events!r}\n"
        "for event in events: print(json.dumps(event), flush=True)\n",
        encoding="utf-8",
    )
    config = _config(tmp_path)
    tools = ClaudeCodeTools(config, EventBus(), LocalComputerTools(config))
    monkeypatch.setattr(tools, "_command_prefix", lambda: [sys.executable, str(fake)])
    result = tools.delegate(
        {
            "prompt": "작업해줘",
            "folder": str(folder),
            "reason": "test",
            "__job_id": "job-1",
        }
    )
    assert result["status"] == "completed"
    assert result["session_id"] == "session-live"
    assert result["result"] == "테스트 통과"
    assert result["total_cost_usd"] == 0.0123


def test_delegation_targets_the_authorized_code_repository_not_an_empty_desk(tmp_path) -> None:
    """Code 모드의 위임이 빈 잡 책상을 가리켜, 승인해도 고칠 파일이 없었다."""
    from alture_jarvis.claude_code import ClaudeCodeTools

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "model.py").write_text("x = 1\n", encoding="utf-8")
    desk = tmp_path / "workspace"

    class _Local:
        def code_workspace(self, job_id: str):
            return repo if job_id == "job-with-repo" else None

        def job_workspace(self, job_id: str, *, create: bool = False):
            path = desk / job_id
            if create:
                path.mkdir(parents=True, exist_ok=True)
            return path

        def resolve_allowed_path(self, raw: str, *, must_exist: bool = True):
            raise AssertionError("경로를 지목하지 않은 요청이다")

    tools = ClaudeCodeTools.__new__(ClaudeCodeTools)
    tools.local_computer = _Local()

    prompt = "모델과 서비스 두 파일을 함께 고치고 테스트를 실행해."
    assert tools.folder_for(prompt, job_id="job-with-repo") == repo
    assert tools.folder_for(prompt, job_id="plain-job") == desk / "plain-job"
