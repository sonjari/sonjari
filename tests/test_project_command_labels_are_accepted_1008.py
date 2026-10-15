"""도구 설명이 붙여 준 이름표(`tests`·`lint`…)로 불러도 그 명령을 돌린다 (2026-10-08).

`local_run_project_command` 의 설명은 표다 — 「tests    python -m pytest -q」「lint    python -m ruff check .」….
35B 는 오른쪽 칸을 명령으로 읽는데 **9B 는 왼쪽 칸의 이름표를 명령으로 읽었다**: 64K 창 코드 사다리 6판 중 5판에서
`command="tests"` → `project_command_not_allowed — tests 은(는) 정해진 명령이 아니다. local_run_shell 로 돌려라`.
모델은 시키는 대로 일반 명령줄로 시험을 통과시켰고, 하네스는 「검증 도구를 돌린 적이 없다」며 6판 중 4판을 실패로 닫았다
(채점은 5/6 통과). 도구가 가라고 한 길로 간 판이 벌을 받았다.

설명이 이름을 붙였으면 그 이름은 그 명령이다.
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


@pytest.mark.parametrize("command", ["tests", ["tests"], "Tests", " test "])
def test_the_label_tests_runs_pytest(tmp_path: Path, command) -> None:
    project, local = _local(tmp_path)

    result = local.run_project_command({"path": str(project), "command": command})

    assert result.get("exit_code") == 0 and result.get("verified") is True, result
    assert [str(part).lower() for part in result["command"]][-3:] == ["-m", "pytest", "-q"], result["command"]
    assert "pytest" in str(result.get("note") or ""), "이름표를 무엇으로 돌렸는지 결과에 적는다"


def test_the_description_and_the_labels_do_not_drift_apart() -> None:
    """설명에 적힌 이름표는 전부 받아 준다 — 설명만 늘리고 표를 안 늘리면 같은 버그가 돌아온다."""
    from alture_jarvis.code_runtime import _QWEN_DESCRIPTIONS  # noqa: PLC0415
    from alture_jarvis.local_computer import PROJECT_COMMAND_LABELS  # noqa: PLC0415

    text = _QWEN_DESCRIPTIONS["local_run_project_command"]
    for label in ("tests", "lint", "types", "security", "deps"):
        assert f"  {label} " in text, f"설명에서 {label} 이름표가 사라졌다 — 표도 같이 고쳐라"
        assert label in PROJECT_COMMAND_LABELS


def test_an_ordinary_command_is_untouched(tmp_path: Path) -> None:
    """★ 좋은 표본 — 제대로 쓴 명령에는 덧말이 없다."""
    project, local = _local(tmp_path)

    result = local.run_project_command({"path": str(project), "command": "python -m pytest -q"})

    assert result.get("exit_code") == 0 and not result.get("note")


def test_an_unknown_word_is_still_refused(tmp_path: Path) -> None:
    """★ 좋은 표본 — 이름표가 아닌 낱말을 눈감아 주지는 않는다."""
    project, local = _local(tmp_path)

    with pytest.raises((PermissionError, ValueError)) as caught:
        local.run_project_command({"path": str(project), "command": "frobnicate"})
    assert "project_command_not_allowed" in str(caught.value)
