from __future__ import annotations

from pathlib import Path

import pytest

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


def test_project_command_runs_python_compile_check_without_approval(tmp_path: Path) -> None:
    project, _, gateway = _stack(tmp_path)
    (project / "ok.py").write_text("answer = 42\n", encoding="utf-8")

    result = gateway.execute(
        "local_run_project_command",
        {
            "path": str(project),
            "command": ["python", "-m", "compileall", "-q", "."],
            "timeout_sec": 30,
        },
        job_id="code-1",
    )

    assert result.ok is True
    assert result.risk_level == "L1"
    assert result.result["exit_code"] == 0
    assert result.result["verified"] is True
    assert result.result["command"] == ["python", "-m", "compileall", "-q", "."]


def test_python_dash_c_runs_but_scripts_do_not(tmp_path: Path) -> None:
    """`python -c` 는 2026-09-01 에 열었다 (사용자님 결정).

    예전엔 아래 차단 목록에 있었는데 **근거 주석이 없었다.** 위험도가 새로 늘지
    않는다 — 바로 위 검사가 보여 주듯 `pytest`·`compileall` 이 이미 임의 코드를
    실행한다. 테스트 파일 하나 쓰고 돌리면 되는 일을 한 줄로 못 하게 막고 있었고,
    그래서 자비스는 자기 장부(sqlite)도 못 열고 JSON 분석을 눈으로 했다.

    ★ **2026-09-20 정책 변경 (사장님 승인).** 파일 지정 실행을 **작업 폴더 안에서만** 연다.
    원래 막은 이유는 「작업 폴더 **밖**의 스크립트를 부르는 통로」였고, 그 이유는 경로를
    검사하면 그대로 지켜진다. 막혀 있는 동안 어려운 코딩 판은 재현 스크립트를 짜 놓고
    돌릴 수가 없었다 — 그게 제일 큰 막힘이었다.
    자세한 것은 `tests/test_code_mode_has_room_to_work.py`.
    """
    project, local, _ = _stack(tmp_path)

    result = local.run_project_command(
        {"path": str(project), "command": ["python", "-c", "print(40 + 2)"]}
    )
    assert result["exit_code"] == 0
    assert "42" in str(result)

    # 없는 스크립트는 「없다」고 말한다 — 막힌 것과 없는 것은 다른 말이다.
    with pytest.raises(FileNotFoundError):
        local.run_project_command({"path": str(project), "command": ["python", "foo.py"]})

    # ★ 지켜야 할 것: 작업 폴더 **밖**은 여전히 못 돈다.
    outside = tmp_path / "바깥.py"
    outside.write_text("print('열리면 안 된다')\n", encoding="utf-8")
    for bad in (str(outside), "../바깥.py"):
        with pytest.raises(PermissionError):
            local.run_project_command({"path": str(project), "command": ["python", bad]})

    # 안쪽 스크립트는 돈다.
    (project / "repro.py").write_text("print('재현 40 + 2 =', 40 + 2)\n", encoding="utf-8")
    ran = local.run_project_command({"path": str(project), "command": ["python", "repro.py"]})
    assert ran["exit_code"] == 0 and "42" in str(ran)


def test_declared_installs_run_but_new_packages_need_approval(tmp_path: Path) -> None:
    """설치는 **인자로** 갈린다 (2026-09-01, 사용자님 결정).

    폴더 경계로는 못 막는 일이다 — 설치는 네트워크에서 코드를 끌어와 설치 스크립트까지
    돌린다. 그래서 「어디서 도느냐」가 아니라 **무엇을 가져오느냐**로 가른다:

        pip install -r requirements.txt / npm ci / npm install
            저장소가 이미 선언한 것을 재현 → L1, 승인 없음
        pip install requests / npm install lodash
            새로 끌어옴 → L2, 사람이 본다
    """
    _, local, _ = _stack(tmp_path)

    for declared in (
        ["python", "-m", "pip", "install", "-r", "requirements.txt"],
        ["npm", "ci"],
        ["npm", "install"],
    ):
        assert local._install_risk({"command": declared}).name == "L1", declared

    for fresh in (["python", "-m", "pip", "install", "requests"], ["npm", "install", "lodash"]):
        assert local._install_risk({"command": fresh}).name == "L2", fresh

    # 제거는 여전히 통로가 없다 — 되돌리기가 설치보다 어렵다.
    with pytest.raises((PermissionError, ValueError)):
        local.run_project_command(
            {"path": str(tmp_path / "project"), "command": ["python", "-m", "pip", "uninstall", "x"]}
        )


