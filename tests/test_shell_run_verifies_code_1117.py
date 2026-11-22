"""쓴 파일을 셸로 직접 돌려 성공했으면 코드 검증이다 (2026-11-17 맥 새 계정 소수 판 — 헛경고).

설계 `docs/설계_맥새계정시험_고칠것_2026-11-17.ko.md` P2. 실제 판의 걸음 모양 그대로.
"""
from __future__ import annotations

from alture_jarvis.code_runtime import code_verification_is_current, shell_run_verification_indices

PRIMES = "/Users/sonjaritest/Documents/Documents/sonjari_test/primes.py"


def write(path: str = PRIMES) -> dict:
    return {"tool": "local_write_file", "ok": True, "arguments": {"path": path},
            "evidence": {"output_path": path, "verified": True}}


def shell(command: str, exit_code: int = 0) -> dict:
    return {"tool": "local_run_shell", "ok": True, "arguments": {"command": command},
            "evidence": {"command": command, "exit_code": exit_code, "verified": exit_code == 0}}


def test_the_real_run_counts_as_verification() -> None:
    steps = [
        shell('mkdir -p "Documents/sonjari_test"'),
        write(),
        {"tool": "local_run_project_command", "ok": False, "evidence": {}},
        shell(f"python {PRIMES}"),
    ]
    assert shell_run_verification_indices(steps) == [3]
    assert code_verification_is_current(steps)


def test_running_by_file_name_counts() -> None:
    assert shell_run_verification_indices([write(), shell("cd ~/Documents/sonjari_test && python3 primes.py")]) == [1]


def test_echo_and_look_only_commands_do_not_count() -> None:
    assert shell_run_verification_indices([write(), shell("echo ok")]) == []
    assert shell_run_verification_indices([write(), shell(f"cat {PRIMES}")]) == []
    assert shell_run_verification_indices([write(), shell("ls ~/Documents/Documents/sonjari_test/primes.py")]) == []


def test_a_failed_run_does_not_count() -> None:
    assert shell_run_verification_indices([write(), shell(f"python {PRIMES}", exit_code=1)]) == []


def test_running_before_writing_does_not_count() -> None:
    assert shell_run_verification_indices([shell(f"python {PRIMES}"), write()]) == []


def test_editing_after_the_run_makes_it_stale_again() -> None:
    steps = [write(), shell(f"python {PRIMES}"),
             {"tool": "local_apply_edit", "ok": True, "arguments": {"path": PRIMES},
              "evidence": {"output_path": PRIMES, "verified": True, "changed": True}}]
    assert shell_run_verification_indices(steps) == [1]
    assert not code_verification_is_current(steps)


def test_a_similar_name_is_not_the_written_file() -> None:
    assert shell_run_verification_indices([write(), shell("python old_primes.py")]) == []


# ── P7a: 쓴 코드를 돌려 결과를 읽은 판은 「근거 읽기」도 한 것이다 ──────────────────────────────
from alture_jarvis import plan as _plan  # noqa: E402

OBSERVE_LOCAL = _plan.Requirement("observe", "근거가 되는 대상 실제로 읽기", "local")


def _observed(steps: list[dict], target: str = "local") -> bool:
    req = _plan.Requirement("observe", "근거가 되는 대상 실제로 읽기", target)
    ((_, ok, _saw),) = _plan.check([req], sources=[], steps=steps)
    return ok


def test_running_the_code_it_wrote_is_seeing_the_result() -> None:
    steps = [shell('mkdir -p "Documents/sonjari_test"'), write(), shell(f"python {PRIMES}")]
    assert _observed(steps) and _observed(steps, target="any")


def test_running_something_else_or_failing_is_not() -> None:
    assert not _observed([write(), shell("echo ok")])
    assert not _observed([write(), shell(f"python {PRIMES}", exit_code=1)])
    assert not _observed([shell("python other.py")])


def test_a_web_reading_job_is_not_satisfied_by_running_code() -> None:
    """웹을 보라는 판은 그대로 — 코드 돌리고 기억으로 조사 답을 쓰는 판이 통과하면 안 된다."""
    assert not _observed([write(), shell(f"python {PRIMES}")], target="browser")
