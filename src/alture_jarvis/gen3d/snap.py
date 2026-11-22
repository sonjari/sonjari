"""겉면 다시 붙이기 — 칸으로 다시 뜬 꼭짓점을 「자기가 온 면」 위로 되돌린다(설계 `설계_조립부품나누기` §4-2).

11-14 첫 실물: 원래 모델 옆면은 매끈한데(기울기 흔들림 1.4°) 0.35mm 칸으로 다시 뜨자 계단 잔물결이 생겼다(6.1°) ·
다듬기를 40번 해도 6.3°. 연결(면 짜임)은 그대로 두고 위치만 옮기므로 닫힘은 그대로다.

붙일 곳(가장 가까운 것 하나):
- 원래 메시 표면(삼각형 위 가장 가까운 점)
- 평면(자른 면) · 원기둥 벽(핀 구멍) · 원판(구멍 바닥) — 조립 나누기에서 쓴다

붙이지 않는 것: `frozen` 표시된 꼭짓점(가는 곳 굵게 한 자리 — 일부러 원래보다 굵다).
접힘 막기: 붙인 뒤 뒤집히거나 찌그러진 면의 꼭짓점은 붙이기 전 자리로 되돌린다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

PAIR_BATCH = 4_000_000  # 꼭짓점 × 후보 삼각형 짝을 한 번에 이만큼까지(메모리)


def closest_on_triangles(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """점마다 짝지은 삼각형 위의 가장 가까운 점(에릭슨 「Real-Time Collision Detection」 5.1.5 을 배열로)."""
    ab, ac, ap = b - a, c - a, p - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(denom != 0, vb / denom, 0.0)
        w = np.where(denom != 0, vc / denom, 0.0)
    out = a + ab * v[:, None] + ac * w[:, None]  # 안쪽

    def put(mask: np.ndarray, val: np.ndarray) -> None:
        out[mask] = val[mask]

    # 가장자리 · 꼭짓점 구역(뒤에 둔 것이 이긴다 — 에릭슨 순서의 거꾸로)
    with np.errstate(divide="ignore", invalid="ignore"):
        # 가장자리 BC
        m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        t = np.where(m, (d4 - d3) / ((d4 - d3) + (d5 - d6)), 0.0)
        put(m, b + (c - b) * t[:, None])
        # 가장자리 AC
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        t = np.where(m, d2 / (d2 - d6), 0.0)
        put(m, a + ac * t[:, None])
        # 가장자리 AB
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        t = np.where(m, d1 / (d1 - d3), 0.0)
        put(m, a + ab * t[:, None])
    put((d6 >= 0) & (d5 <= d6), c)
    put((d3 >= 0) & (d4 <= d3), b)
    put((d1 <= 0) & (d2 <= 0), a)
    return out


class Target(Protocol):
    def closest(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(가장 가까운 점, 거리) — 닿지 않으면 거리 inf."""


