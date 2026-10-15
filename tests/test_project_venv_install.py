"""설치는 **프로젝트 .venv** 에, 선언된 것은 승인 없이·새 이름은 승인 카드로 (2026-09-26).

노트북 코드 모드 뒤에 설치 길을 따라가 보니: ① `pip install` 이 온텔릭 자기 파이썬에 깔렸고(포장본은 읽기 전용이라
늘 실패), ② 글자 한 줄 명령은 승인 판정을 건너뛰었다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis import project_env
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _local(tmp_path: Path) -> tuple[Path, LocalComputerTools]:
    project = tmp_path / "project"
    project.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True,
    )
    return project, LocalComputerTools(config)


def test_a_string_command_gets_the_same_verdict_as_a_list(tmp_path: Path) -> None:
    project, local = _local(tmp_path)
    for command in ("python -m pip install requests", ["python", "-m", "pip", "install", "requests"]):
        assert local._install_risk({"path": str(project), "command": command}).name == "L2", command


def test_declared_names_run_without_approval_but_new_names_need_it(tmp_path: Path) -> None:
    project, local = _local(tmp_path)
    (project / "requirements.txt").write_text("PyYAML>=6  # 설정\n-r requirements-dev.txt\n", encoding="utf-8")
    (project / "requirements-dev.txt").write_text("pytest-cov\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=["httpx[http2]>=0.27"]\n[project.optional-dependencies]\nai=["numpy"]\n',
        encoding="utf-8",
    )
    risk = lambda command: local._install_risk({"path": str(project), "command": command}).name  # noqa: E731
    for declared in ("python -m pip install pyyaml", "python -m pip install PyYAML==6.0",
                     "python -m pip install pytest-cov", "python -m pip install httpx", "python -m pip install numpy",
                     "python -m pip install -r requirements.txt", "python -m pip install -e ."):
        assert risk(declared) == "L1", declared
    for fresh in ("python -m pip install reqeusts", "python -m pip install pyyaml reqeusts",
                  "python -m pip install git+https://example.com/x.git", "python -m pip install ./wheel.whl"):
        assert risk(fresh) == "L2", fresh


@pytest.mark.parametrize("option", ["--user", "--target=out", "--index-url=https://evil.example/simple",
                                    "--extra-index-url=https://evil.example", "--break-system-packages"])
def test_options_that_change_the_source_or_the_target_never_run(tmp_path: Path, option: str) -> None:
    project, local = _local(tmp_path)
    (project / "requirements.txt").write_text("", encoding="utf-8")
    assert local._install_risk({"path": str(project), "command": f"python -m pip install -r requirements.txt {option}"}).name == "L2"
    with pytest.raises(PermissionError):
        local.run_project_command({"path": str(project), "command": f"python -m pip install -r requirements.txt {option}"})


def test_requirement_file_outside_the_workspace_is_refused(tmp_path: Path) -> None:
    project, local = _local(tmp_path)
    (tmp_path / "evil.txt").write_text("", encoding="utf-8")
    with pytest.raises(PermissionError):
        local.run_project_command({"path": str(project), "command": "python -m pip install -r ../evil.txt"})


def test_install_goes_into_a_project_venv_that_still_sees_our_tools(tmp_path: Path) -> None:
    project, local = _local(tmp_path)
    (project / "requirements.txt").write_text("# 아직 비어 있음\n", encoding="utf-8")
    done = local.run_project_command({"path": str(project), "command": "python -m pip install -r requirements.txt",
                                      "timeout_sec": 240})
    assert done["exit_code"] == 0, done
    assert done["project_venv_created"]["exit_code"] == 0
    venv = project_env.venv_dir(project)
    assert venv is not None and venv.name == ".venv"
    # 이제 `python` 은 프로젝트 가상환경이고, 우리가 싣고 다니는 pytest 도 그 안에서 보인다.
    where = local.run_project_command({"path": str(project), "command": ["python", "-c", "import sys, pytest; print(sys.prefix)"]})
    assert where["exit_code"] == 0, where
    assert Path(where["stdout"].strip()).resolve() == venv.resolve()
    # 두 번째 설치는 가상환경을 다시 만들지 않는다.
    again = local.run_project_command({"path": str(project), "command": "python -m pip install -r requirements.txt",
                                       "timeout_sec": 240})
    assert "project_venv_created" not in again


def test_a_missing_module_failure_says_what_to_install(tmp_path: Path) -> None:
    project, local = _local(tmp_path)
    (project / "requirements.txt").write_text("PyYAML\n", encoding="utf-8")
    (project / "app.py").write_text("import yaml\n", encoding="utf-8")
    (project / "tool.py").write_text("import yamlx_nowhere\n", encoding="utf-8")
    declared = local.run_project_command({"path": str(project), "command": ["python", "-c", "import yaml_not_here_either"]})
    assert declared["install_hint"]["declared"] == "maybe"
    assert "-r requirements.txt" in declared["install_hint"]["next"]
    assert "지어내지" in declared["install_hint"]["next"]


def test_missing_module_hint_matches_a_declared_name() -> None:
    hint = project_env.missing_module_hint("ModuleNotFoundError: No module named 'httpx'", Path(__file__).parent / "_nowhere")
    assert hint is not None and hint["declared"] == "no"
