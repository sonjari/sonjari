"""확인 명령 「통과」 판정의 빈틈 둘 (2026-11-09 · 게임 시험 하네스 후보 17).

코드 모드는 바깥 AI 가 준 확인 명령이 **마지막 변경 뒤에** 통과했는지로 끝을 가른다(`declared_check_is_current`). 게임 시험
밤에 하네스가 확인을 직접 돌린 횟수가 다섯 판 연속 0 이었다 — 모델이 스스로 같은 명령을 돌려 통과시켰기 때문이고 그건 설계대로다.
그런데 그 「스스로 통과」를 세는 자리에 빈틈이 둘 있었다.

ㄱ. **어느 폴더에서 돌렸나를 안 본다.** 옛 가지 폴더 · 다른 사본에서 같은 명령이 통과해도 지금 작업 폴더의 통과로 셌다.
ㄴ. **셸로 고친 것을 고침으로 안 센다.** 통과 뒤 `local_run_shell`(sed · cp · git checkout …)이나 **다른** 프로젝트 명령이
   파일을 바꿔도 그 통과가 그대로 「지금 코드의 것」으로 남았다. 셸이 무엇을 바꿨는지는 알 수 없으니, 통과 뒤에 셸 · 다른 명령이
   있으면 그 통과는 지금 것이 아니다 — 하네스가 한 번 더 돌린다(정해진 횟수 안에서).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from alture_jarvis.code_runtime import declared_check_is_current

_CHECK = "python check_human1.py"
_ROOT = str(Path("C:/work/BugGuard-1"))


def _ran(command: Any, *, where: str | None = None, in_args: str | None = None, verified: bool = True) -> dict:
    step: dict[str, Any] = {"tool": "local_run_project_command", "ok": True,
                            "arguments": {"command": command}, "evidence": {"verified": verified}}
    if where is not None:
        step["evidence"]["path"] = where          # 도구 결과에 적힌 실제로 돌린 폴더
    if in_args is not None:
        step["arguments"]["path"] = in_args       # 모델이 준 폴더
    return step


def _edited() -> dict:
    return {"tool": "local_apply_edit", "ok": True, "arguments": {"path": "a.cs"}}


def _shell(command: str = "sed -i s/a/b/ Assets/x.cs", ok: bool = True) -> dict:
    return {"tool": "local_run_shell", "ok": ok, "arguments": {"command": command}}


# ── ㄱ. 어느 폴더에서 돌렸나 ───────────────────────────────────────────────────


def test_a_pass_in_the_work_folder_counts() -> None:
    assert declared_check_is_current([_edited(), _ran(_CHECK, where=_ROOT)], _CHECK, root=_ROOT) is True


def test_a_pass_in_a_folder_inside_the_work_folder_counts() -> None:
    inner = str(Path(_ROOT) / "Tools")
    assert declared_check_is_current([_edited(), _ran(_CHECK, where=inner)], _CHECK, root=_ROOT) is True


def test_a_pass_in_another_folder_does_not_count() -> None:
    other = str(Path("C:/work/BugGuard-0"))   # 옛 가지 폴더 — 이름이 비슷해도 다른 곳
    assert declared_check_is_current([_edited(), _ran(_CHECK, where=other)], _CHECK, root=_ROOT) is False


def test_a_folder_whose_name_only_starts_the_same_does_not_count() -> None:
    longer = _ROOT + "0"   # BugGuard-10 은 BugGuard-1 안이 아니다
    assert declared_check_is_current([_edited(), _ran(_CHECK, where=longer)], _CHECK, root=_ROOT) is False


def test_the_folder_the_model_gave_is_used_when_the_result_has_none() -> None:
    other = str(Path("D:/elsewhere"))
    assert declared_check_is_current([_edited(), _ran(_CHECK, in_args=other)], _CHECK, root=_ROOT) is False
    assert declared_check_is_current([_edited(), _ran(_CHECK, in_args=_ROOT)], _CHECK, root=_ROOT) is True


def test_no_folder_at_all_means_the_job_folder() -> None:
    # 폴더를 안 주면 도구가 잡에 묶인 작업 폴더에서 돌린다(local_computer.run_project_command) — 통과로 친다.
    assert declared_check_is_current([_edited(), _ran(_CHECK)], _CHECK, root=_ROOT) is True


def test_folder_names_are_compared_without_case_or_slash_differences() -> None:
    odd = _ROOT.upper().replace("\\", "/") + "/"
    assert declared_check_is_current([_edited(), _ran(_CHECK, where=odd)], _CHECK, root=_ROOT) is True


def test_without_root_the_old_behaviour_stays() -> None:
    other = str(Path("C:/work/BugGuard-0"))
    assert declared_check_is_current([_edited(), _ran(_CHECK, where=other)], _CHECK) is True


# ── ㄴ. 통과 뒤에 셸 · 다른 명령 ─────────────────────────────────────────────


def test_a_shell_step_after_the_pass_makes_it_stale() -> None:
    assert declared_check_is_current([_edited(), _ran(_CHECK, where=_ROOT), _shell()], _CHECK, root=_ROOT) is False


def test_a_failed_shell_step_after_the_pass_does_not() -> None:
    assert declared_check_is_current([_edited(), _ran(_CHECK, where=_ROOT), _shell(ok=False)], _CHECK, root=_ROOT) is True


def test_another_project_command_after_the_pass_makes_it_stale() -> None:
    steps = [_edited(), _ran(_CHECK, where=_ROOT), _ran("git checkout other-branch", where=_ROOT)]
    assert declared_check_is_current(steps, _CHECK, root=_ROOT) is False


def test_running_the_same_check_again_after_a_shell_makes_it_current_again() -> None:
    steps = [_edited(), _ran(_CHECK, where=_ROOT), _shell(), _ran(_CHECK, where=_ROOT)]
    assert declared_check_is_current(steps, _CHECK, root=_ROOT) is True


def test_shell_and_other_commands_before_the_pass_do_not_matter() -> None:
    steps = [_shell(), _ran("python check_turret.py", where=_ROOT), _edited(), _ran(_CHECK, where=_ROOT)]
    assert declared_check_is_current(steps, _CHECK, root=_ROOT) is True


# ── 하네스가 실제로 작업 폴더를 넘긴다 ─────────────────────────────────────────


def test_every_call_in_the_agent_passes_the_work_folder() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    calls = re.findall(r"declared_check_is_current\(([^()]*)\)", source)
    assert len(calls) >= 5, calls
    missing = [c for c in calls if "root=" not in c]
    assert not missing, f"작업 폴더(root=)를 안 넘기는 자리: {missing}"
