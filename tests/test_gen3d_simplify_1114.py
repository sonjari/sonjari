"""프린트용 면 줄이기(ADR-3D-2) — 사다리 · 닫힘 · 오차 · 부품 없음 (2026-11-14).

11-14 실측: 부품(pyfqmr)은 면 수에 따라 들쭉날쭉하게 닫힘을 깼고(캐릭터 60만에서도 6), 닫혀 있어도 한 곳이 1mm 무너진
판이 있었다(배 30만). 그래서 가짜 줄이기 도구로 그 경우들을 하나씩 만들어 사다리가 걸러 내는지 본다.
"""
from __future__ import annotations

import sys

import numpy as np
import pytest

from alture_jarvis.gen3d.simplify import _closest_dist, closed_ok, deviation, simplify_closed, surface_distance


def _box(lo=(0.0, 0.0, 0.0), hi=(20.0, 20.0, 20.0)) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], dtype=float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    return v, f


def _subdivide(v: np.ndarray, f: np.ndarray, times: int) -> tuple[np.ndarray, np.ndarray]:
    """삼각형마다 넷으로(이음 꼭짓점은 합치지 않는다 — 겉 모양만 같으면 된다)."""
    for _ in range(times):
        a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        tris = np.stack([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1)], 1)
        v = tris.reshape(-1, 3)
        f = np.arange(len(v)).reshape(-1, 3)
    return v, f


# ── 거리 자 ───────────────────────────────────────────────────────────────
def test_distance_counterexamples() -> None:
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0.0]])
    f = np.array([[0, 1, 2]])
    d = surface_distance(np.array([[0.2, 0.2, 0.5], [2, 0, 0], [0.5, 0.5, 0], [-1, -1, 0], [0.5, -1, 0]]), pos, f, reach=5)
    assert np.allclose(d, [0.5, 1.0, 0.0, 2 ** 0.5, 1.0])
    d = surface_distance(np.array([[0.2, 0.2, 0.5], [0.2, 0.2, 0.4]]), pos, f, reach=0.45)
    assert np.isinf(d[0]) and np.isclose(d[1], 0.4)  # reach 를 넘으면 inf


def test_distance_matches_brute_force_on_random_triangles() -> None:
    rng = np.random.default_rng(3)
    for _ in range(200):
        a, b, c = rng.normal(size=(3, 3))
        p = rng.normal(size=3) * 2
        u = rng.random((20000, 2))
        m = u.sum(1) > 1
        u[m] = 1 - u[m]
        brute = np.linalg.norm(a + (b - a) * u[:, :1] + (c - a) * u[:, 1:] - p, axis=1).min()
        got = _closest_dist(p[None], a[None], b[None], c[None])[0]
        assert got <= brute + 1e-9 and brute - got < 0.05


def test_far_points_count_as_infinite() -> None:
    """이웃 칸 안에 삼각형이 없으면 inf — 「멀다」를 0 으로 잘못 세면 무너진 곳을 놓친다."""
    v, f = _box()
    assert np.isinf(surface_distance(np.array([[100.0, 100.0, 100.0], [10.0, 10.0, 20.6]]), v, f)).all()
    # 큰 평면 삼각형(20mm) 가운데 바로 위 — 무게중심에서 멀어도 찾아야 한다(11-14 자의 구멍)
    assert np.allclose(surface_distance(np.array([[3.0, 17.0, 20.1], [10.0, 10.0, 19.9]]), v, f), [0.1, 0.1])


# ── 닫힘 ─────────────────────────────────────────────────────────────────
def test_closed_ok_catches_holes_and_flips() -> None:
    v, f = _box()
    assert closed_ok(f) == (True, 0)
    assert not closed_ok(f[1:])[0]  # 구멍
    flipped = f.copy()
    flipped[0] = flipped[0][::-1]
    assert not closed_ok(flipped)[0]  # 뒤집힌 면
    assert not closed_ok(np.concatenate([f, f[:2]]))[0]  # 가장자리에 면 셋(꼬임)