@pytest.mark.parametrize(
    "command",
    [
        ["powershell", "Get-ChildItem"],
        ["npm", "run", "deploy"],
        ["git", "reset", "--hard"],
        ["git", "status", "&&", "git", "clean", "-fd"],
    ],
)
def test_project_command_rejects_shell_install_and_git_mutations(
    tmp_path: Path, command: list[str]
) -> None:
    project, local, _ = _stack(tmp_path)

    with pytest.raises((PermissionError, ValueError)):
        local.run_project_command({"path": str(project), "command": command})


def test_project_command_reports_a_failed_verification(tmp_path: Path) -> None:
    project, local, _ = _stack(tmp_path)
    (project / "broken.py").write_text("if True print('no')\n", encoding="utf-8")

    result = local.run_project_command(
        {
            "path": str(project),
            "command": ["python", "-m", "py_compile", "broken.py"],
        }
    )

    assert result["exit_code"] != 0
    assert result["verified"] is False
    assert "SyntaxError" in result["stderr"]
    assert result["failure_kind"] == "syntax"
    assert len(result["failure_fingerprint"]) == 16
    assert any("broken.py" in target for target in result["failed_targets"])


def test_zero_exit_with_an_explicit_fail_marker_is_not_verified(tmp_path: Path) -> None:
    project, local, _ = _stack(tmp_path)
    (project / "lying_check.py").write_text(
        "print('[FAIL] 필수 텍스트 없음')\nprint('일부 항목 실패')\n",
        encoding="utf-8",
    )

    result = local.run_project_command(
        {"path": str(project), "command": ["python", "lying_check.py"]}
    )

    assert result["exit_code"] == 0
    assert result["verified"] is False
    assert result["failure_kind"] == "self_reported_failure"
    assert len(result["failure_fingerprint"]) == 16


def test_code_workspace_can_delete_its_temporary_probe_without_approval(tmp_path: Path) -> None:
    project, local, gateway = _stack(tmp_path)
    probe = project / "_jarvis_probe.py"
    probe.write_text("print('probe')\n", encoding="utf-8")
    local.authorize_code_workspace("code-cleanup", str(project))

    result = gateway.execute(
        "local_delete_file", {"path": "_jarvis_probe.py"}, job_id="code-cleanup",
    )

    assert result.ok is True
    assert result.risk_level == "L1"
    assert result.result["verified"] is True
    assert not probe.exists()


def test_git_remote_can_be_read_but_not_changed(tmp_path: Path) -> None:
    """★ 2026-09-20 실전: `git remote -v` 가 막혀 한 걸음을 버렸다 (코딩 과제 걸음 24).

    어느 저장소에서 일하는지 **보는 것**은 읽기다. 그런데 `remote add`·`set-url` 은
    저장소가 어디를 가리키는지를 바꾼다 — 그건 읽기가 아니다. 인자로 가른다.
    """
    import subprocess

    project, local, _ = _stack(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)

    seen = local.run_project_command({"path": str(project), "command": ["git", "remote", "-v"]})
    assert seen["exit_code"] == 0

    for blocked in (
        ["git", "remote", "add", "origin", "https://example.invalid/x.git"],
        ["git", "remote", "set-url", "origin", "https://example.invalid/x.git"],
        ["git", "remote", "remove", "origin"],
    ):
        with pytest.raises(PermissionError):
            local.run_project_command({"path": str(project), "command": blocked})
