"""뒤에 붙은 판 검사 (2026-11-17 · 평면 아이콘 → TRELLIS.2 가 「판에 붙은 부조」 · 공식 이슈 TRELLIS.2#45).

지키는 것:
1. 얇은 판 + 앞쪽 부조는 걸린다(그림 면 z · 옆 x 어느 쪽을 보든).
2. 한쪽 면만 넓은 것 — 정육면체 · 상자 앞면 — 은 안 걸린다(판은 앞 · 뒤 두 면이 같은 띠에 있다).
3. 바닥(y) 받침판은 안 걸린다(받침 · 바닥 평면은 판 실패가 아니다).
4. 걸리면 영수증 measured.backing 과 not_done 에 한 줄이 남는다 · 정상은 not_done 에 없다.
운영 기록 30판 역검증(11-17): 판 2 / 2 걸림 · 정상 28 중 헛걸림 0(판 0.805 · 0.771 · 정상 최대 0.173).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

from alture_jarvis.gen3d.defects import BACKING_FLAT_MAX, flat_backing
from alture_jarvis.gen3d.glb import Mesh

_spec = importlib.util.spec_from_file_location("_gen3d_1114", Path(__file__).with_name("test_gen3d_1114.py"))
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)  # type: ignore[union-attr]

_F = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
               [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])


def _box(lo, hi) -> tuple[np.ndarray, np.ndarray]:
    v = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], dtype=np.float64)
    return v, _F.copy()


def _join(*boxes) -> Mesh:
    vs, fs, n = [], [], 0
    for v, f in boxes:
        vs.append(v)
        fs.append(f + n)
        n += len(v)
    return Mesh(positions=np.vstack(vs), faces=np.vstack(fs))


def _plate_with_relief(axis: int = 2) -> Mesh:
    mesh = _join(_box([0, 0, 0], [1, 1.2, 0.01]), _box([0.3, 0.2, 0.01], [0.7, 0.9, 0.25]))
    if axis == 0:  # 판이 옆(x)을 본다
        mesh = Mesh(positions=mesh.positions[:, [2, 1, 0]], faces=mesh.faces[:, [0, 2, 1]])
    return mesh


def test_a_thin_plate_with_a_relief_is_flagged_on_either_horizontal_axis() -> None:
    for axis, name in ((2, "z"), (0, "x")):
        out = flat_backing(_plate_with_relief(axis))
        assert out["axis"] == name and out["share"][name] > BACKING_FLAT_MAX, out
        assert out["flag"] and "TRELLIS.2#45" in out["flag"]


def test_a_cube_or_a_box_front_is_not_a_plate() -> None:
    for mesh in (_join(_box([0, 0, 0], [1, 1, 1])), _join(_box([0, 0, 0], [2, 1, 0.5]))):
        out = flat_backing(mesh)
        assert out["flag"] is None and max(out["share"].values()) < 0.05, out


def test_a_floor_base_plate_is_not_flagged() -> None:
    base = _join(_box([0, 0, 0], [1, 0.01, 1]), _box([0.3, 0.01, 0.3], [0.7, 0.8, 0.7]))  # 받침판(y) 위 기둥
    assert flat_backing(base)["flag"] is None


def test_the_receipt_says_so_only_when_there_is_a_plate(tmp_path: Path) -> None:
    for sub, mesh, want in (("plate", _plate_with_relief(), True), ("cube", "cube", False)):
        root = tmp_path / sub
        root.mkdir()
        image = root / "in.png"
        image.write_bytes(b"png")
        runner = _base._runner(root, mesh)
        found = _base._wait(runner, runner.submit(image, res=512, gpu=1))
        assert found["state"] == "done", found
        receipt = found["receipt"]
        assert "share" in receipt["measured"]["backing"]
        assert any("뒤에 얇은 판" in line for line in receipt["not_done"]) is want
