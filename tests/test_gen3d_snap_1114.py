"""겉면 다시 붙이기 — 일부러 깨 보는 시험 (2026-11-14 · 설계 `설계_조립부품나누기` §4-2).

11-14 배 실물의 「우글우글」: 원래 모델은 매끈한데 칸으로 다시 뜨며 계단 잔물결이 생겼다(기울기 흔들림 1.4° → 6.1°).
- 가장 가까운 점 계산이 무작정 다 대 본 답과 같은가(꼭짓점 · 가장자리 · 안쪽 구역 모두)
- 공을 다시 뜨면 붙이기 뒤 진짜 공 표면에 붙는가(끄면 계단만큼 어긋남) · 닫힘 그대로
- 원기둥 · 평면 · 원판에 정확히 붙는가(핀 구멍 지름이 칸 크기에 안 묶임)
- 묶은 꼭짓점은 안 움직이는가 · 접히는 붙이기는 되돌리는가
"""
from __future__ import annotations

import numpy as np
import pytest

from alture_jarvis.gen3d.glb import Mesh
from alture_jarvis.gen3d.printing import check_printable
from alture_jarvis.gen3d.remesh import remesh
from alture_jarvis.gen3d.snap import Cylinder, Disk, MeshSurface, Plane, closest_on_triangles, snap


def _sphere(r: float = 10.0, n: int = 48) -> tuple[np.ndarray, np.ndarray]:
    th = np.linspace(0, np.pi, n + 1)[1:-1]
    ph = np.linspace(0, 2 * np.pi, 2 * n, endpoint=False)
    t, p = np.meshgrid(th, ph, indexing="ij")
    v = np.stack([np.sin(t) * np.cos(p), np.sin(t) * np.sin(p), np.cos(t)], axis=-1).reshape(-1, 3) * r
    v = np.vstack([[0, 0, r], v, [0, 0, -r]])
    rows, cols = len(th), len(ph)
    idx = lambda i, j: 1 + i * cols + (j % cols)  # noqa: E731
    f = []
    for j in range(cols):
        f.append([0, idx(0, j), idx(0, j + 1)])
        f.append([len(v) - 1, idx(rows - 1, j + 1), idx(rows - 1, j)])
    for i in range(rows - 1):
        for j in range(cols):
            a, b, c, d = idx(i, j), idx(i, j + 1), idx(i + 1, j), idx(i + 1, j + 1)
            f += [[a, c, b], [b, c, d]]
    return v + r + 2, np.array(f, dtype=np.int64)


