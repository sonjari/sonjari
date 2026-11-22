"""조립 부품으로 나눠 뽑기 · 끼움 시험 조각 (2026-11-14 · 설계 `docs/설계_조립부품나누기_2026-11-14.ko.md`).

클로드는 「어디를 왜 나눌지」만 정한다(자르는 평면 = 한 점 + 방향). 손자리가 전부 계산하고 검사한다:
- 자르기는 **칸 격자 위**에서 — 그 점을 지나는 단면 한 조각만 끊고(평면이 팔 같은 다른 곳을 지나가도 거긴 안 자름),
  양쪽을 채워 번져 두 부품으로 가른다. 부품마다 늘 닫힌 메시.
- 끼움은 **양쪽 구멍 + 따로 뽑은 핀**(부품은 잘린 평평한 면을 판에 붙여 뽑을 수 있고, 핀은 세워 뽑아 둥글다).
- 구멍 지름 · 깊이는 벽 두께(1.6mm)를 지키는 자리에서만. 못 지키면 작은 핀 → 핀 하나 → 「핀 자리 없음」으로 물러난다.
- 뜬 겉면은 자기가 온 면(원래 겉 · 자른 평면 · 구멍 원기둥 · 구멍 바닥)에 다시 붙인다 — 구멍 지름이 칸 크기에 안 묶인다.

숫자의 처음 값(벽 1.6 · 틈 0.2 · 핀 3~8mm)은 짐작이다 — 끼움 시험 조각(`fit_coupon`)과 실물로 고친다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .remesh import _box_pass, _marching_tets, taubin_smooth
from .snap import Cone, Cylinder, Disk, MeshSurface, Plane, snap

WALL_MM = 1.6          # 구멍 둘레 · 바닥에 남길 벽(가는 곳 굵게와 같은 기준)
GAP_MM = 0.4           # 구멍 바닥 여유(공기 · 접착제) — 핀은 구멍 깊이보다 이만큼 짧다
CHAMFER_MM = 0.4       # 핀 끝 모따기
CLEARANCE_MM = 0.2     # 틈 기본값(지름이 아니라 반지름 쪽 한 면) — 맞춤 시험 조각으로 고친다
PIN_SIZES = (8.0, 6.0, 5.0, 4.0, 3.0)
MIN_ENGAGE = 1.0       # 핀이 한쪽 구멍에 들어가는 깊이 ≥ 지름 × 이것
MAX_ENGAGE = 1.5       # … ≤ 지름 × 이것
PLATE_MM = 250.0       # 판 한 변에서 쓸 수 있는 길이(가장자리 여유 뺀 값 · 썰기가 실제 판으로 다시 잰다)
PLATE_GAP_MM = 6.0
TINY_PIECE_MM3 = 100.0  # 이보다 작은 떨어진 조각은 부품으로 안 내고 버린다(메모에 적음)
TALL_RATIO_MAX = 3.0    # 높이 ÷ 바닥 짧은 폭이 이걸 넘으면 쓰러질 위험 — 눕히는 쪽을 고른다
#: 자른 면을 판에 대는 방향을 고르는 너그러움(11-16) — 그 방향 점수가 가장 좋은 것의 이 배 + 이만큼(mm²) 안이면 자른 면.
CUT_FACE_DOWN_SLACK = 1.3
CUT_FACE_DOWN_EXTRA_MM2 = 50.0
#: 핀 구멍 끝을 이 각(수평에서)의 고깔로 판다(11-16 곰 머리: 자른 면을 판에 대니 구멍이 아래로 열려 평평한 천장 53.6mm² 가
#: 허공에 떴고, 뱀부가 구멍 안을 바닥부터 천장까지 지지대 60층으로 채웠다 — 떼기도 어렵고 핀이 안 들어간다).
#: 뱀부 기준각 30° 보다 서 있으면 지지대 없이 쌓인다. 고깔 높이 = 구멍 반지름 × tan(이 각).
ROOF_DEG = 45.0
#: 구멍마다 뱀부 「지지대 금지」 부피(구멍보다 반지름 이만큼 굵고, 입구 · 끝을 조금 넘게) — 고깔을 못 판 구멍 · 비스듬한
#: 구멍에도 지지대가 안 자라게. 11-16 실측: 곰 머리 그대로에 이 부피만 넣어 썰니 구멍 안 지지대 60층 → 0층.
BLOCKER_MARGIN_MM = 0.2
_PART_ARRAYS = ("positions", "faces", "rotation", "shift", "blockers")  # 영수증에 안 싣는 배열
MAX_TRIES = 60         # 핀 자리 후보를 깊은(먼) 순으로 이만큼만 재 본다(11-14 배: 전부 재느라 179초)
FIT_FILE = "printer_fit.json"


# ── 작은 도구 ──────────────────────────────────────────────────────────
def _unit(v: Any) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        raise ValueError("방향(normal)이 0 이다")
    return v / n


def _basis(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = _unit(np.cross(n, a))
    return u, np.cross(n, u)


def rotation_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a 를 b 로 돌리는 회전 행렬(로드리게스)."""
    a, b = _unit(a), _unit(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        u, _ = _basis(a)
        return 2 * np.outer(u, u) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k * (1 / (1 + c))


def _centres(origin: np.ndarray, pitch: float, cells: np.ndarray) -> np.ndarray:
    return origin + (cells + 0.5) * pitch


def _flood(mask: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """seeds 에서 mask 안으로 번진 칸(6-이웃). 다시 뜨기의 바깥 훑기를 그대로 쓴다: 「껍질 = mask 밖」으로 보고 씨앗에서 훑는다."""
    # _sweep_outside 는 격자 테두리에서 번진다 — 씨앗을 쓰려고 테두리 대신 씨앗을 넣은 판을 따로 돈다.
    reach = seeds & mask
    for _ in range(4096):
        before = int(reach.sum())
        for axis in range(3):
            s = np.moveaxis(~mask, axis, -1)
            r = np.moveaxis(reach, axis, -1)
            length = s.shape[-1]
            lines = s.reshape(-1, length)
            seg = np.cumsum(lines, axis=1, dtype=np.int32)
            free = ~lines
            rl = r.reshape(-1, length)
            key = np.arange(lines.shape[0], dtype=np.int64)[:, None] * (length + 1) + seg
            hit = np.zeros(lines.shape[0] * (length + 1), dtype=bool)
            hit[key[rl & free]] = True
            grown = free & hit[key]
            np.moveaxis(reach, axis, -1)[...] = grown.reshape(r.shape) | r
        if int(reach.sum()) == before:
            break
    return reach


# ── 자르기 ────────────────────────────────────────────────────────────
@dataclass
class Cut:
    point: np.ndarray
    normal: np.ndarray
    name: str = ""

    @classmethod
    def parse(cls, raw: dict[str, Any], i: int) -> Cut:
        try:
            p = np.asarray(raw["point"], dtype=np.float64).reshape(3)
            n = _unit(np.asarray(raw.get("normal") or [0, 0, 1], dtype=np.float64).reshape(3))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"cuts[{i}] 는 {{point:[x,y,z], normal:[x,y,z]}} — {exc}") from exc
        return cls(p, n, str(raw.get("name") or f"자르기{i + 1}"))


@dataclass
class Pin:
    centre: np.ndarray       # 자른 평면 위 핀 가운데(mm)
    axis: np.ndarray         # 자르기 normal(＋쪽 부품으로 들어감)
    d: float                 # 핀 지름
    hole_r: float            # 구멍 반지름(= d/2 + 틈)
    depth_plus: float        # ＋쪽 구멍 깊이
    depth_minus: float       # －쪽 구멍 깊이
    plus_id: int = 0         # 핀이 꽂히는 ＋쪽 부품(여러 조각이면 그 조각)
    minus_id: int = 0
    roof_plus: bool = False  # ＋쪽 구멍 끝이 고깔인가(벽이 모자라면 평평)
    roof_minus: bool = False

    @property
    def length(self) -> float:
        return round(self.depth_plus + self.depth_minus - 2 * GAP_MM, 2)

    def receipt(self) -> dict[str, Any]:
        return {"d_mm": self.d, "hole_d_mm": round(2 * self.hole_r, 3), "length_mm": self.length,
                "hole_depth_mm": [round(self.depth_plus, 2), round(self.depth_minus, 2)],
                "hole_end": ["고깔" if self.roof_plus else "평평", "고깔" if self.roof_minus else "평평"],
                "at_mm": [round(float(v), 2) for v in self.centre]}


@dataclass
class CutResult:
    cut: Cut
    plus: int                # ＋쪽 부품 번호
    minus: int
    section_mm2: float
    pins: list[Pin] = field(default_factory=list)
    contact_mm2: float = 0.0  # 두 부품이 실제로 맞닿는 넓이(접착 면)
    extra_parts: list[int] = field(default_factory=list)  # 한쪽이 여러 조각으로 갈려 새로 생긴 부품 번호
    plus_ids: list[int] = field(default_factory=list)   # ＋쪽 부품들(여러 조각이면 여럿)
    minus_ids: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _section_depth(points_uv: np.ndarray, pitch: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """단면 점(평면 좌표)을 2D 칸으로 찍고, 칸마다 가장자리까지 깊이(mm). 돌려주는 것: (칸 가운데 uv, 깊이, 칸 마스크 원점)."""
    lo = points_uv.min(axis=0) - 2 * pitch
    # 반올림: 축에 맞는 평면이면 칸 가운데가 격자점에 딱 떨어진다(내림은 소수점 오차로 칸이 숭숭 빈다 — 11-14 눈사람 0.5mm).
    idx = np.rint((points_uv - lo) / pitch).astype(np.int64)
    dims = idx.max(axis=0) + 3
    grid = np.zeros(tuple(dims), dtype=bool)
    grid[idx[:, 0], idx[:, 1]] = True
    # 비스듬한 평면은 찍힌 점이 격자에 안 맞아 작은 틈이 생긴다 — 닫힘(불렸다 깎기) 한 번으로 메운다.
    grown = grid.copy()
    grown[1:] |= grid[:-1]
    grown[:-1] |= grid[1:]
    grown[:, 1:] |= grid[:, :-1]
    grown[:, :-1] |= grid[:, 1:]
    closed = grown.copy()
    closed[1:] &= grown[:-1]
    closed[:-1] &= grown[1:]
    closed[:, 1:] &= grown[:, :-1]
    closed[:, :-1] &= grown[:, 1:]
    grid |= closed
    depth = np.zeros(grid.shape, dtype=np.float64)
    cur = grid.copy()
    k = 0
    while cur.any():
        k += 1
        depth[cur] = k
        nxt = cur.copy()
        nxt[1:] &= cur[:-1]
        nxt[:-1] &= cur[1:]
        nxt[:, 1:] &= cur[:, :-1]
        nxt[:, :-1] &= cur[:, 1:]
        nxt[0] = nxt[-1] = False
        nxt[:, 0] = nxt[:, -1] = False
        cur = nxt
    cells = np.argwhere(grid)
    uv = lo + (cells + 0.5) * pitch
    return uv, (depth[grid] - 0.5) * pitch, lo


class _Parts:
    """부품 번호 격자 + 칸 → 부품 찾기."""

    def __init__(self, solid: np.ndarray, origin: np.ndarray, pitch: float) -> None:
        self.label = np.where(solid, 1, 0).astype(np.int16)
        self.origin = np.asarray(origin, dtype=np.float64)
        self.pitch = float(pitch)
        self.count = 1

    def at(self, pts: np.ndarray) -> np.ndarray:
        idx = np.floor((pts - self.origin) / self.pitch).astype(np.int64)
        ok = ((idx >= 0) & (idx < np.array(self.label.shape))).all(axis=1)
        out = np.zeros(len(pts), dtype=np.int16)
        out[ok] = self.label[idx[ok, 0], idx[ok, 1], idx[ok, 2]]
        return out

    def signed(self, cut: Cut) -> np.ndarray:
        """칸 가운데의 평면까지 부호 거리 — 격자 전체(float32)."""
        nx, ny, nz = self.label.shape
        p = self.pitch
        o = self.origin - cut.point
        n = cut.normal
        x = (o[0] + (np.arange(nx) + 0.5) * p) * n[0]
        y = (o[1] + (np.arange(ny) + 0.5) * p) * n[1]
        z = (o[2] + (np.arange(nz) + 0.5) * p) * n[2]
        return (x[:, None, None] + y[None, :, None] + z[None, None, :]).astype(np.float32)


def split_cells(parts: _Parts, cut: Cut) -> CutResult:
    """그 점을 지나는 단면 한 조각만 끊어 그 점이 든 부품을 둘로 가른다."""
    from .remesh import cell_components

    p = parts.pitch
    owner = int(parts.at(cut.point[None])[0])
    sd = parts.signed(cut)
    if owner == 0:
        # 점이 비어 있는 칸(겉면 위를 찍음)이면 단면에서 가장 가까운 안 칸의 부품
        slab_any = (np.abs(sd) < 0.75 * p) & (parts.label > 0)
        cells = np.argwhere(slab_any)
        if not len(cells):
            raise ValueError(f"{cut.name}: 이 평면은 모델을 지나지 않는다")
        near = np.argmin(np.linalg.norm(_centres(parts.origin, p, cells) - cut.point, axis=1))
        owner = int(parts.label[tuple(cells[near])])
    part = parts.label == owner
    slab = part & (np.abs(sd) < 0.75 * p)
    cells, lab = cell_components(slab)
    if not len(cells):
        raise ValueError(f"{cut.name}: 이 평면은 그 부품을 지나지 않는다")
    centres = _centres(parts.origin, p, cells)
    pick = lab[np.argmin(np.linalg.norm(centres - cut.point, axis=1))]
    sect = cells[lab == pick]
    sever = np.zeros_like(part)
    sever[tuple(sect.T)] = True
    rest = part & ~sever
    # 씨앗: 끊은 칸의 ＋ · － 쪽 이웃
    step = np.round(cut.normal * 2).astype(np.int64)  # 두 칸 건너 — 비스듬해도 판 밖으로 나가게
    seeds_p = np.zeros_like(part)
    seeds_m = np.zeros_like(part)
    for sgn, seeds in ((1, seeds_p), (-1, seeds_m)):
        nb = np.clip(sect + sgn * step, 0, np.array(part.shape) - 1)
        seeds[tuple(nb.T)] = True
    seeds_p &= rest & (sd > 0)
    seeds_m &= rest & (sd < 0)
    if not seeds_p.any() or not seeds_m.any():
        raise ValueError(f"{cut.name}: 단면 한쪽이 비었다 — 모델 끝을 스치는 자르기")
    a = _flood(rest, seeds_p)
    if (a & seeds_m).any():
        raise ValueError(f"{cut.name}: 이 단면을 끊어도 두 쪽이 다른 길로 이어져 있다(고리 모양) — 나뉘지 않는다")
    b = _flood(rest, seeds_m)
    left = rest & ~a & ~b
    notes: list[str] = []
    if left.any():
        # 단면을 끊으며 떨어져 나간 작은 조각 — 붙은 쪽이 없으면 버리지 않고 알린다
        vol = float(left.sum()) * p ** 3
        notes.append(f"{cut.name}: 어느 쪽에도 안 이어진 조각 {vol:.0f}mm³ 이 생겼다 — 큰 쪽(＋)에 붙였다")
        a |= left
    a |= sever & (sd >= 0)
    b |= sever & (sd < 0)
    new_id = parts.count + 1
    parts.count = new_id
    parts.label[b] = new_id  # － 쪽에 새 번호, ＋ 쪽은 원래 번호
    # 한쪽이 여러 조각이면(11-14 배 갑판: 돛 묶음 · 선실 · 밧줄 끝이 갑판으로만 이어져 있어 6조각) 조각마다 따로 부품.
    extra: list[int] = []
    side_ids: dict[int, list[int]] = {owner: [owner], new_id: [new_id]}
    for side_mask, side_id in ((a, owner), (b, new_id)):
        comps = _split_components(side_mask)
        if len(comps) <= 1:
            continue
        comps.sort(key=lambda c: -len(c))
        # 아주 작은 조각(갑판 윗면 부스러기 · 11-14 배 0.7mm × 42mm³)은 버리고 메모에 적는다 — 반대쪽에 붙였더니
        # 갑판 면보다 0.7mm 솟아 선체를 뒤집어 놓을 때 판에 닿는 면이 그 부스러기가 됐다(받침 58 → 1,292mm²).
        tiny = [c for c in comps[1:] if len(c) * p ** 3 < TINY_PIECE_MM3]
        for cells in tiny:
            parts.label[tuple(cells.T)] = 0
        if tiny:
            notes.append(f"{cut.name}: 자른 자리의 작은 부스러기 {len(tiny)}개({sum(len(c) for c in tiny) * p ** 3:.0f}mm³)는 버렸다")
        comps = [comps[0]] + [c for c in comps[1:] if len(c) * p ** 3 >= TINY_PIECE_MM3]
        if len(comps) <= 1:
            continue
        for cells in comps[1:]:  # 가장 큰 조각이 원래 번호를 지킨다
            parts.count += 1
            parts.label[tuple(cells.T)] = parts.count
            extra.append(parts.count)
            side_ids[side_id].append(parts.count)
        vols = [round(len(c) * p ** 3) for c in comps]
        notes.append(f"{cut.name}: {'＋' if side_id == owner else '－'}쪽이 {len(comps)}조각으로 갈렸다(부피 mm³ {vols}) — "
                     "조각마다 따로 뽑아 붙인다. 원치 않으면 더 좁은 자리(밑동)에서 잘라라")
    area = float(len(sect)) * p ** 3 / (0.75 * 2 * p)  # 판 두께(1.5칸)로 나눈 넓이(대략)
    return CutResult(cut, owner, new_id, round(area, 1), notes=notes, extra_parts=extra,
                     plus_ids=side_ids[owner], minus_ids=side_ids[new_id])


def _split_components(mask: np.ndarray) -> list[np.ndarray]:
    """참인 칸의 덩이들(칸 좌표 목록) — 덩이 상자로 잘라 다룬다(격자 전체를 안 씀)."""
    from .remesh import cell_components

    idx = np.argwhere(mask)
    if not len(idx):
        return []
    lo, hi = idx.min(axis=0), idx.max(axis=0) + 1
    sub = mask[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
    cells, lab = cell_components(sub)
    return [cells[lab == k] + lo for k in np.unique(lab)]


def _hole_depth(parts: _Parts, part_id: int, centre: np.ndarray, axis: np.ndarray, hole_r: float,
                limit: float) -> float:
    """centre 에서 axis 쪽으로 반지름 hole_r 구멍을 얼마나 깊이 팔 수 있나 — 둘레 · 바닥에 벽 WALL_MM 이 남는 데까지."""
    u, v = _basis(axis)
    ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    ring_r = hole_r + WALL_MM
    rings = [centre + np.outer(np.cos(ang), u) * r + np.outer(np.sin(ang), v) * r for r in (ring_r, ring_r * 0.5)]
    ring = np.vstack([*rings, centre[None]])
    p = parts.pitch
    best = 0.0
    t = p
    while t <= limit + 1e-9:
        wall_pts = ring + axis * t
        bottom = ring + axis * (t + WALL_MM)
        if (parts.at(wall_pts) != part_id).any() or (parts.at(bottom) != part_id).any():
            break
        best = t
        t += p
    # 자른 면 바로 옆(0 ~ 첫 칸)은 단면 자체 — 둘레 벽만 본다
    if (parts.at(centre + np.outer(np.cos(ang), u) * ring_r + np.outer(np.sin(ang), v) * ring_r + axis * (0.5 * p))
            != part_id).any():
        return 0.0
    return best


def roof_h(hole_r: float) -> float:
    """고깔 높이 — 겉이 수평에서 ROOF_DEG 만큼 서도록(45° 면 반지름과 같다)."""
    return float(hole_r * np.tan(np.radians(ROOF_DEG)))


def fit_roof(parts: _Parts, part_id: int, centre: np.ndarray, axis: np.ndarray, hole_r: float, depth: float,
             min_depth: float) -> tuple[float, bool]:
    """깊이 depth 인 구멍 끝에 고깔(+ 고깔 둘레 벽 WALL_MM)이 그 부품 살 안에 들어가나. 안 들어가면 원기둥을 한 칸씩 줄여
    min_depth 까지 본다. 돌려주는 것: (원기둥 깊이 · 고깔인가) — 끝내 안 되면 (depth, False) = 평평한 천장(예전 그대로)."""
    u, v = _basis(axis)
    ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    dirs = np.outer(np.cos(ang), u) + np.outer(np.sin(ang), v)
    h = roof_h(hole_r)
    out_n = (dirs * h + axis * hole_r) / np.hypot(h, hole_r)  # 고깔 겉의 바깥 방향
    t = depth
    while t >= min_depth - 1e-9:
        pts = [(centre + axis * (t + h + WALL_MM))[None]]  # 꼭짓점 너머
        for f in (0.0, 0.25, 0.5, 0.75):
            ring = centre + axis * (t + h * f) + dirs * (hole_r * (1 - f))
            pts.append(ring + out_n * WALL_MM)
        if (parts.at(np.vstack(pts)) == part_id).all():
            return t, True
        t -= parts.pitch
    return depth, False


def place_pins(parts: _Parts, res: CutResult, clearance: float, pin_d: float | None = None) -> None:
    """단면에서 핀 자리 · 크기 · 깊이를 고른다(결정론). 못 찾으면 res.notes 에 까닭."""
    cut = res.cut
    p = parts.pitch
    sd = parts.signed(cut)
    u, v = _basis(cut.normal)
    # 핀은 양쪽 다 살이 있는 자리에만 — 11-14 배 갑판: 아래(선체) 단면은 넓은데 위(돛 · 선실)는 작은 발 몇 개뿐이라
    # 아래 단면만 보고 고른 자리는 위가 빈 공중이었다. ＋쪽 바로 위 칸과 －쪽 바로 아래 칸을 따로 찍어 겹치는 곳만 쓴다.
    from .remesh import cell_components

    sides = []
    # 끊은 한 겹(|sd| < 0.75칸)은 건너뛰고 그 너머를 본다 — 11-14 배: 끊은 선체 맨 윗장이 위 부품에 붙어 갑판 전체가
    # 「맞닿는 면」으로 잡혔고, 위가 빈 공중인 36만 자리를 하나씩 재느라 179초를 쓰고 핀을 못 놓았다.
    for ids, lo_t, hi_t in ((res.plus_ids, 0.75 * p, 2.25 * p), (res.minus_ids, -2.25 * p, -0.75 * p)):
        near = (sd >= lo_t) & (sd < hi_t) & np.isin(parts.label, ids)
        cells = np.argwhere(near)
        if not len(cells):
            res.notes.append(f"{cut.name}: 단면 한쪽이 비어 핀을 못 놓는다")
            return
        centres = _centres(parts.origin, p, cells)
        rel = centres - cut.point
        sides.append(np.stack([rel @ u, rel @ v], axis=1))
    lo = np.minimum(sides[0].min(axis=0), sides[1].min(axis=0)) - 2 * p
    grids = []
    dims = np.ceil((np.maximum(sides[0].max(axis=0), sides[1].max(axis=0)) - lo) / p).astype(int) + 3
    for uv_side in sides:
        g = np.zeros(tuple(dims), dtype=bool)
        idx = np.rint((uv_side - lo) / p).astype(np.int64)
        g[idx[:, 0], idx[:, 1]] = True
        grids.append(g)
    both = np.argwhere(grids[0] & grids[1])
    if not len(both):
        res.notes.append(f"{cut.name}: 두 부품이 맞닿는 면이 없어 핀을 못 놓는다")
        return
    uv = lo + both * p
    # 자르는 점이 든 덩이만(평면이 다른 데를 지나도)
    cells2 = np.concatenate([both, np.zeros((len(both), 1), dtype=np.int64)], axis=1)
    mask2 = np.zeros((*dims, 1), dtype=bool)
    mask2[cells2[:, 0], cells2[:, 1], 0] = True
    cc, lab = cell_components(mask2)
    cuv_all = lo + cc[:, :2] * p
    # 맞닿는 면이 여러 조각이면(배: 선실 발 · 기둥 발 · 밧줄 발) 조각마다 깊이를 따로 재서 합친다 —
    # 첫 핀은 가장 깊은 곳, 둘째 핀은 거기서 가장 먼 곳(다른 조각일 수 있다).
    cuv_parts, depth_parts = [], []
    for k in np.unique(lab):
        a, b, _ = _section_depth(cuv_all[lab == k], p)
        cuv_parts.append(a)
        depth_parts.append(b)
    cuv, depth = np.vstack(cuv_parts), np.concatenate(depth_parts)
    res.contact_mm2 = round(float(len(both)) * p * p, 1)
    max_depth = float(depth.max())
    sizes = [pin_d] if pin_d else [d for d in PIN_SIZES if d / 2 + clearance + WALL_MM <= max_depth]
    if not sizes:
        res.notes.append(f"{cut.name}: 단면이 좁아(가장 깊은 곳 {max_depth:.1f}mm) 핀 자리가 없다 — 판판한 면을 접착제로 붙인다")
        return
    for d in sizes:
        hole_r = d / 2 + clearance
        need = hole_r + WALL_MM
        ok = depth >= need
        if not ok.any():
            continue
        cand = cuv[ok]
        cdepth = depth[ok]
        # 양쪽 부품 속으로 곧게 몇 mm 들어갈 수 있나(가운데 줄 하나 · 한꺼번에) — 깊이가 모자라는 자리는 미리 뺀다.
        # 11-14 배: 단면 안쪽 깊이만 보고 고르니 위가 얇은 판인 자리만 앞에 와서 핀을 못 놓았다.
        need_len = d * MIN_ENGAGE + GAP_MM + WALL_MM
        steps = np.arange(1, int(np.ceil((d * MAX_ENGAGE + GAP_MM + WALL_MM) / p)) + 1) * p
        c3s = cut.point + np.outer(cand[:, 0], u) + np.outer(cand[:, 1], v)
        cols = []
        for ids, ax_vec in ((res.plus_ids, cut.normal), (res.minus_ids, -cut.normal)):
            pts = c3s[:, None, :] + steps[None, :, None] * ax_vec
            inside = np.isin(parts.at(pts.reshape(-1, 3)), ids).reshape(len(cand), len(steps))
            run = np.where(inside.all(axis=1), len(steps), np.argmin(inside, axis=1))
            cols.append(run * p)
        reach = np.minimum(cols[0], cols[1])
        good = reach >= need_len
        if not good.any():
            continue
        cand, cdepth, reach = cand[good], cdepth[good], reach[good]
        # 첫 핀: 양쪽으로 가장 깊이 들어가는 곳 → 단면 안쪽 깊이 → 무게중심에 가까운 곳
        centroid = cuv.mean(axis=0)
        order = np.lexsort((np.linalg.norm(cand - centroid, axis=1), -cdepth, -reach))[:MAX_TRIES]
        chosen: list[np.ndarray] = []
        for i in order:
            c3 = cut.point + cand[i, 0] * u + cand[i, 1] * v
            pid_p = int(parts.at((c3 + cut.normal * 1.5 * p)[None])[0])
            pid_m = int(parts.at((c3 - cut.normal * 1.5 * p)[None])[0])
            dp = _hole_depth(parts, pid_p, c3, cut.normal, hole_r, d * MAX_ENGAGE + GAP_MM) if pid_p in res.plus_ids else 0.0
            dm = _hole_depth(parts, pid_m, c3, -cut.normal, hole_r, d * MAX_ENGAGE + GAP_MM) if pid_m in res.minus_ids else 0.0
            if min(dp, dm) - GAP_MM >= d * MIN_ENGAGE:
                chosen.append(np.array([cand[i, 0], cand[i, 1], dp, dm, pid_p, pid_m]))
                break
        if not chosen:
            continue
        # 둘째 핀(돌지 않게): 첫 핀에서 가장 먼 자리 — 두 구멍 사이 벽이 남게
        first = chosen[0]
        far = np.linalg.norm(cand - first[:2], axis=1)
        for i in np.argsort(-far)[:MAX_TRIES]:
            if far[i] < 2 * hole_r + WALL_MM:
                break
            c3 = cut.point + cand[i, 0] * u + cand[i, 1] * v
            pid_p = int(parts.at((c3 + cut.normal * 1.5 * p)[None])[0])
            pid_m = int(parts.at((c3 - cut.normal * 1.5 * p)[None])[0])
            dp = _hole_depth(parts, pid_p, c3, cut.normal, hole_r, d * MAX_ENGAGE + GAP_MM) if pid_p in res.plus_ids else 0.0
            dm = _hole_depth(parts, pid_m, c3, -cut.normal, hole_r, d * MAX_ENGAGE + GAP_MM) if pid_m in res.minus_ids else 0.0
            if min(dp, dm) - GAP_MM >= d * MIN_ENGAGE:
                chosen.append(np.array([cand[i, 0], cand[i, 1], dp, dm, pid_p, pid_m]))
                break
        for c in chosen:
            c3 = cut.point + c[0] * u + c[1] * v
            need = d * MIN_ENGAGE + GAP_MM
            dp, rp = fit_roof(parts, int(c[4]), c3, cut.normal, hole_r, float(c[2]), need)
            dm, rm_ = fit_roof(parts, int(c[5]), c3, -cut.normal, hole_r, float(c[3]), need)
            res.pins.append(Pin(c3, cut.normal.copy(), d, hole_r, dp, dm, int(c[4]), int(c[5]), rp, rm_))
            if not (rp and rm_):
                res.notes.append(f"{cut.name}: 핀 구멍 끝 하나를 고깔로 못 팠다(벽 {WALL_MM:g}mm 가 모자람) — 그 구멍이 판을 향하면 "
                                 "천장이 평평해 지지대가 들어갈 수 있다")
        if len(chosen) == 1:
            res.notes.append(f"{cut.name}: 핀이 하나만 들어간다 — 돌 수 있으니 접착제를 같이 쓴다")
        return
    res.notes.append(f"{cut.name}: 벽 {WALL_MM:g}mm 를 남기는 핀 자리가 없다 — 판판한 면을 접착제로 붙인다")


def carve_holes(parts: _Parts, res: CutResult) -> None:
    """핀 구멍을 양쪽 부품에서 비운다."""
    if not res.pins:
        return
    shape = np.array(parts.label.shape)
    p = parts.pitch
    for pin in res.pins:
        for part_id, axis, depth, roof in ((pin.plus_id or res.plus, pin.axis, pin.depth_plus, pin.roof_plus),
                                           (pin.minus_id or res.minus, -pin.axis, pin.depth_minus, pin.roof_minus)):
            r = pin.hole_r
            h = roof_h(r) if roof else 0.0
            end = pin.centre + axis * (depth + h)
            lo = np.floor((np.minimum(pin.centre, end) - r - p - parts.origin) / p).astype(int)
            hi = np.ceil((np.maximum(pin.centre, end) + r + p - parts.origin) / p).astype(int)
            lo, hi = np.clip(lo, 0, shape - 1), np.clip(hi, 0, shape)
            ii, jj, kk = np.meshgrid(*(np.arange(lo[a], hi[a]) for a in range(3)), indexing="ij")
            cells = np.stack([ii.ravel(), jj.ravel(), kk.ravel()], axis=1)
            rel = _centres(parts.origin, p, cells) - pin.centre
            t = rel @ axis
            radial = np.linalg.norm(rel - np.outer(t, axis), axis=1)
            inside = (t > -p) & (t <= depth) & (radial <= r)
            if roof:  # 고깔: 원기둥 끝에서 반지름이 h 동안 0 으로
                inside |= (t > depth) & (t <= depth + h) & (radial <= r * (1 - (t - depth) / h))
            sel = cells[inside]
            # 그 부품의 칸만 비운다(자른 면 바로 앞 칸이 다른 부품 것이면 그 부품을 팔 때 비워진다)
            sel = sel[parts.label[tuple(sel.T)] == part_id]
            parts.label[tuple(sel.T)] = 0


def hole_blocker(centre: np.ndarray, axis: np.ndarray, hole_r: float, depth: float, roof: bool
                 ) -> tuple[np.ndarray, np.ndarray]:
    """구멍을 감싸는 원기둥(지지대 금지 부피) — 모델 자리. 입구 앞 0.6mm 부터 끝(고깔 꼭짓점) 너머 0.3mm 까지."""
    axis = _unit(axis)
    length = 0.6 + depth + (roof_h(hole_r) if roof else 0.0) + 0.3
    pv, pf = cylinder_mesh(2 * (hole_r + BLOCKER_MARGIN_MM), length, chamfer=0.0, segments=32)
    rot = rotation_to(np.array([0, 0, 1.0]), axis)
    return pv @ rot.T + (np.asarray(centre, dtype=np.float64) - axis * 0.6), pf


def to_laid(mesh: tuple[np.ndarray, np.ndarray], made: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """모델 자리 → 그 부품을 판에 놓은 자리(mesh_part 의 rotation · shift)."""
    return mesh[0] @ made["rotation"].T - made["shift"], mesh[1]


def hole_end_target(key: str, end: np.ndarray, axis: np.ndarray, hole_r: float, roof: bool, radius: float) -> dict[str, Any]:
    """구멍 끝 붙일 곳 — 고깔이면 Cone, 아니면 평평한 원판."""
    if roof:
        return {f"roof{key}": Cone(end, axis, hole_r, roof_h(hole_r), radius)}
    return {f"bottom{key}": Disk(end, axis, hole_r, radius)}


# ── 메시 만들기 ───────────────────────────────────────────────────────
def mesh_cells(solid: np.ndarray, origin: np.ndarray, pitch: float, targets: dict[str, Any],
               frozen_cells: np.ndarray | None = None, smooth_rounds: int = 8,
               whole: np.ndarray | None = None, floor_z: float | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    verts, faces = _marching_tets(solid, origin, pitch)
    if not len(verts):
        return verts, faces, {}
    if smooth_rounds:
        verts = taubin_smooth(verts, faces, rounds=smooth_rounds)
    return snap_again(verts, faces, origin, pitch, solid.shape, targets, frozen_cells, whole, floor_z)


def snap_again(verts: np.ndarray, faces: np.ndarray, origin: np.ndarray, pitch: float, shape: tuple[int, ...],
               targets: dict[str, Any], frozen_cells: np.ndarray | None = None,
               whole: np.ndarray | None = None, floor_z: float | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    """붙이기(모서리는 두 면이 만나는 선으로). 면 줄이기 뒤에 한 번 더 부른다 — 줄이기가 옮긴 꼭짓점을 다시 제자리로.

    `whole` = 나누기 전 모델 전체의 안 칸. 꼭짓점에서 바깥으로 반 칸 나간 자리가 `whole` 안이면 파낸 면(자른 면 · 구멍)이라
    원래 표면에 붙이지 않는다 — 원래 모델에 속 면이 있으면(겹친 공 · 트렐리스 결과) 구멍 벽이 거기로 끌려가 접혔다."""
    frozen = None
    lim = np.array(shape) - 1
    if frozen_cells is not None and frozen_cells.any():
        near = _box_pass(_box_pass(frozen_cells, grow=True), grow=True)
        cell = np.clip(np.floor((verts - origin) / pitch).astype(np.int64), 0, lim)
        frozen = near[cell[:, 0], cell[:, 1], cell[:, 2]]
    exclude = None
    if whole is not None and "original" in targets:
        from .snap import vertex_normals

        probe = verts + vertex_normals(verts, faces) * (0.6 * pitch)
        cell = np.clip(np.floor((probe - origin) / pitch).astype(np.int64), 0, lim)
        carved = whole[cell[:, 0], cell[:, 1], cell[:, 2]]
        exclude = {"original": carved}
    if floor_z is not None:
        # 바닥 자르기(floor_cut_mm): 자른 바닥은 원래 겉이 아니라 그 평면에 붙인다(한 판 경로 `remesh` 와 같은 규칙).
        # ★ 11-16 리락쿠마 몸통: `whole` 은 바닥을 자른 뒤의 칸이라 위의 「파낸 면」 검사가 바닥을 못 알아봐, 자른 바닥이
        #   원래 엉덩이 쪽으로 끌려 내려갔다(3mm 자름 → 맨 아래 0.3mm 안 평면 2.7mm²).
        from .snap import Plane, vertex_normals

        targets = {**targets, "floor": Plane(np.array([0.0, 0.0, floor_z]), np.array([0.0, 0.0, 1.0]), 1.5 * pitch)}
        vn = vertex_normals(verts, faces)
        on_floor = (np.abs(verts[:, 2] - floor_z) < 0.75 * pitch) & (vn[:, 2] < -0.5)
        exclude = {"original": on_floor | (exclude["original"] if exclude else False)}
    sn = snap(verts, faces, targets, frozen=frozen, edge_mm=0.5 * pitch, exclude=exclude)
    return sn.positions, faces, sn.receipt()


def cylinder_mesh(d: float, length: float, chamfer: float = CHAMFER_MM, segments: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """세워 뽑는 핀(바닥 z=0 · 가운데 x=y=0). 양 끝 모따기."""
    r = d / 2
    c = min(chamfer, r * 0.4, length * 0.2)
    rings = [(0.0, r - c), (c, r), (length - c, r), (length, r - c)]
    ang = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    verts = [np.array([0, 0, 0.0])]
    for z, rr in rings:
        verts += [np.array([rr * np.cos(a), rr * np.sin(a), z]) for a in ang]
    verts.append(np.array([0, 0, length]))
    v = np.array(verts)
    f = []
    top = len(v) - 1
    for j in range(segments):
        k = (j + 1) % segments
        f.append([0, 1 + k, 1 + j])  # 바닥(아래를 봄)
        for ring in range(3):
            a0, a1 = 1 + ring * segments + j, 1 + ring * segments + k
            b0, b1 = a0 + segments, a1 + segments
            f += [[a0, a1, b1], [a0, b1, b0]]
        f.append([top, 1 + 3 * segments + j, 1 + 3 * segments + k])
    return v, np.array(f, dtype=np.int64)


# ── 판 배치 ──────────────────────────────────────────────────────────
def pick_lay(options: list[tuple[float, int, str, Any, float]]) -> tuple[float, int, str, Any, float]:
    """놓는 방향 고르기 — options = (점수, 종류 0=자른 면을 판에 · 1=축 방향, 이름, 회전, 받침 넓이), 점수 작을수록 좋다.
    자른 면 방향이 가장 좋은 것의 `CUT_FACE_DOWN_SLACK` 배 + `CUT_FACE_DOWN_EXTRA_MM2` 안이면 자른 면을 고른다(11-16 머리)."""
    ranked = sorted(options, key=lambda o: (o[0], o[1]))
    best = ranked[0]
    cut_down = [o for o in ranked if o[1] == 0]
    if cut_down and best[1] != 0:
        cand = cut_down[0]
        if cand[0] <= best[0] * CUT_FACE_DOWN_SLACK + CUT_FACE_DOWN_EXTRA_MM2:
            return cand
    return best


def lay_flat(pos: np.ndarray) -> np.ndarray:
    lo, hi = pos.min(axis=0), pos.max(axis=0)
    return pos - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])


def pack_plates(items: list[tuple[str, np.ndarray, np.ndarray]], plate: float = PLATE_MM,
                gap: float = PLATE_GAP_MM) -> list[list[tuple[str, np.ndarray, np.ndarray]]]:
    """선반 쌓기: 큰 것부터 줄마다 왼쪽에서 오른쪽으로. 판 하나에 안 들어가면 다음 판. 판 가운데가 (0,0)."""
    order = sorted(range(len(items)), key=lambda i: -float(np.ptp(items[i][1][:, 1])))
    plates: list[list[tuple[str, np.ndarray, np.ndarray]]] = []
    cursors: list[list[float]] = []  # 판마다 [x, y, 줄 높이]
    for i in order:
        name, pos, faces = items[i]
        w, h = float(np.ptp(pos[:, 0])), float(np.ptp(pos[:, 1]))
        if w > plate or h > plate:
            raise ValueError(f"{name}: {w:.0f}×{h:.0f}mm — 판({plate:g}mm)보다 크다. 더 나누거나 크기를 줄여야 한다")
        placed = False
        for k, cur in enumerate(cursors):
            x, y, row = cur
            if x + w > plate:
                x, y, row = 0.0, y + row + gap, 0.0
            if y + h <= plate:
                lo = pos.min(axis=0)
                moved = pos - np.array([lo[0], lo[1], 0]) + np.array([x - plate / 2, y - plate / 2, 0])
                plates[k].append((name, moved, faces))
                cursors[k] = [x + w + gap, y, max(row, h)]
                placed = True
                break
        if not placed:
            lo = pos.min(axis=0)
            moved = pos - np.array([lo[0], lo[1], 0]) + np.array([-plate / 2, -plate / 2, 0])
            plates.append([(name, moved, faces)])
            cursors.append([w + gap, 0.0, h])
    return plates


# ── 끼움 시험 조각 ───────────────────────────────────────────────────
FIT_CLEARANCES = (0.10, 0.15, 0.20, 0.25, 0.30)


def fit_coupon(pin_d: float = 5.0, clearances: tuple[float, ...] = FIT_CLEARANCES, pitch: float = 0.1
               ) -> dict[str, Any]:
    """구멍 다섯(틈 0.10~0.30mm) 막대 + 핀 하나. 구멍은 왼쪽부터 틈이 작은 순 · 0.10 쪽 윗모서리에 홈 하나(표시)."""
    depth = 7.0
    spacing = pin_d + 2 * max(clearances) + 5.0
    length = spacing * len(clearances) + 4.0
    width, height = pin_d + 2 * max(clearances) + 2 * 4.0, depth + 3.0
    notch = 1.6
    xs = [2.0 + spacing * (i + 0.5) for i in range(len(clearances))]
    lo = np.array([-1.0, -1.0, -1.0])
    dims = np.ceil((np.array([length, width, height]) + 2.0) / pitch).astype(int) + 1
    ii = (np.arange(dims[0]) + 0.5) * pitch + lo[0]
    jj = (np.arange(dims[1]) + 0.5) * pitch + lo[1]
    kk = (np.arange(dims[2]) + 0.5) * pitch + lo[2]
    x, y, z = np.meshgrid(ii, jj, kk, indexing="ij")
    solid = (x >= 0) & (x <= length) & (y >= 0) & (y <= width) & (z >= 0) & (z <= height)
    solid &= ~((x <= notch) & (z >= height - notch))  # 표시 홈: 틈 0.10 쪽
    yc = width / 2
    targets: dict[str, Any] = {}
    big = pitch * 1.5
    for i, (cx, c) in enumerate(zip(xs, clearances)):
        r = pin_d / 2 + c
        solid &= ~(((x - cx) ** 2 + (y - yc) ** 2 <= r ** 2) & (z >= height - depth))
        targets[f"hole{i}"] = Cylinder(np.array([cx, yc, height]), np.array([0, 0, -1.0]), r, 0.0, depth, big)
        targets[f"bottom{i}"] = Disk(np.array([cx, yc, height - depth]), np.array([0, 0, 1.0]), r, big)
    # 상자 여섯 면 + 홈 두 면
    for name, pt, nn in (("x0", (0, 0, 0), (1, 0, 0)), ("x1", (length, 0, 0), (1, 0, 0)),
                         ("y0", (0, 0, 0), (0, 1, 0)), ("y1", (0, width, 0), (0, 1, 0)),
                         ("z0", (0, 0, 0), (0, 0, 1)), ("z1", (0, 0, height), (0, 0, 1)),
                         ("nx", (notch, 0, 0), (1, 0, 0)), ("nz", (0, 0, height - notch), (0, 0, 1))):
        targets[name] = Plane(np.array(pt, dtype=float), np.array(nn, dtype=float), big)
    solid[0], solid[-1], solid[:, 0], solid[:, -1], solid[:, :, 0], solid[:, :, -1] = (False,) * 6
    pos, faces, snapped = mesh_cells(solid, lo, pitch, targets, smooth_rounds=0)
    pin_len = depth - GAP_MM + 5.0  # 구멍에 다 들어가고 5mm 남아 손으로 뺄 수 있게
    pin_v, pin_f = cylinder_mesh(pin_d, pin_len)
    return {"block": (lay_flat(pos), faces), "pin": (pin_v, pin_f), "clearances": list(clearances),
            "pin_d": pin_d, "hole_depth_mm": depth, "pin_length_mm": round(pin_len, 2), "snap": snapped,
            "how": (f"막대의 구멍 다섯은 왼쪽(윗모서리에 홈이 있는 쪽)부터 틈 {', '.join(f'{c:.2f}' for c in clearances)}mm. "
                    "핀을 하나씩 끼워 보고 「손으로 눌러 들어가고 흔들리지 않는」 구멍의 틈을 고른다 — "
                    "안 들어가면 더 큰 틈, 헐거우면 더 작은 틈.")}


def load_fit(root: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((root / FIT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("clearance_mm"), (int, float)) else None


def save_fit(root: Path, clearance_mm: float, printer: str, filament: str, note: str = "") -> dict[str, Any]:
    if not 0.0 <= float(clearance_mm) <= 0.6:
        raise ValueError("clearance_mm 은 0~0.6mm")
    data = {"clearance_mm": round(float(clearance_mm), 3), "printer": printer, "filament": filament,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note}
    root.mkdir(parents=True, exist_ok=True)
    (root / FIT_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def mesh_part(mask: np.ndarray, origin: np.ndarray, pitch: float, targets: dict[str, Any], frozen: np.ndarray | None,
              whole: np.ndarray | None, flat_faces: list[np.ndarray], simplify: bool = True,
              flat_label: str = "자른 면", floor_z: float | None = None) -> dict[str, Any]:
    """칸 덩이 하나 → 붙인 메시 → 면 줄이기 → 받침이 가장 적게 놓기. flat_faces = 판에 붙일 수 있는 평평한 면의 바깥 방향."""
    from .print_plan import _ORIENTS, _overhang_area
    from .simplify import simplify_closed

    ppos, pfaces, snapped = mesh_cells(mask, origin, pitch, targets, frozen_cells=frozen, whole=whole, floor_z=floor_z)
    before = len(pfaces)
    sm_receipt = None
    if simplify and len(pfaces):
        sm = simplify_closed(ppos, pfaces)
        if sm is not None:
            ppos, pfaces, sm_receipt = sm.positions, sm.faces, sm.receipt()
            ppos, pfaces, _ = snap_again(ppos, pfaces, origin, pitch, mask.shape, targets, frozen, whole, floor_z)
    # 놓는 방향: 자른 면을 판에 붙이는 것 + 축 여섯 — 받침이 가장 적은 것(같으면 자른 면)
    options: list[tuple[float, int, str, np.ndarray, float]] = []

    def score(rot: np.ndarray) -> tuple[float, float]:
        # 받침 넓이 + 쓰러질 위험 벌점(11-14 배: 2.5mm 두께 밧줄 삼각형을 61mm 높이로 세워 놓았다 —
        # 오늘 망가진 바로 그 꼴. 눕히면 납작하고 튼튼하다)
        turned = ppos @ rot.T
        area, height = _overhang_area(turned, pfaces)
        short = float(min(np.ptp(turned[:, 0]), np.ptp(turned[:, 1]))) or 1e-6
        tall = height / short
        return area + 1000.0 * max(0.0, tall - TALL_RATIO_MAX), area

    for i, out_n in enumerate(flat_faces):
        rot = rotation_to(out_n, np.array([0, 0, -1.0]))
        s, area = score(rot)
        options.append((round(s, 1), 0, f"{flat_label} {i + 1} 을 판에", rot, round(area, 1)))
    for name, rot in _ORIENTS:
        s, area = score(rot)
        options.append((round(s, 1), 1, name, rot, round(area, 1)))
    options.sort(key=lambda o: (o[0], o[1]))
    # ★ 11-16 리락쿠마 머리: 받침이 조금 적다고(옆 444 대 자른 면 532mm²) 머리를 옆으로 눕혀 얼굴이 옆을 봤다(대표 「얼굴이 왜
    #   돌아가 있노 · 꼭 고쳐야」). 자른 면은 평평하고 조립하면 가려지는 면이라 판 자국이 남아도 된다 — 받침이 가장 좋은 방향의
    #   `CUT_FACE_DOWN_SLACK` 배 이내면 자른 면을 판에 댄다(얼굴 · 겉면이 받침 자국 없이 위로).
    _, _, how, rot, area = pick_lay(options)
    turned = ppos @ rot.T
    laid = lay_flat(turned)
    return {
        "positions": laid, "faces": pfaces, "lay": how, "overhang_mm2": area,
        # 프린트 자리 → 판 자리: laid = model @ rotation.T - shift (시험 · 조립 그림이 되짚는다)
        "rotation": rot, "shift": turned[0] - laid[0],
        "overhang_if_upright_mm2": next(o[4] for o in options if o[2] == "지금 그대로"),
        "size_mm": [round(float(v), 1) for v in np.ptp(laid, axis=0)],
        "volume_mm3": round(float(mask.sum()) * pitch ** 3, 0), "faces_before": before,
        "simplify": sm_receipt, "snap": snapped,
    }


# ── 한 번에 ──────────────────────────────────────────────────────────
def split_model(pos: np.ndarray, faces: np.ndarray, cuts: list[Cut], *, pitch: float = 0.2,
                clearance: float = CLEARANCE_MM, pin_d: float | None = None, thicken_to_mm: float = 1.6,
                min_thickness_mm: float = 1.2, floor_cut_mm: float = 0.0, simplify: bool = True,
                attach: list[Any] | None = None, picture_dir: Path | None = None) -> dict[str, Any]:
    """닫히지 않았을 수도 있는 메시(밀리미터 · 프린트 자리)를 다시 뜬 뒤 cuts 대로 나누고 핀 구멍을 뚫어 부품 메시를 만든다.
    attach = 따로 구운 부품을 앉힐 목록(`attach.Attach` · 설계 §8-6) — 바탕에 홈을 파고 핀을 놓는다.
    돌려주는 것: parts(이름 · 메시 · 놓는 방향 · 재기) · pins · cuts(단면 · 핀 · 메모) · attached · notes."""
    from .remesh import remesh

    attach = list(attach or [])
    if not cuts and not attach:
        raise ValueError("cuts 가 비었다 — 적어도 하나(또는 attach)")
    if len(cuts) > 8:
        raise ValueError("한 번에 8번까지만 자른다(부품 9개)")
    if len(attach) > 4:
        raise ValueError("attach 는 한 번에 넷까지")
    rm = remesh(pos, faces, pitch=pitch, floor_cut_mm=floor_cut_mm, min_thickness_mm=min_thickness_mm,
                thicken_to_mm=thicken_to_mm, keep_grid=True, smooth_rounds=0)
    solid, origin, grown = rm.cells
    pitch = rm.pitch
    floor_z: float | None = None
    if rm.floor_cut_mm > 0 and solid.any():  # 자른 바닥 평면 = 맨 아래 안 칸의 아랫면(remesh 와 같은 자리)
        floor_z = float(origin[2] + np.nonzero(solid.any(axis=(0, 1)))[0][0] * pitch)
    parts = _Parts(solid, origin, pitch)
    results: list[CutResult] = []
    for cut in cuts:
        res = split_cells(parts, cut)
        place_pins(parts, res, clearance, pin_d)
        carve_holes(parts, res)
        results.append(res)
    seats: list[Any] = []
    if attach:
        from .attach import seat_part

        for att in attach:
            seat, solid, grown = seat_part(parts, solid, grown, att, clearance=clearance, pin_d=att.pin_d,
                                           thicken_to_mm=thicken_to_mm, picture_dir=picture_dir,
                                           key=f"seat{len(seats)}", base_mesh=(pos, faces))
            seats.append(seat)
        origin = parts.origin
    radius = (1.5 + rm.shell_thickened) * pitch
    surface = MeshSurface(pos, faces, radius)
    out_parts: list[dict[str, Any]] = []
    notes = list(rm.notes)
    for part_id in range(1, parts.count + 1):
        mask = parts.label == part_id
        if not mask.any():
            continue
        targets: dict[str, Any] = {"original": surface}
        holes: list[tuple[np.ndarray, np.ndarray]] = []  # 지지대 금지 부피(모델 자리)
        cut_faces: list[np.ndarray] = []  # 이 부품의 자른 면 바깥 방향
        for k, res in enumerate(results):
            if part_id not in res.plus_ids and part_id not in res.minus_ids:
                continue
            on_plus = part_id in res.plus_ids
            outward = -res.cut.normal if on_plus else res.cut.normal
            cut_faces.append(outward)
            targets[f"cut{k}"] = Plane(res.cut.point, res.cut.normal, radius)
            for j, pin in enumerate(res.pins):
                if part_id not in (pin.plus_id, pin.minus_id):
                    continue
                axis = pin.axis if on_plus else -pin.axis
                depth = pin.depth_plus if on_plus else pin.depth_minus
                targets[f"hole{k}_{j}"] = Cylinder(pin.centre, axis, pin.hole_r, 0.0, depth, radius)
                roof = pin.roof_plus if on_plus else pin.roof_minus
                targets.update(hole_end_target(f"{k}_{j}", pin.centre + axis * depth, axis, pin.hole_r, roof, radius))
                holes.append(hole_blocker(pin.centre, axis, pin.hole_r, depth, roof))
        for seat in seats:  # 따로 구운 부품을 앉히는 홈 · 그 핀 구멍(설계 §8-6)
            if part_id == seat.seat_id:
                targets.update(seat.base_targets(radius))
                if seat.pin is not None:
                    holes.append(hole_blocker(seat.pin.centre, seat.pin.axis, seat.pin.hole_r, seat.pin.depth_plus,
                                              seat.pin.roof_plus))
        frozen = (grown & mask) if grown is not None else None
        made = mesh_part(mask, origin, pitch, targets, frozen, solid, cut_faces, simplify, floor_z=floor_z)
        made["blockers"] = [to_laid(h, made) for h in holes]
        out_parts.append({"id": part_id, **made})
    pins: list[dict[str, Any]] = []
    for k, res in enumerate(results):
        for pin in res.pins:
            pv, pf = cylinder_mesh(pin.d, pin.length)
            pins.append({"cut": k, "positions": pv, "faces": pf, **pin.receipt()})
        notes += res.notes
    attached = []
    for seat in seats:
        notes += seat.notes
        attached.append(seat.output())
    return {"parts": out_parts, "pins": pins, "attached": attached, "pitch_mm": round(pitch, 4), "remesh": rm.receipt(),
            "cuts": [{"name": r.cut.name, "point": [round(float(v), 2) for v in r.cut.point],
                      "normal": [round(float(v), 3) for v in r.cut.normal], "plus_part": r.plus, "minus_part": r.minus,
                      "plus_parts": r.plus_ids, "minus_parts": r.minus_ids,
                      "section_mm2": r.section_mm2, "contact_mm2": r.contact_mm2, "pins": [p.receipt() for p in r.pins], "notes": r.notes}
                     for r in results],
            "clearance_mm": clearance, "notes": notes}


# ── 판 폴더까지 한 번에 (실행기 · 도구가 부른다) ─────────────────────────
def _merged(objs: list[tuple[str, np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    off, fs = 0, []
    for _, p, f in objs:
        fs.append(f + off)
        off += len(p)
    return np.vstack([p for _, p, _ in objs]), np.vstack(fs)


def _slice_plates(plates: list[list[tuple[str, np.ndarray, np.ndarray]]], out_dir: Path, stem: str, size_mm: float,
                  detail: str, prefs: dict[str, Any], slice_it: bool,
                  blockers: dict[str, tuple[np.ndarray, list[tuple[np.ndarray, np.ndarray]]]] | None = None
                  ) -> list[dict[str, Any]]:
    """blockers = 물체 이름 → (판에 놓기 전 꼭짓점 · 지지대 금지 부피들). 판에 놓으며 옮긴 만큼 같이 옮겨 3MF 에 싣는다."""
    from .print_plan import plan_print
    from .printing import write_3mf_multi
    from .slicer import slice_3mf

    done = []
    for i, plate in enumerate(plates, start=1):
        path = out_dir / f"{stem}_plate{i}.3mf"
        moved_blockers: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
        for name, pos, _ in plate:
            if blockers and blockers.get(name) and blockers[name][1]:
                before, meshes = blockers[name]
                delta = pos[0] - before[0]  # 판 배치는 평행 이동뿐
                moved_blockers[name] = [(bp + delta, bf) for bp, bf in meshes]
        write_3mf_multi(path, plate, blockers=moved_blockers)
        mp, mf = _merged(plate)
        plan = plan_print(mp, mf, size_mm, detail)
        info: dict[str, Any] = {"plate": i, "objects": [n for n, _, _ in plate], "3mf": str(path), "plan": plan.receipt(),
                                "support_blockers": sum(len(v) for v in moved_blockers.values())}
        if slice_it:
            info["slice"] = slice_3mf(path, out_dir / f"slice_plate{i}", printer=prefs["printer"], process=plan.process,
                                      filament=prefs["filament"],
                                      overrides={**plan.overrides(), "curr_bed_type": prefs["bed"]},
                                      mesh_height=float(np.ptp(mp[:, 2])),
                                      mesh_dims=tuple(float(v) for v in np.ptp(mp, axis=0)))
        done.append(info)
    return done


def assembly_picture(parts: list[dict[str, Any]], pins: list[dict[str, Any]], cuts: list[dict[str, Any]],
                     out_dir: Path, stem: str, attached: list[dict[str, Any]] | None = None,
                     spread_mm: float = 10.0, tag: str = "assembly") -> list[str]:
    """조립 그림: 부품을 원래 자리에서 자른 면 방향으로 벌려(spread_mm) 색을 달리 칠한 앞 · 옆 그림.
    attached(따로 구운 부품)는 앉힌 자리에서 미는 반대쪽으로 1.5배 벌린다 — spread_mm=0 이면 다 끼운 모습."""
    from .glb import Mesh
    from .preview import VIEWS, render
    from .split_plan import _PALETTE

    objs, cols = [], []
    for k, part in enumerate(parts):
        model = (part["positions"] + part["shift"]) @ part["rotation"]
        push = np.zeros(3)
        for c in cuts:
            if part["id"] in c.get("plus_parts", [c["plus_part"]]):
                push += np.asarray(c["normal"]) * spread_mm
            elif part["id"] in c.get("minus_parts", [c["minus_part"]]):
                push -= np.asarray(c["normal"]) * spread_mm
        objs.append((f"p{part['id']}", model + push, part["faces"]))
        cols.append(np.tile(np.array(_PALETTE[k % len(_PALETTE)], dtype=float), (len(part["faces"]), 1)))
    for j, att in enumerate(attached or []):
        part = att["part"]
        model = (part["positions"] + part["shift"]) @ part["rotation"] + np.asarray(att["shift_mm"])
        model = model - np.asarray(att["direction"], dtype=float) * spread_mm * 1.5
        objs.append((f"a{j}", model, part["faces"]))
        cols.append(np.tile(np.array(_PALETTE[(len(parts) + j) % len(_PALETTE)], dtype=float), (len(part["faces"]), 1)))
    pos, faces = _merged(objs)
    yup = np.stack([pos[:, 0], pos[:, 2], -pos[:, 1]], axis=1)  # 프린트 자리(z 위) → 그림 자리(y 위)
    mesh = Mesh(yup, faces)
    colors = np.vstack(cols)
    files = []
    for name, view in VIEWS.items():
        target = out_dir / f"{stem}_{tag}_{name}.webp"
        render(mesh, view, 512, colors).save(target, format="WEBP", quality=82)
        files.append(str(target))
    return files


def prepare_assembly(mesh: Any, out_dir: Path, stem: str, size_mm: float, cuts: list[Cut], *,
                     printer: str | None = None, detail: str = "auto", orientation: str | None = None,
                     clearance: float | None = None, clearance_source: str = "기본값(안 잼)",
                     pin_d: float | None = None, pitch: float | None = None, slice_it: bool | None = None,
                     floor_cut_mm: float | None = None, attach: list[Any] | None = None) -> dict[str, Any]:
    """나눠 뽑기 한 바퀴: 프린트 자리 → 나누기 · 핀 → (따로 구운 부품 앉히기) → 부품 · 핀 STL → 판 나누기 → 판마다 3MF ·
    썰기 → 조립 그림 · 영수증. 앉힌 부품은 색이 다를 수 있어 바탕 부품과 다른 판에 담는다(설계 §8-2 「색끼리 판」)."""
    import os

    from .print_plan import orient
    from .printing import print_space, printer_prefs, write_stl

    if slice_it is None:
        slice_it = os.environ.get("JARVIS_GEN3D_SLICE", "1").strip() != "0"
    if pitch is None:
        pitch = float(os.environ.get("JARVIS_GEN3D_PITCH", "0.2") or 0.2)
    pos, faces = print_space(mesh, size_mm)
    if orientation and orientation != "지금 그대로":
        pos = orient(pos, orientation)
    prefs = printer_prefs(printer)
    clr = CLEARANCE_MM if clearance is None else float(clearance)
    started = time.time()
    out = split_model(pos, faces, cuts, pitch=pitch, clearance=clr, pin_d=pin_d,
                      thicken_to_mm=prefs["thicken_to_mm"],
                      floor_cut_mm=prefs["floor_cut_mm"] if floor_cut_mm is None else floor_cut_mm,
                      attach=attach, picture_dir=out_dir)
    split_sec = round(time.time() - started, 1)
    (out_dir / "parts").mkdir(parents=True, exist_ok=True)
    items: list[tuple[str, np.ndarray, np.ndarray]] = []
    blockers: dict[str, tuple[np.ndarray, list[tuple[np.ndarray, np.ndarray]]]] = {}
    files: dict[str, Any] = {"parts": [], "pins": [], "attached": [], "seat_maps": []}
    groups: list[list[tuple[str, np.ndarray, np.ndarray]]] = []
    for j, att in enumerate(out.get("attached") or []):
        safe = f"attach{j + 1}"
        group = []
        for name, pv, pf in ((safe, att["part"]["positions"], att["part"]["faces"]),
                             *(((f"{safe}_pin", *att["pin_mesh"]),) if att.get("pin_mesh") else ())):
            target = out_dir / "parts" / f"{stem}_{name}.stl"
            write_stl(target, pv, pf)
            files["attached"].append(str(target))
            group.append((name, pv, pf))
            if name == safe and att["part"].get("blockers"):
                blockers[name] = (pv, att["part"]["blockers"])
        groups.append(group)
        files["seat_maps"] += att.get("pictures") or []
    for part in out["parts"]:
        name = f"part{part['id']}"
        target = out_dir / "parts" / f"{stem}_{name}.stl"
        write_stl(target, part["positions"], part["faces"])
        files["parts"].append(str(target))
        items.append((name, part["positions"], part["faces"]))
        if part.get("blockers"):
            blockers[name] = (part["positions"], part["blockers"])
    for j, pin in enumerate(out["pins"], start=1):
        name = f"pin{j}"
        target = out_dir / "parts" / f"{stem}_{name}.stl"
        write_stl(target, pin["positions"], pin["faces"])
        files["pins"].append(str(target))
        items.append((name, pin["positions"], pin["faces"]))
    plates = pack_plates(items) if items else []
    kinds = ["바탕"] * len(plates)
    for j, group in enumerate(groups):  # 앉힌 부품은 따로 판(색이 다를 수 있다)
        extra = pack_plates(group)
        plates += extra
        kinds += [f"붙임{j + 1}"] * len(extra)
    sliced = _slice_plates(plates, out_dir, stem, size_mm, detail, prefs, slice_it, blockers)
    for info, kind in zip(sliced, kinds):
        info["group"] = kind
    files["plates"] = [p["3mf"] for p in sliced]
    try:
        files["pictures"] = assembly_picture(out["parts"], out["pins"], out["cuts"], out_dir, stem,
                                             attached=out.get("attached"))
        if out.get("attached"):
            files["pictures"] += assembly_picture(out["parts"], out["pins"], out["cuts"], out_dir, stem,
                                                  attached=out["attached"], spread_mm=0.0, tag="seated")
    except Exception as exc:  # 그림은 덤 — 실패해도 부품은 그대로
        out["notes"].append(f"조립 그림을 못 그렸다: {exc}")
    total_sec = sum(float((p.get("slice") or {}).get("estimated_sec") or 0) for p in sliced)
    total_g = sum(float((p.get("slice") or {}).get("filament_g") or 0) for p in sliced)
    parts_receipt = [{k: (len(v) if k == "blockers" else v) for k, v in part.items()
                      if k not in _PART_ARRAYS or k == "blockers"}
                     for part in out["parts"]]
    steps = []
    for c in out["cuts"]:
        pins_txt = (f"핀 {len(c['pins'])}개(지름 {c['pins'][0]['d_mm']:g}mm)를 양쪽 구멍에 꽂고" if c["pins"]
                    else "핀 없이 맞닿는 면에 접착제를 바르고")
        a_txt = ' · '.join(str(x) for x in c.get('minus_parts') or [c['minus_part']])
        b_txt = ' · '.join(str(x) for x in c.get('plus_parts') or [c['plus_part']])
        steps.append(f"{c['name']}: 부품 {a_txt} 와 부품 {b_txt} — {pins_txt} 맞붙인다")
    attached_receipt = []
    for j, att in enumerate(out.get("attached") or []):
        rec = {k: v for k, v in att.items() if k not in ("part", "pin_mesh")}
        rec["part"] = {k: v for k, v in att["part"].items() if k not in _PART_ARRAYS}
        rec["file"] = f"attach{j + 1}"
        attached_receipt.append(rec)
        pin_txt = (f"핀(지름 {att['pin']['d_mm']:g}mm)을 홈 쪽 구멍에 먼저 꽂고" if att.get("pin") else "핀 없이 홈에 접착제를 바르고")
        steps.append(f"{att['name']}: 부품 {att['seat_part']} 의 홈({att['from']} 쪽 · 깊이 {att['depth_mm']:.2f}mm)에 "
                     f"{pin_txt} attach{j + 1} 을 끼운다")
    return {
        "files": files, "parts": parts_receipt, "attached": attached_receipt,
        "pins": [{k: v for k, v in pin.items() if k not in ("positions", "faces")} for pin in out["pins"]],
        "cuts": out["cuts"], "plates": [{k: v for k, v in p.items()} for p in sliced],
        "clearance_mm": clr, "clearance_from": clearance_source, "split_sec": split_sec,
        "total_estimated_sec": round(total_sec) or None, "total_filament_g": round(total_g, 1) or None,
        "assembly_steps": steps, "notes": out["notes"], "remesh": out["remesh"],
        "placement": "판 위 자리는 뱀부가 다시 놓는다(11-14 실측: 안 겹치게 다시 늘어놓음) — 우리는 판 몇 장에 무엇을 담을지만 정한다",
    }


def plan_split(mesh: Any, out_dir: Path, stem: str, size_mm: float, *, orientation: str | None = None,
               pitch: float | None = None) -> dict[str, Any]:
    """나눌 자리 후보 + 그림(클로드가 고른다)."""
    import os

    from .print_plan import orient
    from .printing import print_space
    from .remesh import remesh
    from .split_plan import candidates, coarse, draw_views, refine

    if pitch is None:
        pitch = float(os.environ.get("JARVIS_GEN3D_PITCH", "0.2") or 0.2)
    pos, faces = print_space(mesh, size_mm)
    if orientation and orientation != "지금 그대로":
        pos = orient(pos, orientation)
    rm = remesh(pos, faces, pitch=pitch, smooth_rounds=0, thicken_to_mm=0, keep_grid=True)
    solid, origin, _ = rm.cells
    cs, co, cp = coarse(solid, origin, rm.pitch)
    cands = refine(candidates(cs, co, cp), solid, origin, rm.pitch)
    pictures = draw_views(cs.astype(np.int16), co, cp, out_dir, stem, cands)
    total = float(solid.sum()) * rm.pitch ** 3
    for c in cands:
        c["small_side_share"] = round(float(c["small_side_mm3"]) / total, 3) if total else None
        if c.get("kind") == "갈래":
            c["pieces_note"] = "거친 격자(1mm)로 센 대략 — 실제 조각 수는 나누기 영수증(notes)에서"
    return {"candidates": cands, "pictures": pictures, "size_mm": size_mm, "orientation": orientation or "지금 그대로",
            "model_mm": [round(float(v), 1) for v in np.ptp(pos, axis=0)],
            "how": ("후보마다 point(자르는 점) · normal(방향) · 종류(목 = 잘록한 곳 · 밑동 = 귀 · 팔 같은 가지가 몸에 붙는 곳 · "
                    "갈래 = 몸통에서 여러 가지가 나뉘기 바로 앞) · 단면 · 작은 쪽 부피 · 좁음(작을수록 잘록). 그림의 빨간 선 번호가 후보 번호다. "
                    "보기 좋은 이음매 · 색 나누기 · 받침이 줄어드는 쪽을 생각해 고르고 gen_3d_split 에 candidate 번호로 넘긴다.")}


def fit_test(out_dir: Path, *, printer: str | None = None, pin_d: float = 5.0, slice_it: bool | None = None) -> dict[str, Any]:
    """끼움 시험 조각 파일 · 썰기."""
    import os

    from .printing import printer_prefs, write_stl

    if slice_it is None:
        slice_it = os.environ.get("JARVIS_GEN3D_SLICE", "1").strip() != "0"
    prefs = printer_prefs(printer)
    cp = fit_coupon(pin_d=pin_d)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_stl(out_dir / "fit_block.stl", *cp["block"])
    write_stl(out_dir / "fit_pin.stl", *cp["pin"])
    plates = pack_plates([("fit_block", *cp["block"]), ("fit_pin", *cp["pin"])])
    sliced = _slice_plates(plates, out_dir, "fit_test", 60.0, "auto", prefs, slice_it)
    return {"files": {"block_stl": str(out_dir / "fit_block.stl"), "pin_stl": str(out_dir / "fit_pin.stl"),
                      "plates": [p["3mf"] for p in sliced]},
            "plates": sliced, "clearances_mm": cp["clearances"], "pin_d_mm": cp["pin_d"],
            "hole_depth_mm": cp["hole_depth_mm"], "pin_length_mm": cp["pin_length_mm"], "how": cp["how"]}
