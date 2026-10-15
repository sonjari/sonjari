"""손자리가 실행하는 명령은 손자리 자신을 바꾸지 못한다 — 「셸 명령 자동 실행」이 켜져 있어도 (2026-10-09).

대표가 권한 화면을 보다 짚었다. 「고치고 만들 수 있는 폴더」 목록은 손자리의 파일 도구에만 걸리고, 손자리가 **실행하는 명령**이
무엇을 쓰는지는 막지 못했다(막는 것은 윈도우 시스템 폴더뿐). 그날 새벽 한 판은 사본을 고친 뒤 돌고 있는 손자리의 설치 폴더를
고치려 했다 — 파일 도구로 시도해 막혔지만 셸로 했으면 됐을 것이다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import local_computer
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

_PACKAGE = Path(local_computer.__file__).resolve().parent          # 지금 도는 코드가 든 폴더


def _tools(tmp_path: Path, *, autorun: bool = True) -> tuple[Path, LocalComputerTools]:
    project = tmp_path / "project"
    project.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path / "installed", data_dir=tmp_path / "installed" / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True, shell_autorun_enabled=autorun,
    )
    return project, LocalComputerTools(config)


def test_a_path_inside_the_running_code_is_recognised(tmp_path: Path) -> None:
    _, tools = _tools(tmp_path)
    target = _PACKAGE / "quantities.py"
    assert tools.names_our_own_install(f'Set-Content "{target}" "x"')
    assert tools.names_our_own_install(f"python -c \"open(r'{str(target).replace(chr(92), '/')}', 'w')\""), "슬래시로 적어도 같은 곳이다"
    assert tools.names_our_own_install(str(tmp_path / "installed" / "data" / "jarvis.db"))
    assert tools.names_our_own_install(str(tmp_path / "installed" / "scripts" / "task_entry.py"))


def test_other_places_are_not_ours(tmp_path: Path) -> None:
    project, tools = _tools(tmp_path)
    assert tools.names_our_own_install(f'Set-Content "{project / "notes.txt"}" "x"') == ""
    assert tools.names_our_own_install(str(tmp_path / "outputs" / "workspace" / "job-1" / "a.py")) == ""
    assert tools.names_our_own_install(str(tmp_path / "installed" / "data-backup" / "old.db")) == "", "이름이 비슷한 다른 폴더"
    assert tools.names_our_own_install("python -m pytest -q tests") == ""


def test_calling_our_python_is_not_touching_our_install(tmp_path: Path) -> None:
    """확인 명령은 「우리 파이썬으로 시험을 돌려라」로 적혀 온다 — 실행 환경을 **부르는** 것은 막지 않는다."""
    import sys
    _, tools = _tools(tmp_path)
    assert tools.names_our_own_install(f'"{sys.executable}" -m pytest -q -p no:cacheprovider tests') == ""


def test_a_shell_command_that_would_change_it_is_refused_even_with_autorun_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, tools = _tools(tmp_path, autorun=True)
    ran: list[Any] = []
    monkeypatch.setattr(local_computer, "run_captured", lambda *a, **k: ran.append(a) or (0, b"", b"", False))

    with pytest.raises(PermissionError, match="own_install_blocked"):
        tools.run_shell({"command": f'Add-Content "{_PACKAGE / "quantities.py"}" "# changed"', "__job_id": "j1"})
    with pytest.raises(PermissionError, match="own_install_blocked"):
        tools.run_shell({"command": f'Remove-Item "{tmp_path / "installed" / "data" / "jarvis.db"}"', "__job_id": "j1"})
    assert ran == [], "막힌 명령은 띄워지지 않는다"


def test_a_shell_command_that_only_looks_is_let_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, tools = _tools(tmp_path)
    ran: list[Any] = []
    monkeypatch.setattr(local_computer, "run_captured", lambda *a, **k: ran.append(a) or (0, b"", b"", False))
    tools.run_shell({"command": f'Get-Content "{_PACKAGE / "quantities.py"}" -TotalCount 5', "__job_id": "j1"})
    assert len(ran) == 1


def test_a_project_command_that_names_it_is_refused(tmp_path: Path) -> None:
    """프로젝트 명령은 파이썬 한 줄처럼 무엇을 하는지 글로 가를 수 없다 — 가리키기만 해도 막는다(읽기는 읽기 도구로)."""
    project, tools = _tools(tmp_path)
    target = str(_PACKAGE / "quantities.py").replace("\\", "/")
    with pytest.raises(PermissionError, match="own_install_blocked"):
        tools.run_project_command({"path": str(project), "command": ["python", "-c", f"open(r'{target}', 'a').write('#')"], "__job_id": "j1"})


def test_an_ordinary_project_command_still_runs(tmp_path: Path) -> None:
    project, tools = _tools(tmp_path)
    done = tools.run_project_command({"path": str(project), "command": ["python", "-c", "print(40 + 2)"], "__job_id": "j1", "timeout_sec": 30})
    assert done["exit_code"] == 0 and "42" in done["stdout"]
