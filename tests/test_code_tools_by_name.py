"""코드 도구를 이름으로 불러도 우리 파이썬으로 돈다 · 셸의 python 이 우리 것 (2026-09-26 노트북 코드 모드 E2E)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alture_jarvis.local_computer import _with_our_python_first


def test_our_python_comes_first_on_path() -> None:
    env = _with_our_python_first({"PATH": r"C:\Windows;C:\Users\x\AppData\Local\Microsoft\WindowsApps"})
    first = env["PATH"].split(os.pathsep)[0]
    assert Path(first) == Path(sys.executable).resolve().parent, "윈도우 스토어 가짜 python 보다 우리 것이 먼저"
    assert "WindowsApps" in env["PATH"], "원래 PATH 는 그대로 뒤에 남는다"


def test_windows_style_path_key_is_merged() -> None:
    env = _with_our_python_first({"Path": r"C:\Windows"})
    assert "Path" not in env and env["PATH"].endswith(r"C:\Windows")


def test_a_tool_name_is_run_as_python_module() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "local_computer.py").read_text(encoding="utf-8")
    assert 'elif program == "pytest" or program in _PYTHON_MODULES:' in source
    assert 'executable = [LocalComputerTools._project_python(root, program), "-m", program, *args]' in source


def test_ruff_by_name_actually_runs_through_our_python(tmp_path) -> None:
    """입구와 분기 **둘 다** 받아야 돈다 — 분기만 넣었을 때 입구에서 막혔다(노트북 .2059)."""
    import subprocess

    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools

    work = tmp_path / "repo"
    work.mkdir()
    (work / "calc.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    for command in ("ruff check .", "mypy calc.py"):
        out = tools.run_project_command({"__job_id": "code-job", "path": str(work), "command": command})
        assert out["exit_code"] == 0, (command, out)
