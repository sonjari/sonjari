"""검증 명령에 폴더 대신 파일 경로를 주면, 그 파일이 든 폴더에서 돌린다 (2026-10-08).

코드 사다리 L6(64K 창) 한 판: 모델이 `local_run_project_command` 의 `path` 에 시험 파일을 넣었다. 도구는 `directory_required`
로 세 번 튕겼고, 모델은 일반 명령줄로 돌아서 시험을 통과시켰다 — 그런데 하네스는 「검증 명령을 돌린 적이 없다」
(`coding_verification_missing`)며 판을 실패로 닫았다. 채점은 통과였다.

「이 파일을 검증해라」는 뜻은 분명하다. 파일이 작업 자리 안에 있으면 그 폴더에서 돌리고, 어디서 돌렸는지 결과에 적는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _local(tmp_path: Path) -> tuple[Path, LocalComputerTools]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True,
    )
    return project, LocalComputerTools(config)


def test_a_file_path_runs_the_command_in_the_folder_that_holds_it(tmp_path: Path) -> None:
    project, local = _local(tmp_path)

    result = local.run_project_command({"path": str(project / "test_ok.py"), "command": ["python", "-m", "pytest", "-q"]})

    assert result.get("exit_code") == 0, result
    assert Path(str(result.get("path") or result.get("cwd") or "")).resolve() == project.resolve(), "어디서 돌렸는지 결과에 있어야 한다"
    assert "test_ok.py" in str(result.get("note") or ""), "파일을 줬는데 그 폴더에서 돌렸다는 말이 있어야 한다"


def test_a_folder_path_runs_as_before(tmp_path: Path) -> None:
    """★ 좋은 표본 — 폴더를 주면 예전 그대로이고 덧말이 없다."""
    project, local = _local(tmp_path)

    result = local.run_project_command({"path": str(project), "command": ["python", "-m", "pytest", "-q"]})

    assert result.get("exit_code") == 0, result
    assert not result.get("note") or "test_ok.py" not in str(result.get("note"))


def test_a_path_that_does_not_exist_is_still_refused(tmp_path: Path) -> None:
    """★ 좋은 표본 — 없는 경로를 눈감아 주지는 않는다."""
    project, local = _local(tmp_path)

    with pytest.raises((FileNotFoundError, NotADirectoryError, ValueError, PermissionError)):
        local.run_project_command({"path": str(project / "nowhere" / "test_ok.py"), "command": ["python", "-m", "pytest", "-q"]})
