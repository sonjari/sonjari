"""3D 품질 구조 개선 — 일부러 깨 보는 시험 (2026-11-15 · 설계 `설계_3D품질_구조개선`).

- 모양 판: 빨간 텍스처를 입힌 상자도 shape=True 면 회색뿐(색이 모양을 가리지 않는다) · shape=False 면 빨강이 남는다
- 굽기 끝나면 영수증에 모양 판이 저절로 · views(source="shape") · zoom 도 회색
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from alture_jarvis.gen3d.glb import Mesh
from alture_jarvis.gen3d.preview import view_sheet


def _red_box() -> Mesh:
    v = np.array([[x, y, z] for x in (0, 40) for y in (0, 10) for z in (0, 20)], dtype=float)
    f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                  [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]], dtype=np.int64)
    uv = np.full((len(v), 2), 0.5)
    return Mesh(v, f, uv, Image.new("RGB", (8, 8), (220, 20, 20)))


def _object_pixels(path: str) -> np.ndarray:
    img = np.asarray(Image.open(path).convert("RGB")).astype(int)
    body = img[60:, :]  # 이름표 줄 아래
    bg = np.array([245, 245, 243])
    mask = np.abs(body - bg).sum(axis=2) > 30
    mask &= (body.max(axis=2) - body.min(axis=2) > 0) | (body.sum(axis=2) < 600)  # 칸 테두리(200,200,196) 빼기는 아래서
    return body[mask]


def test_shape_sheet_drops_color_and_color_sheet_keeps_it(tmp_path: Path) -> None:
    mesh = _red_box()
    color = _object_pixels(view_sheet(mesh, tmp_path / "c.png", cell=200))
    shape = _object_pixels(view_sheet(mesh, tmp_path / "s.png", cell=200, shape=True))
    assert len(color) > 1000 and len(shape) > 1000
    # 색 판: 빨강이 이긴다
    assert (color[:, 0] - color[:, 1]).mean() > 60
    # 모양 판: 물체 픽셀은 빨강 기운이 없다(테두리 선 200,200,196 의 4 차이까지만 허용)
    assert np.abs(shape[:, 0] - shape[:, 1]).max() <= 4


def test_receipt_and_views_tool_give_a_shape_sheet(tmp_path: Path) -> None:
    from test_gen3d_1114 import _runner, _wait

    image = tmp_path / "a.png"
    image.write_bytes(b"png")
    runner = _runner(tmp_path)
    job_id = runner.submit(image)
    assert _wait(runner, job_id)["state"] == "done"
    files = runner.get(job_id)["receipt"]["files"]
    assert Path(files["shape_views"]).is_file() and files["shape_views"] != files["views"]
    sheet = runner.views(job_id, source="shape")
    assert Path(sheet["file"]).name == "shape_views.png"
    zoom = runner.views(job_id, source="shape", zoom="뒤")
    px = np.asarray(Image.open(zoom["file"]).convert("RGB")).astype(int).reshape(-1, 3)
    assert (np.abs(px[:, 0] - px[:, 1]) <= 4).all()  # 회색뿐
    with pytest.raises(ValueError):
        runner.views(job_id, source="color")


# ── 격자 칸 → 3D 자리 · 흠집 숫자 (설계 `설계_3D작업대_블렌더마무리`) ──────────────────────

def _ball(center=(0.0, 0.0, 0.0), r: float = 10.0) -> Mesh:
    from test_gen3d_snap_1114 import _sphere

    v, f = _sphere(r)  # _sphere 는 가운데를 (r+2) 에 둔다 — 원점으로 옮긴다
    return Mesh(v - (r + 2) + np.asarray(center), f)


def test_region_takes_only_the_near_skin_of_the_named_cells() -> None:
    from alture_jarvis.gen3d.preview import region

    ball = _ball()
    full = region(ball, "앞", "A1:P16", 16, depth=2.0)
    z = ball.positions[:, 2]
    # 「앞」은 +z 쪽 카메라 — 잡힌 점은 앞 겉(z ≥ 10-2)뿐 · 뒤쪽은 안 잡힌다
    assert full["count"] > 0 and z[full["sel"]].min() >= 8.0 - 1e-6
    assert not full["sel"][z < 0].any()
    # 왼쪽 위 칸만: x 는 음수(화면 왼쪽) · y 는 양수(화면 위)
    corner = region(ball, "앞", "E4:F5", 16, depth=3.0)
    pts = ball.positions[corner["sel"]]
    assert len(pts) and (pts[:, 0] < 0).all() and (pts[:, 1] > 0).all()
    box = corner["box"]
    assert len(box["center"]) == 3 and len(box["axes"]) == 3 and box["half"][2] == pytest.approx(1.5)
    # 「뒤」에서 같은 칸은 x 가 반대(화면 왼쪽 = 물체의 +x)
    back = region(ball, "뒤", "E4:F5", 16, depth=3.0)
    assert (ball.positions[back["sel"]][:, 0] > 0).all()
    with pytest.raises(ValueError):
        region(ball, "옆", "A1", 16, depth=1.0)
    with pytest.raises(ValueError):
        region(ball, "앞", "A1", 16, depth=1.0)  # 모서리 칸엔 공이 없다


def test_grid_sheet_is_written(tmp_path: Path) -> None:
    from alture_jarvis.gen3d.preview import view_one

    path = view_sheet(_ball(), tmp_path / "g.png", cell=300, shape=True, grid=16)
    assert Image.open(path).size == (900, 600)
    one = view_one(_ball(), "뒤", tmp_path / "b.png", grid=16)
    w, h = Image.open(one).size
    assert w == h and w > 512  # 512 그림 + 이름표 줄


def test_defects_flag_a_detached_lump_and_stay_quiet_on_a_clean_ball() -> None:
    from alture_jarvis.gen3d.defects import measure

    clean = measure(_ball())
    assert clean["fill_parts"] == 1 and clean["off_volume"] == 0 and clean["flags"] == []
    big, small = _ball(), _ball(center=(30.0, 0.0, 0.0), r=5.0)
    two = Mesh(np.vstack([big.positions, small.positions]), np.vstack([big.faces, small.faces + len(big.positions)]))
    out = measure(two)
    assert out["fill_parts"] == 2 and 0.05 < out["off_volume"] < 0.2
    assert any("떨어진" in f for f in out["flags"])