def _brute(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """삼각형 위를 촘촘히 찍어 가장 가까운 점(느리지만 틀릴 수 없는 답)."""
    s = np.linspace(0, 1, 201)
    u, w = np.meshgrid(s, s, indexing="ij")
    keep = (u + w) <= 1
    pts = a + np.outer(u[keep], b - a) + np.outer(w[keep], c - a)
    return pts[np.argmin(np.linalg.norm(pts - p, axis=1))]


def test_closest_point_matches_brute_force_in_every_region() -> None:
    rng = np.random.default_rng(7)
    a, b, c = np.array([0.0, 0, 0]), np.array([4.0, 0, 0]), np.array([1.0, 3, 0])
    pts = rng.uniform(-3, 7, size=(300, 3))
    q = closest_on_triangles(pts, np.tile(a, (300, 1)), np.tile(b, (300, 1)), np.tile(c, (300, 1)))
    for i in range(300):
        want = _brute(pts[i], a, b, c)
        assert np.linalg.norm(q[i] - pts[i]) <= np.linalg.norm(want - pts[i]) + 0.03, i


def test_mesh_surface_finds_the_nearest_triangle_and_ignores_far_points() -> None:
    v, f = _sphere()
    surf = MeshSurface(v, f, radius=0.5)
    centre = np.array([12.0, 12, 12])
    rng = np.random.default_rng(1)
    d = rng.normal(size=(500, 3))
    d /= np.linalg.norm(d, axis=1)[:, None]
    near = centre + d * (10 + rng.uniform(-0.4, 0.4, size=(500, 1)))
    q, dist = surf.closest(near)
    assert np.isfinite(dist).all()
    # 다각형 공이라 진짜 공보다 조금 안쪽(48칸: 최대 0.03mm 안팎)
    assert np.abs(np.linalg.norm(q - centre, axis=1) - 10).max() < 0.05
    _, far = surf.closest(centre + d[:10] * 12)  # 2mm 밖 — 찾는 반지름(0.5) 밖은 inf
    assert np.isinf(far).all()


def test_remeshed_sphere_snaps_back_to_the_true_surface() -> None:
    v, f = _sphere()
    centre = np.array([12.0, 12, 12])
    off = remesh(v, f, pitch=0.35, smooth_rounds=8)
    on = remesh(v, f, pitch=0.35, smooth_rounds=8, snap_to_source=True)
    err_off = np.abs(np.linalg.norm(off.positions - centre, axis=1) - 10)
    err_on = np.abs(np.linalg.norm(on.positions - centre, axis=1) - 10)
    assert np.percentile(err_on, 99) < 0.05 < np.percentile(err_off, 99)  # 붙이면 계단(칸 0.35mm)이 사라진다
    c = check_printable(Mesh(on.positions, on.faces))
    assert c["watertight"] and c["flipped_edges"] == 0 and c["parts"] == 1
    assert on.snap and on.snap["snapped"] > 0.95 * len(on.positions)


def test_cylinder_plane_and_disk_snap_exactly() -> None:
    rng = np.random.default_rng(3)
    p = rng.uniform(-1, 1, size=(400, 3)) * [3, 3, 5]
    cyl = Cylinder(center=np.zeros(3), axis=np.array([0, 0, 1.0]), r=2.1, t0=-4, t1=4, radius=0.5)
    q, d = cyl.closest(p)
    hit = np.isfinite(d)
    assert hit.any()
    assert np.allclose(np.linalg.norm(q[hit][:, :2], axis=1), 2.1)  # 지름이 칸 크기와 상관없이 정확히
    pl = Plane(point=np.array([0, 0, 1.0]), normal=np.array([0, 0, 2.0]), radius=0.5)
    q, d = pl.closest(p)
    assert np.allclose(q[np.isfinite(d)][:, 2], 1.0) and np.isinf(d[np.abs(p[:, 2] - 1) > 0.5]).all()
    dk = Disk(center=np.zeros(3), normal=np.array([0, 0, 1.0]), r=1.0, radius=0.5)
    q, d = dk.closest(p)
    ok = np.isfinite(d)
    assert (np.linalg.norm(q[ok][:, :2], axis=1) <= 1.0 + 1e-9).all() and np.allclose(q[ok][:, 2], 0)


def test_frozen_vertices_stay_and_folding_snaps_are_undone() -> None:
    # 삼각형 두 개(지붕 모양)를 평면에 붙이면 하나가 뒤집힌다 → 되돌린다
    v = np.array([[0, 0, 0], [2, 0, 0], [1, 2, 0], [1, 1, 0.3]], dtype=float)
    f = np.array([[0, 1, 3], [1, 2, 3], [2, 0, 3]])
    frozen = np.array([True, False, False, False])
    target = {"far": Plane(point=np.array([0, 0, 0.0]), normal=np.array([1.0, 0, 0]), radius=5.0)}
    r = snap(v, f, target, frozen=frozen)
    assert np.allclose(r.positions[0], v[0])  # 묶은 꼭짓점은 그대로
    t = r.positions[f]
    n0 = np.cross(v[f][:, 1] - v[f][:, 0], v[f][:, 2] - v[f][:, 0])
    n1 = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    assert (np.einsum("ij,ij->i", n0, n1) > 0).all()  # 뒤집힌 면이 남지 않는다
    assert r.reverted > 0


@pytest.mark.parametrize("pitch", [0.2, 0.5])
def test_snapping_keeps_a_thickened_rod_thick(pitch: float) -> None:
    """굵힌 막대는 원래(가는) 표면으로 되돌아가면 안 된다 — 묶음이 지킨다."""
    from test_gen3d_print_1114 import _box, _merge, _xy_width_at

    base = _box((0, 0, 0), (20, 20, 5))
    rod = _box((9.7, 9.7, 5), (10.3, 10.3, 25))
    r = remesh(*_merge(base, rod), pitch=pitch, smooth_rounds=0, thicken_to_mm=1.6, snap_to_source=True)
    assert r.thickened_cells > 0 and r.snap and r.snap["frozen"] > 0
    assert _xy_width_at(r.positions, 15.0) >= 1.6
