"""붙이기가 만든 「까실까실」 접힘 — 일부러 깨 보는 시험 (2026-11-20 · 대표가 뱀부에서 본 햄버거 곰).

햄버거 층 사이 · 팔다리 이음매 · 아래 테두리(오목한 골)를 따라 가시 같은 잔면이 줄지어 섰다. 실측(곰 · 칸 0.304mm):
90° 넘게 꺾인 모서리가 붙이기 전 19 → 붙인 뒤 735. 골 양쪽 꼭짓점이 원래 모델의 골선 하나로 몰려 접힌 것.
- 층진 원기둥(햄버거처럼 지름이 다른 층)을 다시 뜨면 접힘 막기가 날카로운 접힘을 크게 줄이는가 — 끄면 많아야 한다
- 매끈한 공은 손대지 않는가(같은 위치)
- 자른 면 · 구멍 같은 다른 붙일 곳에 붙은 꼭짓점은 그대로인가
- 닫힘은 그대로인가 · 원래 겉에서 멀어지지 않는가
"""
from __future__ import annotations

import numpy as np
import pytest

from alture_jarvis.gen3d import snap as S
from alture_jarvis.gen3d.glb import Mesh
from alture_jarvis.gen3d.printing import check_printable
from alture_jarvis.gen3d.remesh import remesh

from test_gen3d_snap_1114 import _sphere


def _cylinder(r: float, z0: float, z1: float, n: int = 96) -> tuple[np.ndarray, np.ndarray]:
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.stack([np.cos(a) * r, np.sin(a) * r], axis=1)
    v = np.vstack([np.c_[ring, np.full(n, z0)], np.c_[ring, np.full(n, z1)], [[0, 0, z0], [0, 0, z1]]])
    bc, tc = 2 * n, 2 * n + 1
    f = []
    for i in range(n):
        j = (i + 1) % n
        f += [[i, j, n + j], [i, n + j, n + i], [bc, j, i], [tc, n + i, n + j]]
    return v, np.array(f, dtype=np.int64)


def _stack() -> tuple[np.ndarray, np.ndarray]:
    """햄버거처럼 지름이 다른 층 셋(두 군데 오목한 층 사이 골)."""
    parts = [_cylinder(9.0, 0.0, 4.0), _cylinder(6.5, 4.0, 7.0), _cylinder(9.5, 7.0, 12.0)]
    vs, fs, off = [], [], 0
    for v, f in parts:
        vs.append(v)
        fs.append(f + off)
        off += len(v)
    v = np.vstack(vs)
    v[:, :2] += 12.0
    v[:, 2] += 1.0
    return v, np.vstack(fs)


def _sharp(pos: np.ndarray, faces: np.ndarray, deg: float = 90.0) -> int:
    ang, _, _ = S.edge_dihedral(pos, faces)
    return int((ang > deg).sum())


def _remesh(pos: np.ndarray, faces: np.ndarray, monkeypatch: pytest.MonkeyPatch, guard: bool):
    if not guard:
        # 기준 판 = 운영 전(두 고침 모두 끔) — 3차에 털 펴기가 강해져(0.15) 접힘까지 펴므로 같이 끈다
        monkeypatch.setattr(S, "ease_creases", lambda before, after, faces, movable, **k: (after, 0))
        monkeypatch.setattr(S, "smooth_hairs", lambda p, f, m, **k: (p, 0))
    try:
        return remesh(pos, faces, pitch=0.25, snap_to_source=True)
    finally:
        monkeypatch.undo()


def test_layer_grooves_lose_their_spikes(monkeypatch: pytest.MonkeyPatch) -> None:
    v, f = _stack()
    off = _remesh(v, f, monkeypatch, guard=False)
    on = _remesh(v, f, monkeypatch, guard=True)
    n_off, n_on = _sharp(off.positions, off.faces), _sharp(on.positions, on.faces)
    assert n_off >= 20, f"모양이 접힘을 만들지 못했다 — 시험이 아무것도 안 잰다({n_off})"
    assert n_on <= n_off * 0.35, (n_off, n_on)
    assert on.snap["crease_eased"] > 0
    chk = check_printable(Mesh(on.positions, on.faces))
    assert chk["printable"]["ok"], chk["printable"]
    # 원래 겉에서 멀어지지 않는다(99% 가 칸 크기의 0.75 안 — 11-20 실측 0.156mm · 붙이기 없으면 0.27mm)
    _, d = S.MeshSurface(v, f, 0.5).closest(on.positions)
    d = np.where(np.isfinite(d), d, 0.5)
    assert float(np.percentile(d, 99)) <= 0.75 * 0.25


