"""나누기 경로의 바닥 자르기 — 자른 바닥이 평평하게 남는가 (2026-11-16).

★ 11-16 리락쿠마 몸통: 나눌 때 바닥을 3mm 잘라도, 붙이기가 자른 바닥 꼭짓점을 원래 엉덩이 겉으로 끌어내려 맨 아래
0.3mm 안 평면이 2.7mm² 뿐이었다(한 판 경로는 11-15 에 같은 병을 고쳤다 · `remesh` 의 floor 붙일 곳). 시험 자료는 공 도형만."""
from __future__ import annotations

import numpy as np

from alture_jarvis.gen3d.assembly import Cut, split_model
from test_gen3d_snap_1114 import _sphere


def _floor_area(part: dict) -> float:
    """놓인 부품에서 원래 바닥(모델 아래 방향) 쪽 맨 끝 평면 넓이."""
    rot = np.asarray(part["rotation"])
    fn = rot @ np.array([0.0, 0.0, -1.0])
    pos, faces = np.asarray(part["positions"]), np.asarray(part["faces"])
    d = pos @ fn
    t = pos[faces]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    a = 0.5 * np.linalg.norm(n, axis=1)
    nz = (n @ fn) / np.maximum(2 * a, 1e-12)
    flat = (d[faces].min(axis=1) > d.max() - 0.05) & (nz > 0.99)
    return float(a[flat].sum())


def _bottom(parts: list[dict]) -> dict:
    """모델 자리에서 가장 낮은 부품(laid = model @ rotation.T - shift 를 되짚음)."""
    def low(p):
        return float(((np.asarray(p["positions"]) + np.asarray(p["shift"])) @ np.asarray(p["rotation"]))[:, 2].min())
    return min(parts, key=low)


def test_split_keeps_the_cut_floor_flat():
    pos, faces = _sphere(10.0, 64)  # 가운데 (12,12,12) · z 2~22
    out = split_model(pos, faces, [Cut(np.array([12.0, 12, 15]), np.array([0, 0, 1.0]), "허리")], pitch=0.3,
                      floor_cut_mm=3.0, simplify=False)
    bottom = _bottom(out["parts"])
    expect = np.pi * (10 ** 2 - 7 ** 2)  # 자른 높이 z=5 → 반지름 √51 원 ≈ 160mm²
    got = _floor_area(bottom)
    assert got > 0.8 * expect, (got, expect)
    assert out["remesh"]["floor_cut_mm"] > 2.5


def test_no_floor_cut_means_no_floor_plane():
    pos, faces = _sphere(10.0, 64)
    out = split_model(pos, faces, [Cut(np.array([12.0, 12, 15]), np.array([0, 0, 1.0]), "허리")], pitch=0.3,
                      simplify=False)
    bottom = _bottom(out["parts"])
    assert _floor_area(bottom) < 20  # 둥근 바닥 그대로(평면 없음)
