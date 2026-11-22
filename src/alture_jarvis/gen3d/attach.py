"""따로 구운 부품을 바탕 모형에 앉히는 홈 · 핀 (2026-11-16 · 설계 `설계_조립부품나누기` §8-6).

「처음부터 부품으로 굽기」로 작은데 디테일이 중요한 부분(햄버거)을 따로 구우면, 그 부품을 바탕(곰 몸)의
정해진 자리에 레고처럼 끼울 자리가 필요하다. 클로드는 「어느 쪽에서 · 어디에」만 정한다. 손자리가 계산한다:

- 자리: 붙일 부품을 정한 쪽(from)에서 바탕 쪽으로 밀어 처음 닿는 곳 → 거기서 depth_mm 만큼 더 밀어 넣는다(칸 격자 · 결정론).
  위에서 내리기만으로는 머리가 몸보다 큰 인형(곰)에 무릎 자리를 못 찾아서(11-16 실측: 위에서 보면 모든 칸이 머리) 앞 · 뒤 · 옆도 둔다.
- 홈: (붙일 부품 칸을 틈만큼 넓힌 것) ∩ 바탕 칸을 지운다 → 붙일 부품 모양 그대로의 얕은 홈. 홈 벽은 붙일 부품 겉을
  틈만큼 밀어낸 면에 다시 붙여 칸 크기(0.26mm)에 안 묶인다. 붙일 부품 쪽은 깎지 않는다.
- 검사: 홈 아래 남은 살이 벽(1.6mm)보다 얇거나 뚫리면 거절 · 바탕 덩이가 갈라지면 거절 · 다른 부품(머리)에 박히면 거절.
- 핀: 맞닿는 면에서 가장 깊은 자리에 미는 방향으로 하나 — 양쪽(바탕 · 붙일 부품) 구멍 + 따로 뽑는 핀(나누기와 같은 Pin).
- 붙일 부품은 자기 칸(0.2mm)으로 따로 다시 뜬다 — 따로 구운 디테일을 바탕의 거친 칸(곰 80mm 는 0.264mm)에 뭉개지 않으려고.

숫자의 처음 값(깊이 2mm · 벽 1.6 · 틈은 끼움 시험 값)은 짐작이다 — 실물로 고친다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .assembly import (
    GAP_MM,
    fit_roof,
    hole_blocker,
    hole_end_target,
    roof_h,
    MAX_ENGAGE,
    MAX_TRIES,
    MIN_ENGAGE,
    PIN_SIZES,
    WALL_MM,
    Pin,
    _basis,
    _Parts,
    _section_depth,
    _split_components,
    cylinder_mesh,
    mesh_part,
    to_laid,
)
from .snap import Cylinder, MeshSurface, vertex_normals

FINE_PITCH_MM = 0.2     # 붙일 부품을 자기 칸으로 다시 뜰 때
DEPTH_RANGE = (0.6, 6.0)
THIN_SHARE_MAX = 0.10   # 홈 자리 가운데 이만큼 넘게 얇거나 뚫리면 거절(가장자리 몇 줄은 둥근 겉을 스친 것)
AUTO_STEP_MM = 2.0

#: from → (미는 축, 부호, 그 축에 수직인 두 축, at 두 값의 뜻)
#  프린트 자리: z 위 · 앞 = -y(나누기 후보 「갈래」 손이 y=-22 · 꼬리 「밑동」이 y=+7 — 11-16 곰 실측).
APPROACH = {
    "top": (2, -1, (0, 1), ("x 가운데", "y 가운데")),
    "front": (1, +1, (0, 2), ("x 가운데", "z 바닥")),
    "back": (1, -1, (0, 2), ("x 가운데", "z 바닥")),
    "left": (0, +1, (1, 2), ("y 가운데", "z 바닥")),
    "right": (0, -1, (1, 2), ("y 가운데", "z 바닥")),
}
_AXIS = "xyz"


@dataclass
class Attach:
    """앉힐 부품 하나. pos · faces = 그 부품을 프린트 자리로 옮긴 메시(mm · z 위 · 바닥 z=0 · 가운데)."""

    name: str
    pos: np.ndarray
    faces: np.ndarray
    approach: str = "top"
    at: tuple[float, float] | None = None  # None = auto
    depth_mm: float = 2.0
    pin: bool = True
    pin_d: float | None = None
    onto: int | None = None
    source: str = ""
    size_mm: float = 0.0

    @staticmethod
    def check(raw: dict[str, Any], i: int) -> dict[str, Any]:
        """도구 인자 한 칸을 검사해 정리한다(메시는 실행기가 읽어 붙인다)."""
        if not isinstance(raw, dict):
            raise ValueError(f"attach[{i}] 는 객체")
        approach = str(raw.get("from") or raw.get("approach") or "top").strip().lower()
        if approach not in APPROACH:
            raise ValueError(f"attach[{i}].from 은 {' · '.join(APPROACH)} 가운데서 — 받은 것: {approach}")
        at = raw.get("at", "auto")
        if at in (None, "", "auto"):
            at_v = None
        else:
            try:
                at_v = tuple(float(v) for v in at)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"attach[{i}].at 은 [두 수] 또는 \"auto\" — {exc}") from exc
            if len(at_v) != 2 or not all(math.isfinite(v) for v in at_v):
                raise ValueError(f"attach[{i}].at 은 [두 수] 또는 \"auto\" — {APPROACH[approach][3]} (mm)")
        depth = float(raw.get("depth_mm") or 2.0)
        if not DEPTH_RANGE[0] <= depth <= DEPTH_RANGE[1]:
            raise ValueError(f"attach[{i}].depth_mm 은 {DEPTH_RANGE[0]:g}~{DEPTH_RANGE[1]:g}")
        onto = raw.get("onto")
        pin_d = raw.get("pin_d")
        if pin_d not in (None, "") and float(pin_d) not in PIN_SIZES:
            raise ValueError(f"attach[{i}].pin_d 는 {PIN_SIZES} 가운데서")
        return {"name": str(raw.get("name") or f"붙임{i + 1}")[:40], "approach": approach, "at": at_v, "depth_mm": depth,
                "pin": raw.get("pin", True) not in (False, "false", 0), "onto": int(onto) if onto not in (None, "") else None,
                "pin_d": float(pin_d) if pin_d not in (None, "") else None}


@dataclass
class Seat:
    att: Attach
    seat_id: int
    direction: np.ndarray       # 붙일 부품 → 바탕 (미는 방향)
    shift: np.ndarray           # 붙일 부품 자리 + shift = 바탕 자리(조립된 자리)
    depth_mm: float
    at_mm: list[float]
    auto: bool
    socket_mm2: float
    socket_mm3: float
    floor_min_mm: float | None
    thin_share: float
    clearance: float
    pin: Pin | None
    socket_pos: np.ndarray      # 홈 벽이 붙을 면(붙일 부품 겉 + 틈 · 바탕 자리)
    socket_faces: np.ndarray
    part: dict[str, Any]
    key: str
    notes: list[str] = field(default_factory=list)
    pictures: list[str] = field(default_factory=list)

    def base_targets(self, radius: float) -> dict[str, Any]:
        t: dict[str, Any] = {f"{self.key}_socket": MeshSurface(self.socket_pos, self.socket_faces, radius)}
        if self.pin is not None:
            p = self.pin
            t[f"{self.key}_hole"] = Cylinder(p.centre, p.axis, p.hole_r, 0.0, p.depth_plus, radius)
            t.update(hole_end_target(f"{self.key}_end", p.centre + p.axis * p.depth_plus, p.axis, p.hole_r, p.roof_plus,
                                     radius))
        return t

    def output(self) -> dict[str, Any]:
        pin_mesh = cylinder_mesh(self.pin.d, self.pin.length) if self.pin is not None else None
        pin_r = None
        if self.pin is not None:
            pin_r = {**self.pin.receipt(), "hole_depth_mm": {"바탕": round(self.pin.depth_plus, 2),
                                                             "붙인 부품": round(self.pin.depth_minus, 2)},
                     "axis": [round(float(v), 3) for v in self.pin.axis]}
        return {
            "name": self.att.name, "from_job": self.att.source, "size_mm": self.att.size_mm, "from": self.att.approach,
            "at_mm": self.at_mm, "at_means": list(APPROACH[self.att.approach][3]), "auto": self.auto,
            "seat_part": self.seat_id, "depth_mm": round(self.depth_mm, 3), "depth_asked_mm": self.att.depth_mm,
            "socket_mm2": self.socket_mm2, "socket_mm3": self.socket_mm3, "floor_min_mm": self.floor_min_mm,
            "thin_share": self.thin_share, "clearance_mm": self.clearance, "pin": pin_r,
            "shift_mm": [round(float(v), 3) for v in self.shift], "direction": [int(v) for v in self.direction],
            "part": self.part, "pin_mesh": pin_mesh, "notes": self.notes, "pictures": self.pictures,
        }


# ── 작은 도구 ──────────────────────────────────────────────────────────
def _dilate(mask: np.ndarray, rounds: int) -> np.ndarray:
    """상자(26-이웃) 넓히기 — 비스듬한 겉에서도 틈이 한 칸은 된다."""
    out = mask.copy()
    for _ in range(rounds):
        g = out.copy()
        for ax in range(3):
            s = np.moveaxis(g, ax, 0)
            t = s.copy()
            t[1:] |= s[:-1]
            t[:-1] |= s[1:]
            g = np.moveaxis(t, 0, ax)
        out = g
    return out


def _lines(mask: np.ndarray, ax: int, sign: int, far: bool) -> tuple[np.ndarray, np.ndarray]:
    """축 ax 를 따라 줄마다 칸이 있나 · 미는 방향(sign)으로 볼 때 가장 앞(far=False) 또는 가장 뒤(far=True) 칸 번호."""
    m = np.moveaxis(mask, ax, -1)
    has = m.any(axis=-1)
    n = m.shape[-1]
    lo = np.argmax(m, axis=-1)
    hi = n - 1 - np.argmax(m[..., ::-1], axis=-1)
    # sign>0 이면 미는 방향 = 번호가 커지는 쪽: 처음 만나는 칸 = 가장 작은 번호, 가장 멀리 나간 칸 = 가장 큰 번호
    pick = (hi if far else lo) if sign > 0 else (lo if far else hi)
    return has, pick


def _hole_room(parts: _Parts, pid: int, start: np.ndarray, axis: np.ndarray, hole_r: float, limit: float,
               max_entry: float) -> tuple[float, float]:
    """start 에서 axis 쪽으로 반지름 hole_r 구멍을 얼마나 팔 수 있나. 맞닿는 면이 둥글거나(햄버거 등 · 배) 틈(0.2~0.5mm)을
    건너야 해서 처음 max_entry 까지는 둘레가 비어도 된다 — 둘레 벽(WALL_MM)이 처음 다 차는 자리가 entry.
    돌려주는 것: (깊이 · entry) — 못 파면 (0, 0)."""
    u, v = _basis(axis)
    ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    ring_r = hole_r + WALL_MM
    ring = np.vstack([start + np.outer(np.cos(ang), u) * r + np.outer(np.sin(ang), v) * r for r in (ring_r, ring_r * 0.5)]
                     + [start[None]])
    p = parts.pitch
    entry, best = None, 0.0
    t = 0.5 * p
    while t <= max_entry + limit + 1e-9:
        ok = bool((parts.at(ring + axis * t) == pid).all() and (parts.at(ring + axis * (t + WALL_MM)) == pid).all())
        if entry is None:
            if ok:
                entry, best = t, t
            elif t > max_entry:
                return 0.0, 0.0
        elif ok and t - entry <= limit + 1e-9:  # 깊이 상한은 입구(entry) 뒤부터 센다
            best = t
        else:
            break
        t += p
    return (best, entry) if entry is not None else (0.0, 0.0)


def _carve_cyl(parts: _Parts, pid: int, centre: np.ndarray, axis: np.ndarray, r: float, depth: float,
               back: float = 2.0, roof: bool = False) -> None:
    """그 부품 칸 가운데 원기둥 안을 비운다. 맞닿는 점은 거친 칸에서 잡아 겉보다 조금 안일 수 있어 뒤로 back 만큼 더 판다
    (11-16: 안 그러면 구멍 입구에 한 칸 막이 남아 메시가 겹친 모서리를 냈다)."""
    shape = np.array(parts.label.shape)
    p = parts.pitch
    h = roof_h(r) if roof else 0.0
    start = centre - axis * back
    end = centre + axis * (depth + h)
    lo = np.clip(np.floor((np.minimum(start, end) - r - p - parts.origin) / p).astype(int), 0, shape - 1)
    hi = np.clip(np.ceil((np.maximum(start, end) + r + p - parts.origin) / p).astype(int), 0, shape)
    ii, jj, kk = np.meshgrid(*(np.arange(lo[a], hi[a]) for a in range(3)), indexing="ij")
    cells = np.stack([ii.ravel(), jj.ravel(), kk.ravel()], axis=1)
    rel = parts.origin + (cells + 0.5) * p - centre
    t = rel @ axis
    radial = np.linalg.norm(rel - np.outer(t, axis), axis=1)
    inside = (t > -back) & (t <= depth) & (radial <= r)
    if roof:  # 끝은 고깔(assembly.ROOF_DEG) — 판을 향해 열려도 지지대 없이 선다
        inside |= (t > depth) & (t <= depth + h) & (radial <= r * (1 - (t - depth) / h))
    sel = cells[inside]
    sel = sel[parts.label[tuple(sel.T)] == pid]
    parts.label[tuple(sel.T)] = 0


def _pad(parts: _Parts, solid: np.ndarray, grown: np.ndarray | None, lo: np.ndarray, hi: np.ndarray
         ) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
    """붙일 부품이 바탕 격자 밖으로 나가면 격자를 늘린다(번호 칸 · 원래 안 칸 · 굵힌 칸 같이). 돌려주는 것: 늘린 몫(앞쪽 칸 수)."""
    shape = np.array(parts.label.shape)
    before = np.maximum(-lo, 0)
    after = np.maximum(hi - shape, 0)
    if not before.any() and not after.any():
        return solid, grown, before
    widths = [(int(b), int(a)) for b, a in zip(before, after)]
    parts.label = np.pad(parts.label, widths)
    solid = np.pad(solid, widths)
    if grown is not None:
        grown = np.pad(grown, widths)
    parts.origin = parts.origin - before * parts.pitch
    return solid, grown, before


# ── 자리 지도 그림 ─────────────────────────────────────────────────────
def seat_map(label: np.ndarray, origin: np.ndarray, pitch: float, approach: str, target: Path, *,
             socket: np.ndarray | None = None, pin: Pin | None = None, ghost: np.ndarray | None = None,
             title: str = "", side: int = 640) -> str:
    """미는 쪽에서 본 바탕 지도(가까울수록 밝게 · 부품마다 색) + mm 좌표 격자(10mm) + 홈(빨강) · 핀(원) · 붙일 부품 그림자(파랑 테).
    at 을 고를 때 이 그림의 눈금을 읽는다 — 좌표를 지어내지 않게."""
    from PIL import Image, ImageDraw

    from .split_plan import _PALETTE, _font

    ax, sg, (q1, q2), _ = APPROACH[approach]
    lab = np.moveaxis(label, ax, -1)
    hit = lab > 0
    has = hit.any(axis=-1)
    n = lab.shape[-1]
    first = np.argmax(hit, axis=-1) if sg > 0 else n - 1 - np.argmax(hit[..., ::-1], axis=-1)
    near = (first / max(n - 1, 1)) if sg > 0 else (1 - first / max(n - 1, 1))
    w, h = lab.shape[0], lab.shape[1]
    pid = np.take_along_axis(lab, first[..., None], axis=-1)[..., 0]
    px = np.full((h, w, 3), 245, dtype=np.float64)
    cols = np.array([_PALETTE[(int(k) - 1) % len(_PALETTE)] for k in range(1, int(label.max()) + 2)], dtype=np.float64)
    shade = (1.0 - 0.6 * near)[..., None]
    rgb = cols[np.clip(pid - 1, 0, len(cols) - 1)] * shade
    jj, ii = np.nonzero(has.T)
    px[h - 1 - jj, ii] = rgb[ii, jj]
    if socket is not None:
        s2 = socket.T
        sj, si = np.nonzero(s2)
        px[h - 1 - sj, si] = np.array([230, 40, 40])
    scale = (side * 0.82) / max(w, h)
    img = Image.new("RGB", (side, side + 40), (245, 245, 243))
    small = Image.fromarray(px.astype(np.uint8)).resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.NEAREST)
    ox, oy = int(side * 0.12), 40 + (side - small.height) // 2
    img.paste(small, (ox, oy))
    draw = ImageDraw.Draw(img)
    font = _font()

    def to_px(a: float, b: float) -> tuple[float, float]:
        return ox + (a - origin[q1]) / pitch * scale, oy + h * scale - (b - origin[q2]) / pitch * scale

    a0, a1 = origin[q1], origin[q1] + w * pitch
    b0, b1 = origin[q2], origin[q2] + h * pitch
    for g in range(int(math.ceil(a0 / 10)) * 10, int(a1) + 1, 10):
        x, _ = to_px(g, b0)
        draw.line([(x, oy), (x, oy + h * scale)], fill=(150, 150, 150) if g else (60, 60, 60), width=1)
        draw.text((x - 10, oy + h * scale + 2), str(g), fill=(60, 60, 60), font=font)
    for g in range(int(math.ceil(b0 / 10)) * 10, int(b1) + 1, 10):
        _, y = to_px(a0, g)
        draw.line([(ox, y), (ox + w * scale, y)], fill=(150, 150, 150) if g else (60, 60, 60), width=1)
        draw.text((ox - 44, y - 10), str(g), fill=(60, 60, 60), font=font)
    if ghost is not None:  # 붙일 부품 테두리(앉힌 자리)
        gt = ghost.T
        edge = gt & ~(np.roll(gt, 1, 0) & np.roll(gt, -1, 0) & np.roll(gt, 1, 1) & np.roll(gt, -1, 1))
        ej, ei = np.nonzero(edge)
        for a_i, b_j in zip(ei.tolist(), ej.tolist()):
            x, y = ox + (a_i + 0.5) * scale, oy + (h - b_j - 0.5) * scale
            draw.point((x, y), fill=(40, 90, 220))
    if pin is not None:
        cx, cy = to_px(pin.centre[q1], pin.centre[q2])
        r = pin.d / 2 / pitch * scale
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(20, 20, 20), width=2)
    names = {"top": "위에서 본", "front": "앞에서 본", "back": "뒤에서 본", "left": "왼쪽(-x)에서 본", "right": "오른쪽(+x)에서 본"}
    draw.text((8, 8), f"{names[approach]} 자리 지도 · 가로 {_AXIS[q1]} · 세로 {_AXIS[q2]} (mm) {title}", fill=(40, 40, 40), font=font)
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target)
    return str(target)


# ── 앉히기 ────────────────────────────────────────────────────────────
def seat_part(parts: _Parts, solid: np.ndarray, grown: np.ndarray | None, att: Attach, *, clearance: float,
              pin_d: float | None = None, thicken_to_mm: float = 1.6, picture_dir: Path | None = None,
              key: str | None = None, base_mesh: tuple[np.ndarray, np.ndarray] | None = None
              ) -> tuple[Seat, np.ndarray, np.ndarray | None]:
    """att 를 바탕(parts)에 앉힌다: 자리 → 홈 → 검사 → 핀 → 붙일 부품 메시. parts.label 의 홈 · 핀 구멍 칸을 비운다.
    돌려주는 것: (Seat, 늘렸을 수 있는 solid, grown). 못 앉히면 ValueError(까닭 · 자리 지도 그림 경로)."""
    from .remesh import remesh

    p = parts.pitch
    ax, sg, (q1, q2), means = APPROACH[att.approach]
    d = np.zeros(3)
    d[ax] = sg
    key = key or f"seat_{att.name}"

    def fail(msg: str) -> ValueError:
        if picture_dir is not None:
            path = seat_map(parts.label, parts.origin, p, att.approach, Path(picture_dir) / f"seat_map_{att.approach}.png",
                            title="(못 앉힘)")
            msg += f" — 자리 지도(mm 눈금): {path}"
        return ValueError(f"{att.name}: {msg}")

    coarse = remesh(att.pos, att.faces, pitch=p, smooth_rounds=0, thicken_to_mm=0, keep_grid=True)
    if abs(coarse.pitch - p) > 1e-9:
        raise fail(f"붙일 부품이 너무 커서 바탕과 같은 칸({p:.3f}mm)에 못 담는다 — size_mm 을 줄여라")
    A, oA, _ = coarse.cells
    a_cells = np.argwhere(A)
    if not len(a_cells):
        raise fail("붙일 부품에 안 칸이 없다")
    a_lo, a_hi = a_cells.min(axis=0), a_cells.max(axis=0)
    k = max(1, int(round(att.depth_mm / p)))
    rc = max(1, int(math.ceil(clearance / p - 1e-9)))

    # 줄 지도: 바탕은 미는 쪽에서 처음 만나는 칸, 붙일 부품은 가장 앞으로 나간 칸
    # onto 를 주면 그 부품만 보고 민다 — 조립 순서상 나머지(예: 머리)는 나중에 얹는다. 다 앉힌 뒤 다른 부품에 박히는지는 따로 본다.
    base_has, base_first = _lines((parts.label == att.onto) if att.onto is not None else (parts.label > 0), ax, sg, far=False)
    first_id = np.take_along_axis(np.moveaxis(parts.label, ax, -1), base_first[..., None], axis=-1)[..., 0]
    a_has, a_lead = _lines(A, ax, sg, far=True)
    au, av = np.nonzero(a_has)
    lead = a_lead[au, av]
    n1, n2 = base_has.shape

    def perp_off(at: tuple[float, float]) -> tuple[int, int]:
        out = []
        for q, val, mean in ((q1, at[0], means[0]), (q2, at[1], means[1])):
            base_idx = (val - parts.origin[q]) / p
            own = a_lo[q] if mean.endswith("바닥") else (a_lo[q] + a_hi[q] + 1) / 2
            out.append(int(round(base_idx - own)))
        return out[0], out[1]

    def evaluate(o1: int, o2: int) -> dict[str, Any] | None:
        bu, bv = au + o1, av + o2
        inside = (bu >= 0) & (bu < n1) & (bv >= 0) & (bv < n2)
        ok = np.zeros(len(au), dtype=bool)
        ok[inside] = base_has[bu[inside], bv[inside]]
        if not ok.any():
            return None
        f = base_first[bu[ok], bv[ok]]
        gap = (f - lead[ok]) if sg > 0 else (lead[ok] - f)  # 미는 방향으로 남은 칸
        g0 = int(gap.min())
        pen = k - (gap - g0)
        hit = pen > 0
        ids = set(np.unique(first_id[bu[ok][hit], bv[ok][hit]]).tolist())
        off_a = (g0 - 1 + k) * sg
        # 실제 틈을 원래 메시로 잴 줄: 칸으로 본 틈이 가장 작은 줄 근처(칸은 겉을 한 칸까지 부풀린다)
        near = np.nonzero(gap <= g0 + 2)[0]
        near = near[np.argsort(gap[near], kind="stable")][:400]
        probe = np.stack([parts.origin[q1] + (bu[ok][near] + 0.5) * p, parts.origin[q2] + (bv[ok][near] + 0.5) * p], axis=1)
        return {"o1": o1, "o2": o2, "off_a": off_a, "contact": int(hit.sum()), "ids": ids, "probe": probe}

    bottom_q = q2 if means[1].endswith("바닥") else None
    base_floor = float(parts.origin[2] + np.argwhere(parts.label > 0)[:, 2].min() * p) if bottom_q is not None else 0.0

    def bottom_ok(o2: int) -> bool:
        return bottom_q is None or parts.origin[2] + (a_lo[2] + o2) * p >= base_floor - 1e-6

    if att.at is not None:
        o1, o2 = perp_off(att.at)
        if not bottom_ok(o2):
            raise fail(f"at 의 바닥 높이 {att.at[1]:g}mm 가 바탕 바닥({base_floor:.1f}mm)보다 낮다")
        cand = evaluate(o1, o2)
        if cand is None:
            raise fail(f"at={list(att.at)} ({' · '.join(means)}) 에서 {att.approach} 쪽으로 밀어도 바탕에 안 닿는다 — 모형 밖")
        order = [cand]
        auto = False
    else:
        step = max(1, int(round(AUTO_STEP_MM / p)))
        cols = np.nonzero(base_has.any(axis=1))[0]
        rows = np.nonzero(base_has.any(axis=0))[0]
        c1 = np.arange(cols.min(), cols.max() + 1, step)
        c2 = np.arange(rows.min(), rows.max() + 1, step)
        if att.approach == "top":  # 설계 방향: 앞쪽 절반(앞 = -y)
            c2 = c2[c2 <= (rows.min() + rows.max()) / 2]
        found = []
        mid1 = (cols.min() + cols.max()) / 2
        for b1 in c1:
            for b2 in c2:
                # 칸 b 에 붙일 부품의 가운데(또는 바닥)가 오게
                own1 = (a_lo[q1] + a_hi[q1] + 1) / 2
                own2 = a_lo[q2] if bottom_q is not None else (a_lo[q2] + a_hi[q2] + 1) / 2
                o1, o2 = int(round(b1 - own1)), int(round(b2 - own2))
                if not bottom_ok(o2):
                    continue
                c = evaluate(o1, o2)
                if c is None or not c["contact"] or len(c["ids"]) != 1:
                    continue
                if att.onto is not None and c["ids"] != {att.onto}:
                    continue
                c["key"] = (-c["contact"], o2 if bottom_q is not None else 0, abs(b1 - mid1))
                found.append(c)
        if not found:
            raise fail("auto 로 앉힐 자리를 못 찾았다(한 부품에만 닿는 자리 없음) — 그림의 눈금을 보고 at 을 정해 다시")
        found.sort(key=lambda c: c["key"])
        order = found[:8]
        auto = True

    last_err = ""
    for cand in order:
        try:
            seat, solid2, grown2 = _seat_at(parts, solid, grown, att, cand, A, oA, a_cells, k, rc, d, ax, sg, (q1, q2),
                                            clearance, pin_d, thicken_to_mm, key, base_mesh)
        except _Reject as exc:
            last_err = str(exc)
            if not auto:
                raise fail(last_err) from None
            continue
        seat.at_mm = _at_from_shift(att, seat.shift, (q1, q2), means)
        seat.auto = auto
        if auto:
            seat.notes.append(f"{att.name}: auto 로 고른 자리 at={seat.at_mm} ({' · '.join(means)}) — 맞닿는 줄 {cand['contact']}개")
        if picture_dir is not None:
            seat.pictures.append(_draw_seat(seat, parts, att, picture_dir, A, ax, (q1, q2)))
        return seat, solid2, grown2
    raise fail(f"auto 후보 {len(order)}곳이 모두 검사에서 떨어졌다(마지막: {last_err})")


class _Reject(Exception):
    pass


def _seat_at(parts: _Parts, solid: np.ndarray, grown: np.ndarray | None, att: Attach, cand: dict[str, Any],
             A: np.ndarray, oA: np.ndarray, a_cells: np.ndarray, k: int, rc: int, d: np.ndarray, ax: int, sg: int,
             perp: tuple[int, int], clearance: float, pin_d: float | None, thicken_to_mm: float, key: str,
             base_mesh: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[Seat, np.ndarray, np.ndarray | None]:
    from .remesh import remesh

    p = parts.pitch
    q1, q2 = perp
    off = np.zeros(3, dtype=np.int64)
    off[q1], off[q2], off[ax] = cand["o1"], cand["o2"], cand["off_a"] - sg * k  # 칸으로 막 닿은 자리
    shift = parts.origin + off * p - oA        # 붙일 부품 자리 + shift = 바탕 자리
    # 칸은 두 겉을 각각 한 칸까지 부풀려 실제보다 일찍 닿는다(11-16 상자 시험: 2mm 를 바랐는데 1.6mm 만 들어감).
    # 닿는 줄 근처를 원래 메시로 재서 실제 틈 G 를 구하고, 붙일 부품을 칸에 안 묶인 거리(G + depth_mm)만큼 민다.
    gap_mm = None
    if base_mesh is not None and len(cand.get("probe", [])):
        gap_mm = _true_gap(cand["probe"], ax, sg, att.pos + shift, att.faces, *base_mesh)
    push = (gap_mm if gap_mm is not None else 0.0) + (att.depth_mm if gap_mm is not None else k * p)
    shift = shift + d * push
    off[ax] += sg * int(round(push / p))
    final = a_cells + off
    margin = rc + 3
    solid, grown, grew = _pad(parts, solid, grown, final.min(axis=0) - margin, final.max(axis=0) + 1 + margin)
    final = final + grew
    label = parts.label
    lo = final.min(axis=0) - rc - 1
    hi = final.max(axis=0) + rc + 2
    box = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi))
    a_box = np.zeros(tuple(hi - lo), dtype=bool)
    a_box[tuple((final - lo).T)] = True
    lab_box = label[box].copy()
    # 붙일 부품을 자기 칸(0.2mm)으로 다시 뜬다 — 디테일 지키기 · 홈 칸 고르기에도 쓴다
    fine = remesh(att.pos, att.faces, pitch=FINE_PITCH_MM, smooth_rounds=0, thicken_to_mm=thicken_to_mm, keep_grid=True)
    Af, oAf, grownA = fine.cells
    fparts = _Parts(Af, oAf, fine.pitch)
    # 홈 칸 = 가운데가 「붙일 부품 + 틈(고운 칸으로 올림)」 안에 드는 바탕 칸. 벽은 그 뒤 「겉 + 틈」 면에 붙는다.
    # 11-16 상자 시험: 거친 칸을 한 칸 넓혀 잡았더니 벽이 0.5mm 더 나가 붙이기 반경 밖에 남았고(지름 8.7 · 바란 것 8.2),
    # 반대로 틈을 안 넓히니 접힘 되돌리기로 못 붙은 꼭짓점 7% 가 원기둥 안(7.8)에 남았다 — 끼울 때 걸린다. 못 붙어도 바깥에 남게.
    grow = max(0, int(math.ceil(clearance / fine.pitch - 1e-9)))
    shell = _dilate(Af, grow) if grow else Af
    idx = np.indices(a_box.shape).reshape(3, -1).T
    own = parts.origin + (idx + lo + 0.5) * p - shift
    fi = np.floor((own - oAf) / fine.pitch).astype(np.int64)
    okf = ((fi >= 0) & (fi < np.array(shell.shape))).all(axis=1)
    inside = np.zeros(len(fi), dtype=bool)
    inside[okf] = shell[fi[okf, 0], fi[okf, 1], fi[okf, 2]]
    sock = inside.reshape(a_box.shape) & (lab_box > 0)
    ids, counts = np.unique(lab_box[sock], return_counts=True)
    if not len(ids):
        raise _Reject("밀어 넣었는데 바탕과 겹치는 칸이 없다")
    seat_id = att.onto if att.onto is not None else int(ids[np.argmax(counts)])
    if seat_id not in ids.tolist():
        raise _Reject(f"onto={att.onto} 부품에 안 닿는다(닿는 부품: {ids.tolist()})")
    others = [int(i) for i in ids if int(i) != seat_id]
    if others:
        raise _Reject(f"부품 {seat_id} 말고 부품 {others} 에도 박힌다 — at · from · depth_mm 를 바꿔라(조립 순서가 꼬인다)")
    # 덩이 수(홈을 판 뒤 갈라지면 안 됨) — 그 부품만
    before = len(_split_components(label == seat_id))
    # 줄마다: 홈이 가장 깊이 들어간 칸 너머에 그 부품 살이 얼마나 남나
    sock_m = np.moveaxis(sock, ax, -1)
    s_has = sock_m.any(axis=-1)
    nloc = sock_m.shape[-1]
    deep_loc = (nloc - 1 - np.argmax(sock_m[..., ::-1], axis=-1)) if sg > 0 else np.argmax(sock_m, axis=-1)
    l1, l2 = np.nonzero(s_has)
    pen = (np.moveaxis(a_box & (lab_box == seat_id), ax, -1)).sum(axis=-1)[l1, l2]
    # 홈 파기
    sub = label[box]
    sub[sock] = 0
    rows = np.moveaxis(label, ax, -1)[l1 + lo[q1], l2 + lo[q2], :] == seat_id
    na = rows.shape[1]
    deep = deep_loc[l1, l2] + lo[ax]
    if sg < 0:
        rows = rows[:, ::-1]
        deep = na - 1 - deep
    idx = np.arange(na)[None, :]
    blocked = (idx > deep[:, None]) & ~rows
    first_block = np.where(blocked.any(axis=1), np.argmax(blocked, axis=1), na)
    remain = (first_block - deep - 1) * p
    full = pen >= k
    through = remain <= 0
    thin = full & (remain < WALL_MM)
    bad = through | thin
    thin_share = round(float(bad.sum()) / max(len(bad), 1), 3)
    floor_min = round(float(remain[full].min()), 2) if full.any() else None
    if thin_share > THIN_SHARE_MAX:
        raise _Reject(f"홈 자리의 {thin_share:.0%} 에서 남는 살이 벽 {WALL_MM:g}mm 보다 얇거나 뚫린다"
                      f"(가장 얇은 곳 {floor_min}mm) — depth_mm 을 줄이거나 두꺼운 자리로")
    after = len(_split_components(label == seat_id))
    if after > before:
        raise _Reject(f"홈을 파니 부품 {seat_id} 이 {after - before + 1}덩이로 갈라진다 — 다른 자리로")
    notes: list[str] = []
    if bad.any():
        notes.append(f"{att.name}: 홈 가장자리 {int(bad.sum())}줄({float(bad.sum()) * p * p:.0f}mm²)은 둥근 겉을 스쳐 얇게 남는다(전체의 {thin_share:.0%})")
    socket_mm2 = round(float(len(l1)) * p * p, 1)
    socket_mm3 = round(float(sock.sum()) * p ** 3, 1)

    if fine.notes:
        notes += [f"{att.name}: {n}" for n in fine.notes]

    # 핀: 맞닿는 면에서 가장 깊은 자리(2D) · 미는 방향
    pin = None
    if att.pin:
        uv = np.stack([parts.origin[q1] + (l1 + lo[q1] + 0.5) * p, parts.origin[q2] + (l2 + lo[q2] + 0.5) * p], axis=1)
        a_lead_has, a_lead = _lines(a_box, ax, sg, far=True)
        pin = _place_pin(parts, fparts, seat_id, uv, a_lead_has, a_lead, lo, d, ax, sg, (q1, q2), clearance, pin_d, shift)
        if pin is None:
            notes.append(f"{att.name}: 벽 {WALL_MM:g}mm 를 지키는 핀 자리가 없다 — 홈 + 접착제로 붙인다")
        else:
            _carve_cyl(parts, seat_id, pin.centre, d, pin.hole_r, pin.depth_plus, roof=pin.roof_plus)
            _carve_cyl(fparts, 1, pin.centre - shift, -d, pin.hole_r, pin.depth_minus, roof=pin.roof_minus)
    # 붙일 부품 메시(자기 자리) — 원래 겉 + 핀 구멍에 붙인다
    radius_f = (1.5 + fine.shell_thickened) * fine.pitch
    targets: dict[str, Any] = {"original": MeshSurface(att.pos, att.faces, radius_f)}
    if pin is not None:
        c_own = pin.centre - shift
        targets["hole"] = Cylinder(c_own, -d, pin.hole_r, 0.0, pin.depth_minus, radius_f)
        targets.update(hole_end_target("", c_own - d * pin.depth_minus, -d, pin.hole_r, pin.roof_minus, radius_f))
    mask = fparts.label == 1
    frozen = (grownA & mask) if grownA is not None else None
    made = mesh_part(mask, oAf, fine.pitch, targets, frozen, Af, [d.copy()], flat_label="앉는 면")
    if pin is not None:  # 붙일 부품 쪽 핀 구멍에도 지지대 금지 부피(판에 놓은 자리)
        made["blockers"] = [to_laid(hole_blocker(pin.centre - shift, -d, pin.hole_r, pin.depth_minus, pin.roof_minus),
                                    made)]
    model = (made["positions"] + made["shift"]) @ made["rotation"]
    socket_pos = model + vertex_normals(model, made["faces"]) * clearance + shift
    if gap_mm is None:
        notes.append(f"{att.name}: 원래 메시로 틈을 못 재 칸으로만 앉혔다 — 실제 깊이는 {k * p:.2f}mm 보다 한두 칸 얕을 수 있다")
    seat = Seat(att=att, seat_id=seat_id, direction=d, shift=shift,
                depth_mm=att.depth_mm if gap_mm is not None else k * p, at_mm=[], auto=False,
                socket_mm2=socket_mm2, socket_mm3=socket_mm3, floor_min_mm=floor_min, thin_share=thin_share,
                clearance=clearance, pin=pin, socket_pos=socket_pos, socket_faces=made["faces"], part=made, key=key,
                notes=notes)
    seat._socket2d = s_has.copy()  # 그림용(상자 자리)
    seat._box_lo = lo
    seat._ghost = np.moveaxis(a_box, ax, -1).any(axis=-1)
    return seat, solid, grown


def _ray_span(points: np.ndarray, ax: int, pos: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """축 ax 와 나란한 줄(수직 두 좌표 = points)이 메시와 만나는 가장 작은 · 가장 큰 축 좌표. 안 만나면 nan."""
    q = [a for a in range(3) if a != ax]
    tri = pos[faces]
    t2 = tri[:, :, q]
    lo, hi = t2.min(axis=1), t2.max(axis=1)
    out_lo = np.full(len(points), np.nan)
    out_hi = np.full(len(points), np.nan)
    for i, (u, v) in enumerate(points):
        sel = np.nonzero((lo[:, 0] <= u) & (hi[:, 0] >= u) & (lo[:, 1] <= v) & (hi[:, 1] >= v))[0]
        if not len(sel):
            continue
        a, b, c = t2[sel, 0], t2[sel, 1], t2[sel, 2]
        det = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
        good = np.abs(det) > 1e-12
        if not good.any():
            continue
        det_s = np.where(good, det, 1.0)
        l1 = ((u - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (v - a[:, 1])) / det_s
        l2 = ((b[:, 0] - a[:, 0]) * (v - a[:, 1]) - (u - a[:, 0]) * (b[:, 1] - a[:, 1])) / det_s
        inside = good & (l1 >= -1e-9) & (l2 >= -1e-9) & (l1 + l2 <= 1 + 1e-9)
        if not inside.any():
            continue
        za = tri[sel, 0, ax] + l1 * (tri[sel, 1, ax] - tri[sel, 0, ax]) + l2 * (tri[sel, 2, ax] - tri[sel, 0, ax])
        za = za[inside]
        out_lo[i], out_hi[i] = za.min(), za.max()
    return out_lo, out_hi


def _true_gap(probe: np.ndarray, ax: int, sg: int, att_pos: np.ndarray, att_faces: np.ndarray,
              base_pos: np.ndarray, base_faces: np.ndarray) -> float | None:
    """붙일 부품(지금 자리)과 바탕 사이 미는 방향으로 남은 실제 틈(mm · 가장 작은 줄). 잴 줄이 없으면 None."""
    a_lo, a_hi = _ray_span(probe, ax, att_pos, att_faces)
    b_lo, b_hi = _ray_span(probe, ax, base_pos, base_faces)
    gap = (b_lo - a_hi) if sg > 0 else (a_lo - b_hi)
    gap = gap[np.isfinite(gap)]
    return float(gap.min()) if len(gap) else None


def _at_from_shift(att: Attach, shift: np.ndarray, perp: tuple[int, int], means: tuple[str, str]) -> list[float]:
    lo, hi = att.pos.min(axis=0) + shift, att.pos.max(axis=0) + shift
    return [round(float(lo[q] if mean.endswith("바닥") else (lo[q] + hi[q]) / 2), 2) for q, mean in zip(perp, means)]


def _place_pin(parts: _Parts, fparts: _Parts, seat_id: int, uv: np.ndarray, lead_has: np.ndarray, lead: np.ndarray,
               lo: np.ndarray, d: np.ndarray, ax: int, sg: int, perp: tuple[int, int], clearance: float,
               pin_d: float | None, shift: np.ndarray) -> Pin | None:
    p = parts.pitch
    q1, q2 = perp
    cuv, depth, _ = _section_depth(uv, p)
    max_depth = float(depth.max()) if len(depth) else 0.0
    sizes = [pin_d] if pin_d else [s for s in PIN_SIZES if s / 2 + clearance + WALL_MM <= max_depth]
    centroid = cuv.mean(axis=0) if len(cuv) else np.zeros(2)
    for dpin in sizes:
        hole_r = dpin / 2 + clearance
        ok = depth >= hole_r + WALL_MM
        if not ok.any():
            continue
        cand, cdepth = cuv[ok], depth[ok]
        order = np.lexsort((np.linalg.norm(cand - centroid, axis=1), -cdepth))[:MAX_TRIES]
        limit = dpin * MAX_ENGAGE + GAP_MM
        for i in order:
            l1 = int(round((cand[i, 0] - parts.origin[q1]) / p - 0.5)) - lo[q1]
            l2 = int(round((cand[i, 1] - parts.origin[q2]) / p - 0.5)) - lo[q2]
            if not (0 <= l1 < lead_has.shape[0] and 0 <= l2 < lead_has.shape[1]) or not lead_has[l1, l2]:
                continue
            g = lead[l1, l2] + lo[ax]
            c3 = np.zeros(3)
            c3[q1], c3[q2] = cand[i]
            c3[ax] = parts.origin[ax] + (g + 1) * p if sg > 0 else parts.origin[ax] + g * p
            entry_base = max(1.0, 0.5 * dpin) + clearance + 2 * p
            db, eb = _hole_room(parts, seat_id, c3, d, hole_r, limit, entry_base)
            da, ea = _hole_room(fparts, 1, c3 - shift, -d, hole_r, limit, max(1.0, 0.5 * dpin))
            if db - eb - GAP_MM >= dpin * MIN_ENGAGE and da - ea - GAP_MM >= dpin * MIN_ENGAGE:
                db, rb = fit_roof(parts, seat_id, c3, d, hole_r, db, eb + GAP_MM + dpin * MIN_ENGAGE)
                da, ra = fit_roof(fparts, 1, c3 - shift, -d, hole_r, da, ea + GAP_MM + dpin * MIN_ENGAGE)
                return Pin(c3, d.copy(), dpin, hole_r, db, da, seat_id, -1, rb, ra)
    return None


def _draw_seat(seat: Seat, parts: _Parts, att: Attach, picture_dir: Path, A: np.ndarray, ax: int,
               perp: tuple[int, int]) -> str:
    """홈 자리를 미는 쪽에서 본 지도 — 홈(빨강) · 핀(검은 원) · 앉힌 부품 테두리(파랑)."""
    shape2 = tuple(np.delete(np.array(parts.label.shape), ax))
    sock = np.zeros(shape2, dtype=bool)
    ghost = np.zeros(shape2, dtype=bool)
    lo = seat._box_lo
    q1, q2 = perp
    s = seat._socket2d
    sock[lo[q1]:lo[q1] + s.shape[0], lo[q2]:lo[q2] + s.shape[1]] = s
    g = seat._ghost
    ghost[lo[q1]:lo[q1] + g.shape[0], lo[q2]:lo[q2] + g.shape[1]] = g
    title = f"· {att.name} 홈 {seat.socket_mm2:g}mm² 깊이 {seat.depth_mm:.2f}mm"
    return seat_map(parts.label, parts.origin, parts.pitch, att.approach,
                    Path(picture_dir) / f"seat_{att.name}_{att.approach}.png", socket=sock, pin=seat.pin, ghost=ghost,
                    title=title)