@dataclass
class MeshSurface:
    """원래 메시 표면. 삼각형을 칸(크기 = 찾는 반지름)에 나눠 담아 꼭짓점마다 자기 칸만 본다."""
    pos: np.ndarray
    faces: np.ndarray
    radius: float
    _keys: np.ndarray = field(init=False, repr=False)
    _tris: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.pos = np.asarray(self.pos, dtype=np.float64)
        self.faces = np.asarray(self.faces, dtype=np.int64)
        h = float(self.radius)
        t = self.pos[self.faces]
        lo = np.floor((t.min(axis=1) - h) / h).astype(np.int64)
        hi = np.floor((t.max(axis=1) + h) / h).astype(np.int64)
        span = hi - lo + 1
        n = span.prod(axis=1)
        tri = np.repeat(np.arange(len(self.faces)), n)
        k = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
        sx, sy = span[tri, 0], span[tri, 1]
        cell = lo[tri] + np.stack([k % sx, (k // sx) % sy, k // (sx * sy)], axis=1)
        keys = self._hash(cell)
        order = np.argsort(keys, kind="stable")
        self._keys, self._tris = keys[order], tri[order]

    @staticmethod
    def _hash(cell: np.ndarray) -> np.ndarray:
        c = cell + (1 << 20)
        return (c[:, 0] << 42) | (c[:, 1] << 21) | c[:, 2]

    def closest(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        p = np.asarray(p, dtype=np.float64)
        best_q = p.copy()
        best_d = np.full(len(p), np.inf)
        if not len(p) or not len(self.faces):
            return best_q, best_d
        keys = self._hash(np.floor(p / self.radius).astype(np.int64))
        start = np.searchsorted(self._keys, keys, side="left")
        stop = np.searchsorted(self._keys, keys, side="right")
        cnt = stop - start
        i0 = 0
        while i0 < len(p):
            # 짝 수가 PAIR_BATCH 를 넘지 않게 꼭짓점을 묶는다
            csum = np.cumsum(cnt[i0:])
            i1 = i0 + max(1, int(np.searchsorted(csum, PAIR_BATCH, side="right")))
            sel = np.arange(i0, min(i1, len(p)))
            c = cnt[sel]
            if c.sum():
                vid = np.repeat(sel, c)
                off = np.arange(int(c.sum())) - np.repeat(np.cumsum(c) - c, c)
                tid = self._tris[np.repeat(start[sel], c) + off]
                f = self.faces[tid]
                q = closest_on_triangles(p[vid], self.pos[f[:, 0]], self.pos[f[:, 1]], self.pos[f[:, 2]])
                d = np.linalg.norm(q - p[vid], axis=1)
                # 꼭짓점마다 가장 짧은 것
                order = np.lexsort((d, vid))
                first = np.ones(len(order), dtype=bool)
                first[1:] = vid[order][1:] != vid[order][:-1]
                win = order[first]
                best_d[vid[win]] = d[win]
                best_q[vid[win]] = q[win]
            i0 = int(sel[-1]) + 1
        best_d[best_d > self.radius] = np.inf
        return best_q, best_d


@dataclass
class Plane:
    """평면(자른 면). `within` 이 있으면 그 안의 점만(예: 단면 상자)."""
    point: np.ndarray
    normal: np.ndarray
    radius: float
    within: Any = None

    def closest(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = np.asarray(self.normal, dtype=np.float64)
        n = n / np.linalg.norm(n)
        s = (p - np.asarray(self.point, dtype=np.float64)) @ n
        q = p - s[:, None] * n
        d = np.abs(s)
        d[d > self.radius] = np.inf
        if self.within is not None:
            d[~self.within(q)] = np.inf
        return q, d


@dataclass
class Cylinder:
    """원기둥 벽(핀 구멍). 축 위 [t0, t1] 사이만."""
    center: np.ndarray
    axis: np.ndarray
    r: float
    t0: float
    t1: float
    radius: float

    def closest(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a = np.asarray(self.axis, dtype=np.float64)
        a = a / np.linalg.norm(a)
        rel = p - np.asarray(self.center, dtype=np.float64)
        t = rel @ a
        radial = rel - t[:, None] * a
        rl = np.linalg.norm(radial, axis=1)
        safe = np.where(rl > 1e-9, rl, 1.0)
        q = np.asarray(self.center) + t[:, None] * a + radial / safe[:, None] * self.r
        d = np.abs(rl - self.r)
        d[(t < self.t0) | (t > self.t1) | (rl < 1e-9) | (d > self.radius)] = np.inf
        return q, d


@dataclass
class Disk:
    """원판(구멍 바닥 · 핀 끝)."""
    center: np.ndarray
    normal: np.ndarray
    r: float
    radius: float

    def closest(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = np.asarray(self.normal, dtype=np.float64)
        n = n / np.linalg.norm(n)
        rel = p - np.asarray(self.center, dtype=np.float64)
        s = rel @ n
        q = p - s[:, None] * n
        d = np.abs(s)
        inside = np.linalg.norm(q - np.asarray(self.center), axis=1) <= self.r + 1e-9
        d[(~inside) | (d > self.radius)] = np.inf
        return q, d


@dataclass
class Cone:
    """구멍 끝 고깔(11-16): 바닥 원(가운데 base · 반지름 r)에서 axis 쪽으로 높이 h 에 꼭짓점.
    판을 향해 열린 구멍의 천장을 평평한 원판 대신 이걸로 — 45°면 슬라이서가 지지대 없이 쌓는다."""
    base: np.ndarray
    axis: np.ndarray
    r: float
    h: float
    radius: float

    def closest(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a = np.asarray(self.axis, dtype=np.float64)
        a = a / np.linalg.norm(a)
        rel = p - np.asarray(self.base, dtype=np.float64)
        t = rel @ a
        radial = rel - t[:, None] * a
        rl = np.linalg.norm(radial, axis=1)
        # (둘레 거리 s, 축 t) 평면에서 선분 (r,0)–(0,h) 위 가장 가까운 점
        f = np.clip(((rl - self.r) * -self.r + t * self.h) / (self.r ** 2 + self.h ** 2), 0.0, 1.0)
        s_q, t_q = self.r * (1 - f), self.h * f
        safe = np.where(rl > 1e-9, rl, 1.0)
        q = np.asarray(self.base) + t_q[:, None] * a + radial / safe[:, None] * s_q[:, None]
        d = np.hypot(rl - s_q, t - t_q)
        d[(rl < 1e-9) | (d > self.radius)] = np.inf
        return q, d


@dataclass
class SnapResult:
    positions: np.ndarray
    snapped: int
    frozen: int
    reverted: int
    by_target: dict[str, int]
    crease_eased: int = 0
    hair_smoothed: int = 0

    def receipt(self) -> dict[str, Any]:
        out = {"snapped": self.snapped, "frozen": self.frozen, "reverted": self.reverted, "by_target": self.by_target}
        if self.crease_eased:
            out["crease_eased"] = self.crease_eased
        if self.hair_smoothed:
            out["hair_smoothed"] = self.hair_smoothed
        return out


#: 접힘 막기(11-20 대표 「까실까실」): 붙인 뒤 이웃 면과 이 각보다 꺾이고, 붙이기 전보다 CREASE_GAIN 넘게 더 꺾인 모서리.
CREASE_DEG = 75.0
CREASE_GAIN = 30.0


def edge_dihedral(pos: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """모서리마다 (두 면 법선 사이 각(도), 면 a, 면 b). 같은 면 짜임이면 순서가 늘 같다(위치만 바뀐 메시끼리 견줄 수 있다)."""
    fn = _face_normals(pos, faces)
    fn = fn / np.maximum(np.linalg.norm(fn, axis=1), 1e-20)[:, None]
    e = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    fid = np.tile(np.arange(len(faces)), 3)
    key = e[:, 0] * (int(faces.max()) + 2 if len(faces) else 1) + e[:, 1]
    order = np.argsort(key, kind="stable")
    key, fid = key[order], fid[order]
    same = key[1:] == key[:-1]
    a, b = fid[:-1][same], fid[1:][same]
    ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", fn[a], fn[b]), -1.0, 1.0)))
    return ang, a, b


def ease_creases(before: np.ndarray, after: np.ndarray, faces: np.ndarray, movable: np.ndarray,
                 deg: float = CREASE_DEG, gain: float = CREASE_GAIN, rounds: int = 6,
                 relax_rounds: int = 2) -> tuple[np.ndarray, int]:
    """붙이기가 새로 만든 날카로운 접힘을 푼다(11-20 햄버거 곰).

    오목한 골(햄버거 층 사이 · 팔다리 이음매 · 아래 테두리)에서는 양쪽 꼭짓점이 원래 모델의 골선 하나로 몰려 바늘 같은
    삼각형이 줄지어 접힌다 — 뒤집히지도 넓이가 1/10 아래로 줄지도 않아 접힘 되돌리기에 안 걸린다. 실측(곰 · 칸 0.304mm):
    90° 넘게 꺾인 모서리 붙이기 전 19 → 붙인 뒤 735. 그런 모서리의 꼭짓점을 반씩 덜 붙이고(몇 번), 덜 붙인 꼭짓점과
    한 고리 이웃만 이웃 평균 쪽으로 펴 계단을 메운다. `movable` 밖 꼭짓점(자른 면 · 핀 구멍 · 바닥 평면 · 굵힌 자리)은
    일부러 만든 각이라 건드리지 않는다. 돌려주는 것: (새 위치, 손댄 꼭짓점 수)."""
    if not len(faces):
        return after, 0
    movable = np.asarray(movable, dtype=bool)
    ang0, _, _ = edge_dihedral(before, faces)
    t = np.ones(len(before))
    out = after.copy()
    for _ in range(rounds):
        ang, a, b = edge_dihedral(out, faces)
        bad = (ang > deg) & (ang - ang0 > gain)
        if not bad.any():
            break
        v = np.unique(np.concatenate([faces[a[bad]].ravel(), faces[b[bad]].ravel()]))
        v = v[movable[v] & (t[v] > 0)]
        if not len(v):
            break
        t[v] *= 0.5
        t[t < 0.07] = 0.0
        out = before + (after - before) * t[:, None]
    touched = t < 1
    if touched.any() and relax_rounds:
        e = np.unique(np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1), axis=0)
        i, j = np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]])
        deg_n = np.maximum(np.bincount(i, minlength=len(out)), 1).astype(np.float64)[:, None]
        ring = touched.copy()
        ring[i[touched[j]]] = True
        ring &= movable
        for _ in range(relax_rounds):
            acc = np.zeros_like(out)
            np.add.at(acc, i, out[j])
            out[ring] += 0.5 * (acc[ring] / deg_n[ring] - out[ring])
    return out, int(touched.sum())

#: 털 펴기(11-20 2차): 꼭짓점이 한 고리 이웃 평균에서 법선 쪽으로 튀어나온 거리 ÷ 이웃 모서리 평균 길이가 이보다 크면 「털」.
#: 대표가 뱀부에서 본 「까실까실」(볼 · 코 · 목 · 햄버거 테두리 이음매의 잔가시)을 이 눈금이 잡는 것을 그림으로 확인했다
#: (매끈한 머리 · 몸엔 안 걸림). 곰 실측: 0.3 넘는 꼭짓점 1,712(붙이기만) → 857(접힘 막기) → 23(+ 털 펴기).
#: 3차(11-20 아침): 0.25 로는 팔 이음매 · 눈 둘레의 옅은 털이 남아 0.15 로 — 곰 0.15 넘는 털 3,807 → 901 ·
#: 원본 거리 99% 0.063 → 0.098mm(층 0.2mm 보다 작음) · 시간 같음.
HAIR_RATIO = 0.15


def _ring_edges(faces: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    e = np.unique(np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1), axis=0)
    i, j = np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]])
    deg = np.maximum(np.bincount(i, minlength=n), 1).astype(np.float64)
    return i, j, deg


def hair_ratio(pos: np.ndarray, faces: np.ndarray, ring: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None) -> np.ndarray:
    """꼭짓점마다 「털」 정도 — 이웃 평균에서 법선 쪽으로 튀어나온 거리 ÷ 이웃 모서리 평균 길이."""
    i, j, deg = ring if ring is not None else _ring_edges(faces, len(pos))
    acc = np.zeros_like(pos)
    np.add.at(acc, i, pos[j])
    avg = acc / deg[:, None]
    el = np.bincount(i, weights=np.linalg.norm(pos[i] - pos[j], axis=1), minlength=len(pos)) / deg
    vn = vertex_normals(pos, faces)
    return np.abs(np.einsum("ij,ij->i", pos - avg, vn)) / np.maximum(el, 1e-12)


def smooth_hairs(pos: np.ndarray, faces: np.ndarray, movable: np.ndarray, ratio: float = HAIR_RATIO,
                 passes: int = 6, inner: int = 3) -> tuple[np.ndarray, int]:
    """붙인 겉에 남은 털(이음매를 따라 번갈아 선 잔가시)만 이웃 평균 쪽으로 편다(11-20 2차).

    오목한 이음매의 둥근 자리에서는 이웃 꼭짓점이 서로 다른 면(머리 · 볼 옆벽)에 갈려 붙어 지그재그 이빨이 선다 —
    날카로운 접힘 수(90°)로는 안 잡히고 털 눈금으로 잡힌다. 털과 한 고리 이웃만, `movable`(원래 메시 겉에 붙은 꼭짓점)만.
    돌려주는 것: (새 위치, 손댄 꼭짓점 수)."""
    if not len(faces):
        return pos, 0
    movable = np.asarray(movable, dtype=bool)
    ring = _ring_edges(faces, len(pos))
    i, j, deg = ring
    out = pos.copy()
    touched = np.zeros(len(pos), dtype=bool)
    for _ in range(passes):
        h = (hair_ratio(out, faces, ring) > ratio) & movable
        if not h.any():
            break
        m = h.copy()
        m[i[h[j]]] = True
        m &= movable
        touched |= m
        for _ in range(inner):
            acc = np.zeros_like(out)
            np.add.at(acc, i, out[j])
            out[m] += 0.6 * (acc[m] / deg[m][:, None] - out[m])
    return out, int(touched.sum())


def _face_normals(pos: np.ndarray, faces: np.ndarray) -> np.ndarray:
    t = pos[faces]
    return np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])