# ── 사다리 ────────────────────────────────────────────────────────────────
def _fine_box() -> tuple[np.ndarray, np.ndarray]:
    return _subdivide(*_box(), times=4)  # 12 × 256 = 3,072면


def test_ladder_skips_open_and_shifted_results_and_takes_the_first_good_one() -> None:
    pos, faces = _fine_box()
    good_v, good_f = _box()
    calls: list[tuple[int, int]] = []

    def fake(p: np.ndarray, f: np.ndarray, target: int, agg: int) -> tuple[np.ndarray, np.ndarray]:
        calls.append((target, agg))
        n = len(calls)
        if n == 1:
            return good_v, good_f[1:]  # 구멍
        if n == 2:
            return good_v + np.array([0, 0, 1.0]), good_f  # 닫혔지만 1mm 무너짐
        if n == 3:
            raise RuntimeError("부품 터짐")
        return good_v, good_f

    r = simplify_closed(pos, faces, decimate=fake, skip_below=0)
    whys = [t.get("why") or t.get("error") for t in r.tried]
    assert whys[0].startswith("닫힘 깨짐") and whys[1] == "오차 문턱 넘음" and "부품 터짐" in whys[2]
    assert r.used is not None and len(r.faces) == 12 and r.used["max"] <= 0.15
    ratios = [row["ratio"] for row in r.tried]
    assert ratios == sorted(ratios) and ratios[0] < ratios[-1]  # 많이 줄이기부터 덜 줄이기로
    assert not r.notes


def test_when_every_step_fails_the_original_is_kept_and_said() -> None:
    pos, faces = _fine_box()
    v, f = _box()
    r = simplify_closed(pos, faces, decimate=lambda p, ff, t, a: (v + 2.0, f), skip_below=0)
    assert r.used is None and r.faces is faces and len(r.tried) > 1
    assert any("그대로" in n for n in r.notes)


def test_missing_part_keeps_the_original(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pyfqmr", None)  # import 하면 ImportError
    pos, faces = _fine_box()
    r = simplify_closed(pos, faces, skip_below=0)
    assert r.faces is faces and any("pyfqmr" in n for n in r.notes)


def test_small_meshes_are_left_alone() -> None:
    pos, faces = _fine_box()
    r = simplify_closed(pos, faces, decimate=lambda *a: (_ for _ in ()).throw(AssertionError("부르면 안 됨")))
    assert r.faces is faces and not r.tried and not r.notes


def test_deviation_is_two_sided() -> None:
    """한쪽만 재면 「작은 쪽이 큰 쪽 겉 위에 있다」로 0 이 나온다 — 큰 상자의 반쪽 판도 걸려야 한다."""
    big_v, big_f = _subdivide(*_box(), times=3)
    half = big_f[: len(big_f) // 2]
    d = deviation(big_v, big_f, big_v, half, n=4000)
    assert d["max"] > 1.0


# ── 진짜 부품(있을 때만) ──────────────────────────────────────────────────
def test_real_part_on_a_remeshed_sphere_stays_closed_and_close() -> None:
    pytest.importorskip("pyfqmr")
    from alture_jarvis.gen3d.remesh import remesh

    # 구(반지름 15mm)를 거칠게 만들어 다시 뜬다 → 칸 0.2 로 수십만 면
    th, ph = np.meshgrid(np.linspace(0, np.pi, 60), np.linspace(0, 2 * np.pi, 120), indexing="ij")
    pts = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1).reshape(-1, 3) * 15
    idx = np.arange(60 * 120).reshape(60, 120)
    a, b, c, d = idx[:-1, :], np.roll(idx, -1, 1)[:-1, :], idx[1:, :], np.roll(idx, -1, 1)[1:, :]
    faces = np.concatenate([np.stack([a, c, b], -1).reshape(-1, 3), np.stack([b, c, d], -1).reshape(-1, 3)])
    rm = remesh(pts, faces, pitch=0.35, smooth_rounds=4)  # 0.2 면 85초 — 시험은 굵게
    r = simplify_closed(rm.positions, rm.faces, skip_below=0)
    assert r.used is not None, r.tried
    assert closed_ok(r.faces)[0] and len(r.faces) < len(rm.faces) * 0.5