def test_smooth_sphere_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    v, f = _sphere()
    off = _remesh(v, f, monkeypatch, guard=False)
    on = _remesh(v, f, monkeypatch, guard=True)
    assert on.snap.get("crease_eased", 0) == 0
    assert np.array_equal(on.positions, off.positions)


def test_other_targets_and_frozen_vertices_are_not_eased() -> None:
    before = np.random.default_rng(3).normal(size=(30, 3))
    after = before + 1.0
    faces = np.array([[i, i + 1, i + 2] for i in range(0, 27, 3)], dtype=np.int64)
    out, n = S.ease_creases(before, after, faces, np.zeros(30, dtype=bool))
    assert n == 0 and np.array_equal(out, after)


def test_plane_snapped_floor_stays_flat() -> None:
    """바닥을 자른 판: 자른 면(평면)에 붙은 꼭짓점은 접힘 막기가 끌어올리지 않는다."""
    v, f = _sphere()
    rm = remesh(v, f, pitch=0.25, snap_to_source=True, floor_cut_mm=3.0)
    z0 = rm.positions[:, 2].min()
    flat = np.abs(rm.positions[:, 2] - z0) < 1e-6
    assert flat.sum() > 50
    chk = check_printable(Mesh(rm.positions, rm.faces))
    assert chk["printable"]["ok"], chk["printable"]


# --- 2차(11-20 아침): 털 — 대표가 본 「까실까실」은 날카로운 접힘 수가 아니라 이음매를 따라 번갈아 선 잔가시였다 ---

def _remesh2(pos: np.ndarray, faces: np.ndarray, monkeypatch: pytest.MonkeyPatch, hairs: bool):
    if not hairs:
        monkeypatch.setattr(S, "smooth_hairs", lambda p, f, m, **k: (p, 0))
    try:
        return remesh(pos, faces, pitch=0.25, snap_to_source=True)
    finally:
        monkeypatch.undo()


def test_seam_hairs_are_smoothed(monkeypatch: pytest.MonkeyPatch) -> None:
    v, f = _stack()
    off = _remesh2(v, f, monkeypatch, hairs=False)
    on = _remesh2(v, f, monkeypatch, hairs=True)
    n_off = int((S.hair_ratio(off.positions, off.faces) > 0.3).sum())
    n_on = int((S.hair_ratio(on.positions, on.faces) > 0.3).sum())
    assert n_off >= 200, f"모양이 털을 만들지 못했다 — 시험이 아무것도 안 잰다({n_off})"  # 11-20 실측 636
    assert n_on <= n_off * 0.2, (n_off, n_on)  # 11-20 실측 36
    assert on.snap["hair_smoothed"] > 0
    chk = check_printable(Mesh(on.positions, on.faces))
    assert chk["printable"]["ok"], chk["printable"]
    _, d = S.MeshSurface(v, f, 0.5).closest(on.positions)
    d = np.where(np.isfinite(d), d, 0.5)
    assert float(np.percentile(d, 99)) <= 0.75 * 0.25


def test_hair_ratio_is_zero_on_a_smooth_ball_and_finds_a_spike() -> None:
    v, f = _sphere()
    assert float(S.hair_ratio(v, f).max()) < 0.1
    spiky = v.copy()
    k = len(v) // 2
    spiky[k] += (spiky[k] - spiky.mean(axis=0)) / np.linalg.norm(spiky[k] - spiky.mean(axis=0)) * 0.6
    h = S.hair_ratio(spiky, f)
    assert h[k] > 0.3 and int((h > 0.3).sum()) <= 7  # 가시 하나와 그 둘레만


def test_hairs_on_unmovable_vertices_stay() -> None:
    v, f = _sphere()
    spiky = v.copy()
    k = len(v) // 2
    spiky[k] += (spiky[k] - spiky.mean(axis=0)) / np.linalg.norm(spiky[k] - spiky.mean(axis=0)) * 0.6
    out, n = S.smooth_hairs(spiky, f, np.zeros(len(v), dtype=bool))
    assert n == 0 and np.array_equal(out, spiky)
    out, n = S.smooth_hairs(spiky, f, np.ones(len(v), dtype=bool))
    assert n > 0 and S.hair_ratio(out, f)[k] < 0.25