def vertex_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    fn = _face_normals(verts, faces)
    vn = np.zeros_like(verts)
    for k in range(3):
        np.add.at(vn, faces[:, k], fn)
    return vn / np.maximum(np.linalg.norm(vn, axis=1), 1e-12)[:, None]


def snap(verts: np.ndarray, faces: np.ndarray, targets: dict[str, Target], frozen: np.ndarray | None = None,
         fold_rounds: int = 4, edge_mm: float = 0.0, exclude: dict[str, np.ndarray] | None = None,
         crease_guard: bool = False) -> SnapResult:
    """꼭짓점마다 가장 가까운 붙일 곳으로 옮긴다. 붙인 뒤 뒤집히거나 넓이가 1/10 아래로 줄어든 면은 되돌린다.
    `crease_guard` 면 원래 메시 겉에 붙은 꼭짓점이 새로 만든 날카로운 접힘도 푼다(`ease_creases`)."""
    verts = np.asarray(verts, dtype=np.float64)
    out = verts.copy()
    best_d = np.full(len(verts), np.inf)
    second_d = np.full(len(verts), np.inf)
    who = np.full(len(verts), -1)
    who2 = np.full(len(verts), -1)
    names = list(targets)
    for i, name in enumerate(names):
        q, d = targets[name].closest(verts)
        if exclude and name in exclude:
            # 이 면에 붙으면 안 되는 꼭짓점(예: 파낸 구멍 벽은 원래 모델의 속 면에 붙지 않는다 — 11-14 눈사람)
            d = np.where(exclude[name], np.inf, d)
        take = d < best_d
        # 둘째로 가까운 곳: 새로 1등이 되면 옛 1등이 2등으로
        demote = take & np.isfinite(best_d)
        second_d[demote], who2[demote] = best_d[demote], who[demote]
        runner = ~take & (d < second_d)
        second_d[runner], who2[runner] = d[runner], i
        out[take], best_d[take], who[take] = q[take], d[take], i
    # 두 면이 만나는 모서리(구멍 벽 ↔ 바닥 · 자른 면 ↔ 원래 겉): 둘 다 가까우면 번갈아 붙여 만나는 선 위로.
    # 11-14 눈사람: 하나만 고르면 모서리 삼각형이 접혀 701개가 되돌려졌고 구멍 벽이 0.136mm 어긋났다.
    edge = np.isfinite(second_d) & (second_d < edge_mm) & (who2 >= 0)
    if edge.any():
        for a_i, b_i in {(int(a), int(b)) for a, b in zip(who[edge], who2[edge])}:
            sel = np.nonzero(edge & (who == a_i) & (who2 == b_i))[0]
            q = verts[sel].copy()
            ok = np.ones(len(sel), dtype=bool)
            for _ in range(8):
                qa, da = targets[names[a_i]].closest(q)
                qb, db = targets[names[b_i]].closest(qa)
                if exclude:
                    for nm, dd in ((names[a_i], da), (names[b_i], db)):
                        if nm in exclude:
                            dd[exclude[nm][sel]] = np.inf
                ok &= np.isfinite(da) & np.isfinite(db)
                q = np.where(ok[:, None], qb, q)
            out[sel[ok]] = q[ok]
    if frozen is not None:
        fz = np.asarray(frozen, dtype=bool)
        out[fz] = verts[fz]
        who[fz] = -1
    else:
        fz = np.zeros(len(verts), dtype=bool)
    eased = haired = 0
    on_mesh = movable = np.zeros(len(verts), dtype=bool)
    if crease_guard:
        on_mesh = np.zeros(len(verts), dtype=bool)
        for i, name in enumerate(names):
            if isinstance(targets[name], MeshSurface):
                on_mesh |= who == i
        # 두 면이 만나는 모서리 꼭짓점(edge)은 일부러 맞춘 선이라 건드리지 않는다
        movable = on_mesh & ~fz & ~edge
        out, eased = ease_creases(verts, out, faces, movable)
    before = _face_normals(verts, faces)
    area0 = np.linalg.norm(before, axis=1)
    reverted = np.zeros(len(verts), dtype=bool)
    for _ in range(fold_rounds):
        after = _face_normals(out, faces)
        bad = (np.einsum("ij,ij->i", before, after) <= 0) | (np.linalg.norm(after, axis=1) < 0.1 * area0)
        bad &= area0 > 0
        if not bad.any():
            break
        idx = np.unique(faces[bad].ravel())
        idx = idx[~reverted[idx] | (np.linalg.norm(out[idx] - verts[idx], axis=1) > 0)]
        if not len(idx):
            break
        out[idx] = verts[idx]
        reverted[idx] = True
        who[idx] = -1
    if crease_guard:
        # 털 펴기는 뒤집힘 되돌리기 **뒤에**(11-20: 앞에 두면 되돌린 꼭짓점이 계단 자리로 돌아가 털이 다시 선다 — 곰 털 23 → 475).
        # 되돌린 꼭짓점도 원래 메시 겉 자리였으면 편다. 펴기가 새로 뒤집은 면만 펴기 전 자리로.
        hair_ok = (movable | (reverted & on_mesh)) & ~fz & ~edge
        pre = out.copy()
        out, haired = smooth_hairs(out, faces, hair_ok)
        for _ in range(fold_rounds):
            after = _face_normals(out, faces)
            bad = (np.einsum("ij,ij->i", before, after) <= 0) & (area0 > 0)
            if not bad.any():
                break
            idx = np.unique(faces[bad].ravel())
            idx = idx[np.linalg.norm(out[idx] - pre[idx], axis=1) > 0]
            if not len(idx):
                break
            out[idx] = pre[idx]
    moved = who >= 0
    by = {n: int((who == i).sum()) for i, n in enumerate(names)}
    return SnapResult(out, int(moved.sum()), int(fz.sum()), int(reverted.sum()), by, crease_eased=eased, hair_smoothed=haired)
