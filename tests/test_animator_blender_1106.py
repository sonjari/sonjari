# -*- coding: utf-8 -*-
"""애니메이터 팩 블렌더 다리(2026-11-06) — 뼈 이름 맞추기 · 원본 안 덮어쓰기 · 진짜 블렌더가 있으면 끝까지 한 판."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from alture_jarvis.animator import blender_bridge as bb


def test_common_rig_names_are_known_for_both_sides() -> None:
    c = bb.bone_candidates()
    assert c["L UpperArm"][:3] == ["upper_arm.L", "DEF-upper_arm.L", "mixamorig:LeftArm"]
    assert c["R Calf"][0] == "shin.R" and "mixamorig:RightLeg" in c["R Calf"]
    assert set(bb.REQUIRED) <= set(c)


def test_tools_refuse_anything_but_an_existing_blend(tmp_path: Path) -> None:
    from test_animator_v1_1103 import _tools

    t = _tools(tmp_path)
    (tmp_path / "x.max").write_bytes(b"x")
    for bad in ("", str(tmp_path / "x.max"), str(tmp_path / "없음.blend")):
        with pytest.raises(FileNotFoundError):
            t.blender_check({"blend": bad})


def test_scripts_save_to_a_new_file_and_never_over_the_original() -> None:
    for script in (bb.WRITE_FIX_PY, bb.BLOCK_PY):
        assert 'filepath=A["save"]' in script
    assert "save_as_mainfile" not in bb.READ_PY


_MOM = Path(r"D:\bench_tmp\blender_pack\mom_block.blend")


@pytest.mark.skipif(not (bb.find_blender() and _MOM.is_file()), reason="이 PC 에 블렌더 · 시험 파일이 있을 때만")
def test_real_blender_check_then_fix_lowers_arm_hits_and_keeps_the_original(tmp_path: Path) -> None:
    from test_animator_v1_1103 import _tools

    src = tmp_path / "mom.blend"
    shutil.copy(_MOM, src)
    before = src.read_bytes()
    t = _tools(tmp_path)
    c = t.blender_check({"blend": str(src)})
    assert "calibration_failed" not in c and c["frames_with_any_hit"] > 0
    f = t.blender_fix({"blend": str(src), "passes": 1})
    assert src.read_bytes() == before                       # 원본 그대로
    assert Path(f["saved"]).is_file()
    assert f["passes"][-1]["arm_cells"] < f["passes"][0]["arm_cells"]
