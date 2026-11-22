"""3D 내보내기 `gen_3d_export` — 유니티 FBX · GLB (2026-11-18 · 설계 `설계_블렌더공통층_워크플로우` §5-3 · G6).

해야 할 것: 다시 불러와 잰 숫자를 요청과 대 봄(긴 변 · 바닥 · 가운데 · 배율 1 · 축 · 예산) / export_v<n> 새 칸 · 원본 그대로 /
엔진 이름은 영문 · 숫자 · _ / 블렌더 없으면 까닭 / 진짜 블렌더로 정육면체 한 판(FBX · GLB)
하면 안 되는 것: 블렌더가 「됐다」고 해도 숫자가 어긋나면 ok / 100배 배율 · 누운 축을 그냥 넘김
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_gen3d_1114 import _cube, _no_real_slicer, _write_glb  # noqa: F401
from test_gen3d_finish_1116 import _done_runner, _found

from alture_jarvis.gen3d import export as ex
from alture_jarvis.gen3d.blender import find_blender


def _good_after(size: float = 1.0, rot: list[float] | None = None, tris: int = 12) -> dict[str, Any]:
    return {"objects": 1, "tris": tris, "dims_m": [size * 0.5, size * 0.4, size], "min_z": 0.0, "center_xy": [0.0, 0.0],
            "obj_scale": [1.0, 1.0, 1.0], "obj_rot_deg": rot if rot is not None else [90.0, 0.0, 0.0], "materials": 1, "images": 0}


class _FakeExport:
    def __init__(self, after: dict[str, Any] | None = None) -> None:
        self.after = after or _good_after()
        self.jobs: list[dict[str, Any]] = []

    def __call__(self, script: str, job: dict[str, Any], *, exe: str | None = None, timeout: int = 0) -> dict[str, Any]:
        assert script == "export.py"
        self.jobs.append(job)
        Path(job["output"]).write_bytes(b"fbx")
        return {"ok": True, "before": {"faces": 145200}, "after": self.after, "decimate_ratio": None, "scale_factor": 1.0, "blender": "5.2.3"}


@pytest.mark.parametrize("raw, want", [("robot_shaded", "robot_shaded"), ("로봇 v2!", "v2"), ("", "Model"), ("3d-cat", "M_3d_cat")])
def test_engine_names_are_ascii(raw: str, want: str) -> None:
    assert ex.safe_name(raw) == want


def test_a_good_reimport_passes(tmp_path: Path) -> None:
    out = ex.export_glb(tmp_path / "a.glb", tmp_path / "e", size_m=1.0, max_faces=20000, find=_found, run=_FakeExport())
    assert out["ok"] and not out["not_done"] and out["files"]["fbx"].endswith("Model.fbx") and "Extract" in out["unity"]


@pytest.mark.parametrize("after, why", [
    ({**_good_after(), "obj_scale": [100.0, 100.0, 100.0]}, "배율"),
    ({**_good_after(), "obj_rot_deg": [0.0, 0.0, 0.0]}, "축"),
    ({**_good_after(), "dims_m": [0.5, 0.4, 1.3]}, "긴 변"),
    ({**_good_after(), "min_z": 0.2}, "바닥"),
    ({**_good_after(), "center_xy": [0.3, 0.0]}, "가운데"),
    ({**_good_after(), "tris": 25000}, "예산"),
    ({"objects": 0}, "메시가 없다"),
])
def test_blender_saying_ok_is_not_enough(tmp_path: Path, after: dict[str, Any], why: str) -> None:
    out = ex.export_glb(tmp_path / "a.glb", tmp_path / "e", size_m=1.0, max_faces=20000, find=_found, run=_FakeExport(after))
    assert not out["ok"] and any(why in n for n in out["not_done"]), out["not_done"]


def test_glb_expects_no_rotation(tmp_path: Path) -> None:
    out = ex.export_glb(tmp_path / "a.glb", tmp_path / "e", fmt="glb", find=_found, run=_FakeExport(_good_after(rot=[0.0, 0.0, 0.0])))
    assert out["ok"] and out["files"]["glb"].endswith(".glb")


@pytest.mark.parametrize("kw", [{"fmt": "obj"}, {"size_m": 0.0}, {"max_faces": 10}, {"origin": "center"}])
def test_bad_arguments_are_refused(tmp_path: Path, kw: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ex.export_glb(tmp_path / "a.glb", tmp_path / "e", find=_found, run=_FakeExport(), **kw)


def test_no_blender_points_at_the_setup_tool(tmp_path: Path) -> None:
    out = ex.export_glb(tmp_path / "a.glb", tmp_path / "e", find=lambda: {"found": False, "why": "없음"})
    assert not out["ok"] and "gen_3d_blender" in out["not_done"][0]


def test_runner_writes_new_export_folders_and_keeps_the_original(tmp_path: Path) -> None:
    runner, job_id = _done_runner(tmp_path)
    home = tmp_path / "out" / job_id
    original = next(home.glob("*.glb"))
    before = original.read_bytes()
    fake = _FakeExport()
    runner._run_export = fake
    first = runner.export(job_id, size_m=1.0)
    second = runner.export(job_id, fmt="glb", base="original", name="Cube Hero", max_faces=500)
    assert Path(first["folder"]).name == "export_v1" and Path(second["folder"]).name == "export_v2"
    assert fake.jobs[1]["name"] == "Cube_Hero" and fake.jobs[1]["format"] == "glb" and fake.jobs[1]["max_faces"] == 500
    assert original.read_bytes() == before and (Path(first["folder"]) / "export.json").is_file()


@pytest.mark.skipif(not find_blender()["found"], reason="블렌더 없음")
@pytest.mark.parametrize("fmt", ["unity_fbx", "glb"])
def test_real_blender_round_trip(tmp_path: Path, fmt: str) -> None:
    glb = tmp_path / "cube.glb"
    _write_glb(glb, _cube())
    out = ex.export_glb(glb, tmp_path / "e", fmt=fmt, name="Cube", size_m=2.0, max_faces=1000)
    assert out["ok"], out["not_done"]
    after = out["measured"]["after"]
    assert abs(max(after["dims_m"]) - 2.0) < 0.005 and after["obj_scale"] == [1.0, 1.0, 1.0] and after["tris"] <= 1000
