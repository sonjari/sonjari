"""구분자가 빠져 붙은 경로는 실제 폴더로 나눠 연다 (2026-10-02 Ornith 35B 코딩 사다리).

작업 폴더 `…\\tools\\ladder_ornith\\ws2\\L6…` 를 모델이 `toolsladder_ornith` · `tools ladder_ornith` · `tools_ladder_ornith` 로 썼고,
L4 판은 13번, L6 판은 9번 「경로 없음」을 받았다. 단독 호출로는 재현이 안 돼(각 4/4 정상) 원인은 못 가렸다 —
대신 디스크에 있는 이름으로만 나눠서 판을 살린다. 딱 하나로 정해질 때만.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.local_computer import repair_glued_path


@pytest.fixture()
def ladder(tmp_path: Path) -> Path:
    work = tmp_path / "RoboMetaFit" / "tools" / "ladder_ornith" / "ws2" / "L6_two_bug_pipeline-r1"
    work.mkdir(parents=True)
    (work / "pager.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("glued", ["toolsladder_ornith", "tools ladder_ornith", "tools_ladder_ornith"])
def test_the_three_shapes_from_the_ladder_are_repaired(ladder: Path, glued: str) -> None:
    broken = ladder / "RoboMetaFit" / glued / "ws2" / "L6_two_bug_pipeline-r1" / "pager.py"
    fixed = repair_glued_path(broken)
    assert fixed == ladder / "RoboMetaFit" / "tools" / "ladder_ornith" / "ws2" / "L6_two_bug_pipeline-r1" / "pager.py"


def test_a_new_file_in_a_glued_folder_is_placed_in_the_real_folder(ladder: Path) -> None:
    broken = ladder / "RoboMetaFit" / "toolsladder_ornith" / "ws2" / "L6_two_bug_pipeline-r1" / "new_test.py"
    assert repair_glued_path(broken) is None, "읽기(있어야 하는 파일)면 없는 파일을 만들어 내지 않는다"
    fixed = repair_glued_path(broken, allow_missing_leaf=True)
    assert fixed == ladder / "RoboMetaFit" / "tools" / "ladder_ornith" / "ws2" / "L6_two_bug_pipeline-r1" / "new_test.py"


def test_nothing_is_guessed_when_no_or_two_splits_fit(ladder: Path) -> None:
    assert repair_glued_path(ladder / "RoboMetaFit" / "toolsnothing" / "a.py") is None
    (ladder / "RoboMetaFit" / "tools_x" / "ladder_ornith").mkdir(parents=True)
    # 「tools_x」 와 「tools」+「x…」 처럼 두 갈래가 다 맞을 수 있는 이름은 고치지 않는다.
    (ladder / "RoboMetaFit" / "tools" / "x_ladder_ornith").mkdir(parents=True)
    assert repair_glued_path(ladder / "RoboMetaFit" / "tools_x_ladder_ornith") is None


def test_an_existing_path_is_left_alone(ladder: Path) -> None:
    real = ladder / "RoboMetaFit" / "tools" / "ladder_ornith"
    assert repair_glued_path(real) is None
