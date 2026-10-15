"""손자리가 띄우는 사용자 명령은 손자리 자신의 설정(`JARVIS_*`)을 물려받지 않는다 (2026-10-09 새벽).

우리 숙제를 손자리에게 맡긴 판에서 실제로 일어난 일: 손자리가 이 저장소의 사본에서 `pytest` 를 돌리자, 운영 프로세스의
`JARVIS_RUNTIME_ROOT` 가 자식에게 그대로 넘어가 사본의 시험이 **돌고 있는 손자리의 DB** 에 붙었다. 진행 중인 진짜 판이 실패로 찍혔다.
제어 토큰 같은 비밀도 같은 머리로 올라와 있었다.
"""
from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

from alture_jarvis import claude_code, local_computer, project_env
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.tool_gateway import ToolGateway


def _stack(tmp_path: Path) -> tuple[Path, LocalComputerTools, ToolGateway]:
    project = tmp_path / "project"
    project.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project),
        local_computer_enabled=True,
    )
    local = LocalComputerTools(config)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    local.register(gateway)
    return project, local, gateway


def test_our_settings_are_dropped_and_everything_else_is_kept() -> None:
    kept = project_env.without_our_settings({
        "JARVIS_RUNTIME_ROOT": "somewhere", "jarvis_port": "1", "Jarvis_Control_Token": "x",
        "PATH": "p", "MY_JARVIS_NOTE": "mine", "JARVISX": "not ours",
    })
    assert kept == {"PATH": "p", "MY_JARVIS_NOTE": "mine", "JARVISX": "not ours"}


def test_it_returns_a_new_mapping() -> None:
    source = {"JARVIS_PORT": "1", "PATH": "p"}
    assert project_env.without_our_settings(source) is not source
    assert source == {"JARVIS_PORT": "1", "PATH": "p"}


def test_a_project_command_does_not_see_where_the_running_app_lives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """진짜로 자식을 띄워 본다 — 자식이 찍은 환경에 우리 값이 없어야 한다."""
    monkeypatch.setenv("JARVIS_RUNTIME_ROOT", str(tmp_path / "the-running-app"))
    monkeypatch.setenv("JARVIS_CONTROL_TOKEN", "a-secret-for-this-test-only")
    monkeypatch.setenv("NOT_OURS_FOR_THIS_TEST", "stays")
    project, _, gateway = _stack(tmp_path)

    result = gateway.execute(
        "local_run_project_command",
        {
            "path": str(project),
            "command": ["python", "-c", "import os; print(sorted(k for k in os.environ if k.upper().startswith('JARVIS_')), os.environ.get('NOT_OURS_FOR_THIS_TEST')); print('ROOT=' + os.environ.get('JARVIS_RUNTIME_ROOT', ''))"],
            "timeout_sec": 30,
        },
        job_id="code-1",
    )

    assert result.ok is True, result.result
    assert result.result["exit_code"] == 0, result.result
    out = str(result.result.get("stdout") or result.result)
    # ★ 2026-10-11: 「우리 이름이 하나도 없다」에서 「돌고 있는 앱의 자리가 안 보인다」로 고쳐 적는다. 설정을 안 넘기기만 했더니
    #   사본의 코드가 기본값(진짜 앱 폴더)으로 갔다 — 그래서 이제는 명령마다 **지워질 빈 자리**를 그 이름으로 넘긴다
    #   (`project_env.scratch_home`). 물려받는 것은 여전히 없다: 두 이름 모두 방금 만든 임시 폴더를 가리킨다.
    assert "['JARVIS_BACKUP_DIR', 'JARVIS_RUNTIME_ROOT'] stays" in out, out
    assert "the-running-app" not in out and "sonjari-scratch-" in out, out
    assert "a-secret-for-this-test-only" not in out


