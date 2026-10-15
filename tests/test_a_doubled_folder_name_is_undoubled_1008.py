"""같은 폴더 이름이 두 번 겹친 경로는 실제로 있는 쪽으로 바로잡는다 (2026-10-08).

바깥 코드 과제를 9B 로 돌린 밤: 작업 폴더가 `…/forth` 인데 모델이 그 안의 설명서를 `…/forth/forth/INSTRUCTIONS.md` 로 불렀다.
도구는 「경로 없음」과 근처 안내를 다섯 번 줬고 모델은 같은 경로를 되풀이했다 — 판이 10초 만에 0걸음으로 멈췄다(열두 과제 중 둘).
안내는 안 먹었다. 디스크에 실제로 있는 경로로만 바로잡는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools, repair_doubled_folder


def _local(tmp_path: Path) -> tuple[Path, LocalComputerTools]:
    project = tmp_path / "forth"
    project.mkdir()
    (project / "INSTRUCTIONS.md").write_text("# 할 일\n", encoding="utf-8")
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True,
    )
    return project, LocalComputerTools(config)


def test_a_doubled_folder_resolves_to_the_file_that_exists(tmp_path: Path) -> None:
    project, local = _local(tmp_path)

    found = local._resolve(str(project / "forth" / "INSTRUCTIONS.md"))

    assert found == (project / "INSTRUCTIONS.md").resolve()


def test_a_new_file_under_a_doubled_folder_lands_in_the_real_folder(tmp_path: Path) -> None:
    """쓸 파일도 같다 — 없는 `forth/forth/` 를 새로 파지 않고 실제 폴더에 둔다."""
    project, local = _local(tmp_path)

    target = local._resolve(str(project / "forth" / "forth.py"), must_exist=False, write=True)

    assert target == (project / "forth.py").resolve()


def test_a_real_nested_folder_of_the_same_name_is_left_alone(tmp_path: Path) -> None:
    """★ 좋은 표본 — 겹친 이름의 폴더가 정말 있으면 그 경로가 맞다."""
    project, local = _local(tmp_path)
    (project / "forth").mkdir()
    (project / "forth" / "notes.md").write_text("안쪽\n", encoding="utf-8")

    assert local._resolve(str(project / "forth" / "notes.md")) == (project / "forth" / "notes.md").resolve()


def test_a_path_that_exists_nowhere_still_fails(tmp_path: Path) -> None:
    project, local = _local(tmp_path)

    with pytest.raises(FileNotFoundError):
        local._resolve(str(project / "forth" / "missing.md"))


def test_two_possible_repairs_are_not_guessed(tmp_path: Path) -> None:
    """겹친 자리가 둘이고 둘 다 맞아떨어지면 고르지 않는다."""
    (tmp_path / "a" / "b" / "b").mkdir(parents=True)
    (tmp_path / "a" / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "b" / "x.txt").write_text("1", encoding="utf-8")  # 겹친 a 를 걷으면 여기
    (tmp_path / "a" / "a" / "b" / "x.txt").write_text("2", encoding="utf-8")  # 겹친 b 를 걷으면 여기
    doubled = tmp_path / "a" / "a" / "b" / "b" / "x.txt"

    assert not doubled.exists()
    assert repair_doubled_folder(doubled) is None