def test_the_shell_gets_the_same_cleaned_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_RUNTIME_ROOT", str(tmp_path / "the-running-app"))
    monkeypatch.setenv("NOT_OURS_FOR_THIS_TEST", "stays")
    project, local, _ = _stack(tmp_path)
    seen: dict[str, dict[str, str]] = {}

    def fake(executable, *, cwd, env, timeout_sec, **_kwargs):  # type: ignore[no-untyped-def]
        seen["env"] = dict(env)
        return 0, b"", b"", False

    monkeypatch.setattr(local_computer, "run_captured", fake)
    local.run_shell({"command": "echo hi", "timeout_sec": 10, "__job_id": "shell-1"})

    assert seen, "셸이 띄워지지 않았다"
    # 물려받은 것은 없고, 명령마다 새로 만든 빈 자리만 그 이름으로 간다(2026-10-11 · `project_env.scratch_home`).
    ours = {key: value for key, value in seen["env"].items() if key.upper().startswith("JARVIS_")}
    assert sorted(ours) == ["JARVIS_BACKUP_DIR", "JARVIS_RUNTIME_ROOT"]
    assert all("the-running-app" not in value and "sonjari-scratch-" in value for value in ours.values()), ours
    assert seen["env"].get("NOT_OURS_FOR_THIS_TEST") == "stays"
    assert seen["env"].get("PYTHONUTF8") == "1"


def test_every_place_that_hands_a_whole_environment_to_a_user_command_cleans_it() -> None:
    """환경을 통째로 넘기는 자리가 다시 생기면 여기서 걸린다."""
    for module, owner in ((local_computer, "run_project_command"), (local_computer, "run_shell")):
        source = inspect.getsource(getattr(module.LocalComputerTools, owner))
        assert "without_our_settings" in source, owner
        assert "os.environ.copy()" not in source and "**os.environ," not in source, owner
    launcher = inspect.getsource(claude_code)
    assert "environment = project_env.without_our_settings(dict(os.environ))" in launcher


def test_this_test_process_itself_points_at_no_running_app() -> None:
    """conftest 가 시험 시작 때 지운다 — 사람이 일부러 올리는 스위치만 남는다."""
    left = sorted(key for key in os.environ if key.upper().startswith("JARVIS_"))
    assert all(key.upper() in {"JARVIS_UNITY_LIVE_PROJECT", "JARVIS_UI_VERIFY"} for key in left), left


# ── 작업 폴더의 코드가 우리 환경에 깔린 같은 이름보다 먼저 불려 온다 (2026-10-09 새벽 · 판 hw5 재실행) ──────
#
# 손자리가 이 저장소의 사본을 고치고 `python 스크립트.py` 로 확인하자 **운영 손자리의 같은 패키지**가 불려 왔다. 고친 것이
# 안 먹은 것처럼 보였고, 모델은 불려 오는 쪽(돌고 있는 손자리의 설치 폴더)을 고치려 했다(허용 범위 문이 막았다).


def test_the_workspace_src_goes_first_on_the_python_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src" / "some_pkg").mkdir(parents=True)
    (project / "src" / "some_pkg" / "__init__.py").write_text("", encoding="utf-8")
    environment = project_env.with_project_sources_first({"PYTHONPATH": "elsewhere"}, project)
    assert environment["PYTHONPATH"].split(os.pathsep) == [str(project / "src"), "elsewhere"]
    again = project_env.with_project_sources_first(environment, project)
    assert again["PYTHONPATH"].split(os.pathsep).count(str(project / "src")) == 1


def test_a_folder_without_python_under_src_is_left_alone(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src" / "assets").mkdir(parents=True)
    (project / "src" / "assets" / "logo.txt").write_text("x", encoding="utf-8")
    assert "PYTHONPATH" not in project_env.with_project_sources_first({}, project)
    assert "PYTHONPATH" not in project_env.with_project_sources_first({}, tmp_path / "nowhere")


def test_a_script_in_the_workspace_imports_the_workspace_copy_of_a_package_we_also_ship(tmp_path: Path) -> None:
    """진짜로 자식을 띄워 본다 — 우리 환경에 깔린 `alture_jarvis` 가 아니라 작업 폴더의 것이 불려 와야 한다."""
    project, _, gateway = _stack(tmp_path)
    package = project / "src" / "alture_jarvis"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("WHERE = 'the workspace copy'\n", encoding="utf-8")

    result = gateway.execute(
        "local_run_project_command",
        {"path": str(project), "command": ["python", "-c", "import alture_jarvis; print(getattr(alture_jarvis, 'WHERE', 'the installed one'))"], "timeout_sec": 30},
        job_id="code-1",
    )

    assert result.result["exit_code"] == 0, result.result
    assert "the workspace copy" in str(result.result.get("stdout")), result.result


def test_both_command_doors_put_the_workspace_first() -> None:
    for owner in ("run_project_command", "run_shell"):
        assert "with_project_sources_first" in inspect.getsource(getattr(local_computer.LocalComputerTools, owner)), owner
