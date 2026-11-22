"""3D 프린트용 「다시 뜨기」 — 깨진 메시를 블록으로 채운 뒤 닫힌 껍데기를 새로 씌운다 (2026-11-14 · 설계 `설계_3D프린트갈래` §3).

왜 고치지 않고 다시 뜨나: 실행기 결과에는 비다양체 · 구멍 · 뒤집힌 면이 수백~수천 개 남는다(11-14 진짜 3판 296~3,231).
하나하나 고치는 도구(MeshFix)는 GPL 이고, 뱀부 스튜디오의 고치기(Netfabb)는 윈도우 전용이다. 그래서 물체가 차지하는
공간을 정육면체 칸으로 칠하고, 그 겉에 **마칭 테트라헤드라**로 삼각형 껍데기를 새로 뜬다. 정육면체를 같은 방향으로 사면체
여섯 개로 쪼개면 이웃 칸의 이음매가 늘 맞아, 결과는 구조상 닫힌 2-다양체다(numpy 만 · 새 부품 0).

절차:
1. 겉면 칠하기 — 삼각형마다 칸 크기 절반 간격으로 점을 찍어 그 칸을 「껍질」로 칠한다.
2. 바깥 찾기 — 격자 테두리에서 껍질을 건너지 않고 닿는 칸. 한 칸씩 퍼뜨리는 대신 축마다 **줄 단위로 훑어**
   (껍질 사이 빈 구간이 바깥과 닿으면 그 구간 전체가 바깥) 몇 바퀴면 끝난다.
3. 안 = 바깥이 아닌 칸(껍질 포함). 구멍이 칸보다 작으면 저절로 막힌다. 크면 안이 바깥으로 새어 껍질만 남는다 →
   껍질을 한 칸씩 두껍게 해 다시 한다(최대 2번). 그래도 새면 그렇다고 돌려준다(지어내지 않는다).
4. 칸 가운데 값(안 1 · 바깥 0)에 마칭 테트라헤드라 → 가장자리 가운데에 꼭짓점 → 같은 가장자리는 한 꼭짓점.
5. 타우빈 고르기(줄어들지 않는 고르기) — 칸 계단 자국을 편다. 모양(연결)은 안 바뀐다.

잃는 것: 칸 크기보다 가는 선 · 날카로운 모서리는 반 칸쯤 둥글어진다. 색(텍스처)은 버린다. 껍질 칸까지 안으로 치므로
겉이 반 칸쯤 부푼다(0.2mm 칸이면 0.1mm 안팎).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: 격자 칸 수 상한(메모리 · 시간). 넘으면 칸을 키운다 — 영수증에 실제 칸 크기를 적는다.
MAX_CELLS = 16_000_000
#: 껍질을 두껍게 하는 최대 횟수 · 격자 둘레 여유 칸(두껍게 해도 맨 바깥 줄에 닿지 않게 — 11-14 적대적 시험에서
#: 여유 2칸일 때 두 번 두껍게 하자 껍질이 테두리에 닿아 겉이 열렸다).
MAX_THICKEN = 2
PAD_CELLS = MAX_THICKEN + 3
#: 겉면 칠하기에서 한 번에 찍는 점 수 상한(메모리) — 넘으면 삼각형을 묶음으로 나눈다.
SAMPLE_POINTS_PER_BATCH = 4_000_000
#: 바깥 찾기 바퀴 상한(보통 2~5 바퀴면 멈춘다).
MAX_SWEEP_ROUNDS = 40

# 정육면체 꼭짓점 번호(x, y, z 비트) — 사면체 여섯 개는 모두 대각선 0→7 을 나눠 가진다(모든 칸이 같은 방향이라 이음매가 맞다).
_CORNER = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]])
_TETS = np.array([
    [0, 1, 3, 7], [0, 3, 2, 7], [0, 2, 6, 7],
    [0, 6, 4, 7], [0, 4, 5, 7], [0, 5, 1, 7],
])
# 사면체의 가장자리(꼭짓점 쌍) 여섯.
_TET_EDGES = np.array([[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]])


def _tet_table() -> list[list[list[int]]]:
    """16 경우마다 삼각형(가장자리 번호 셋)의 목록. 방향은 나중에 기울기로 맞춘다."""
    edge_of = {tuple(sorted(e)): i for i, e in enumerate(_TET_EDGES.tolist())}
    table: list[list[list[int]]] = []
    for case in range(16):
        inside = [v for v in range(4) if case >> v & 1]
        outside = [v for v in range(4) if not case >> v & 1]
        if len(inside) in (0, 4):
            table.append([])
        elif len(inside) in (1, 3):
            lone = inside[0] if len(inside) == 1 else outside[0]
            others = [v for v in range(4) if v != lone]
            table.append([[edge_of[tuple(sorted((lone, o)))] for o in others]])
        else:
            a, b = inside
            c, d = outside
            # 네 교차 가장자리(a-c, a-d, b-d, b-c)는 사각형 — 삼각형 둘로.
            q = [edge_of[tuple(sorted(p))] for p in ((a, c), (a, d), (b, d), (b, c))]
            table.append([[q[0], q[1], q[2]], [q[0], q[2], q[3]]])
    return table


_TABLE = _tet_table()


@dataclass
class RemeshResult:
    positions: np.ndarray
    faces: np.ndarray
    pitch: float
    grid: tuple[int, int, int]
    shell_thickened: int = 0
    leaked: bool = False
    solid_cells: int = 0
    shell_cells: int = 0
    notes: list[str] = field(default_factory=list)
    #: 얇은 곳(최소 굵기보다 가는 칸)의 몫 · 자리(mm) · 잰 굵기 — 11-14 첫 출력: 밧줄 · 돛대가 노즐 몇 줄 굵기였다.
    thin_share: float = 0.0
    thin_bbox_mm: list[list[float]] | None = None
    min_thickness_mm: float = 0.0
    floor_cut_mm: float = 0.0
    #: 가는 곳 굵게 하기(11-14 첫 실물: 밧줄이 털 · 구슬로 망가짐 — 경고만 하던 것을 고쳐서 내보냄).
    #: 굵히기 전 얇은 몫 · 자리 · 목표 굵기 · 더한 칸 · 돈 횟수.
    thin_share_before: float = 0.0
    thin_bbox_before_mm: list[list[float]] | None = None
    thicken_to_mm: float = 0.0
    thickened_cells: int = 0
    thicken_rounds: int = 0
    #: 겉면 다시 붙이기 결과(붙인 · 묶은 · 되돌린 꼭짓점 수) — 켜지 않았으면 None.
    snap: dict[str, Any] | None = None
    #: 막대 · 판 가리지 않고 최소 굵기보다 얇은 칸의 몫(마지막으로 잰 것 · 참고용 — 얇은 판은 대개 잘 나온다).
    thin_wall_share: float = 0.0
    #: 조립 나누기가 다시 쓰는 칸 격자: (안 칸, 격자 원점 mm, 굵힌 칸 또는 None) — `keep_grid=True` 일 때만.
    cells: tuple[np.ndarray, np.ndarray, np.ndarray | None] | None = None

    def receipt(self) -> dict[str, Any]:
        return {
            "remesh_pitch_mm": round(self.pitch, 4), "remesh_grid": list(self.grid),
            "remesh_shell_thickened": self.shell_thickened, "remesh_leaked": self.leaked,
            "remesh_faces": int(len(self.faces)),
            "thin_share": round(self.thin_share, 4), "thin_bbox_mm": self.thin_bbox_mm,
            "min_thickness_mm": self.min_thickness_mm, "floor_cut_mm": self.floor_cut_mm,
            "thin_share_before": round(self.thin_share_before, 4), "thin_bbox_before_mm": self.thin_bbox_before_mm,
            "thicken_to_mm": self.thicken_to_mm, "thickened_cells": self.thickened_cells,
            "thickened_mm3": round(self.thickened_cells * self.pitch ** 3, 1), "thicken_rounds": self.thicken_rounds,
            "snap": self.snap, "thin_any_share": round(self.thin_wall_share, 4),
        }


def _surface_cells(pos: np.ndarray, faces: np.ndarray, lo: np.ndarray, pitch: float, dims: np.ndarray) -> np.ndarray:
    """삼각형마다 칸 크기 절반 간격으로 점을 찍어 그 칸을 칠한다."""
    shell = np.zeros(tuple(dims), dtype=bool)
    a, b, c = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    longest = np.maximum.reduce([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)])
    # 11-14: 예전엔 64 로 잘라 큰 삼각형(20mm 면)에서 점 간격이 칸보다 넓어져 껍질에 틈이 났다 → 속이 비었다.
    # 상한 없이 칸 절반 간격을 지키고, 메모리는 삼각형을 묶음으로 나눠 지킨다.
    steps = np.maximum(np.ceil(longest / (pitch * 0.5)).astype(np.int64), 1)
    for k in np.unique(steps):
        tri_ids = np.nonzero(steps == k)[0]
        # 무게중심 좌표 (i/k, j/k) · i+j<=k
        i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
        keep = (i + j) <= k
        u = (i[keep] / k).astype(np.float64)
        v = (j[keep] / k).astype(np.float64)
        batch = max(1, SAMPLE_POINTS_PER_BATCH // len(u))
        for start in range(0, len(tri_ids), batch):
            sel = tri_ids[start:start + batch]
            pa, pb, pc = a[sel], b[sel], c[sel]
            pts = pa[:, None, :] + (pb - pa)[:, None, :] * u[None, :, None] + (pc - pa)[:, None, :] * v[None, :, None]
            idx = np.floor((pts.reshape(-1, 3) - lo) / pitch).astype(np.int64)
            idx = np.clip(idx, 0, dims - 1)
            shell[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return shell


def _sweep_outside(shell: np.ndarray) -> np.ndarray:
    """테두리에서 껍질을 건너지 않고 닿는 칸. 축마다 줄 단위로 훑는다(빈 구간이 바깥과 닿으면 구간 전체가 바깥)."""
    outside = np.zeros_like(shell)
    free = ~shell
    for _ in range(MAX_SWEEP_ROUNDS):
        before = int(outside.sum())
        for axis in range(3):
            s = np.moveaxis(shell, axis, -1)
            o = np.moveaxis(outside, axis, -1)
            f = np.moveaxis(free, axis, -1)
            length = s.shape[-1]
            lines = s.reshape(-1, length)
            seg = np.cumsum(lines, axis=1, dtype=np.int32)  # 껍질을 지날 때마다 구간 번호가 하나 오른다
            total = seg[:, -1:]
            fl = f.reshape(-1, length)
            ol = o.reshape(-1, length)
            # 줄의 양 끝에 닿는 빈 구간은 바깥(격자 테두리) — 첫 구간(번호 0)과 마지막 구간(번호 = 줄의 껍질 수).
            touch = fl & ((seg == 0) | (seg == total))
            seeds = (ol | touch) & fl
            key = (np.arange(lines.shape[0], dtype=np.int64)[:, None] * (length + 1) + seg)
            hit = np.zeros(lines.shape[0] * (length + 1), dtype=bool)
            hit[key[seeds]] = True
            grown = fl & hit[key]
            np.moveaxis(outside, axis, -1)[...] = grown.reshape(o.shape) | o
        if int(outside.sum()) == before:
            break
    return outside


def parity_inside(shell: np.ndarray, with_valid: bool = False) -> Any:
    """세 방향 투표로 「안」을 정한다: 축마다 줄을 따라 겉(껍질 칸 무리)을 몇 번 지났는지 세어 홀수 번째 뒤면 안.

    구멍이 있으면 그 구멍을 지나는 줄은 겉 하나를 못 세어 틀린다 — 그런 줄은 끝에서 센 수가 홀수라 「믿지 않음」으로 빼고,
    믿을 만한 축들의 과반으로 정한다. 겉을 스치기만 하는 줄(접선)도 같은 방식으로 다른 축이 바로잡는다.
    돌려주는 것: 안(껍질 포함).
    """
    votes = np.zeros(shell.shape, dtype=np.int8)
    valid = np.zeros(shell.shape, dtype=np.int8)
    for axis in range(3):
        s = np.moveaxis(shell, axis, -1)
        lines = s.reshape(-1, s.shape[-1])
        starts = lines.copy()
        starts[:, 1:] &= ~lines[:, :-1]
        count = np.cumsum(starts, axis=1, dtype=np.int32)
        ok = (count[:, -1] % 2 == 0) & (count[:, -1] > 0)
        inside = ((count % 2) == 1) & ~lines & ok[:, None]
        np.moveaxis(votes, axis, -1)[...] += inside.reshape(s.shape).astype(np.int8)
        np.moveaxis(valid, axis, -1)[...] += np.broadcast_to(ok[:, None], lines.shape).reshape(s.shape).astype(np.int8)
    inside = shell | ((votes * 2 > valid) & (valid > 0))
    return (inside, valid) if with_valid else inside


VOTE_TRUST_MIN = 0.30  # 투표로 채울 때 세 방향이 다 믿을 만한 속 칸의 최소 몫(컵 0% · 피규어 70%)
SPECK_SHARE = 0.01  # 가장 큰 덩이의 1% 보다 작은 떨어진 덩이는 투표 부스러기로 보고 버린다


def drop_specks(solid: np.ndarray) -> np.ndarray:
    """투표로 생긴 허공의 부스러기 덩이를 버린다(11-15 리락쿠마: 873덩이). 큰 덩이는 여럿이어도 남긴다."""
    idx = np.argwhere(solid)
    if not len(idx):
        return solid
    lo, hi = idx.min(axis=0), idx.max(axis=0) + 1
    sub = solid[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
    cells, lab = cell_components(sub)
    ids, cnt = np.unique(lab, return_counts=True)
    keep_ids = ids[cnt >= SPECK_SHARE * cnt.max()]
    keep = np.isin(lab, keep_ids)
    out = np.zeros_like(solid)
    kc = cells[keep] + lo
    out[kc[:, 0], kc[:, 1], kc[:, 2]] = True
    return out


def _dilate(mask: np.ndarray) -> np.ndarray:
    out = mask.copy()
    out[1:] |= mask[:-1]
    out[:-1] |= mask[1:]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    out[:, :, 1:] |= mask[:, :, :-1]
    out[:, :, :-1] |= mask[:, :, 1:]
    return out


def _marching_tets(solid: np.ndarray, lo: np.ndarray, pitch: float) -> tuple[np.ndarray, np.ndarray]:
    """칸 가운데 값(안 1)으로 마칭 테트라헤드라. 칸 가운데를 격자점으로 본다."""
    nx, ny, nz = solid.shape
    # 바뀌는 곳이 있는 정육면체(격자점 여덟 개가 다 같지 않은 것)만.
    corners = [solid[dx:nx - 1 + dx, dy:ny - 1 + dy, dz:nz - 1 + dz] for dx, dy, dz in _CORNER.tolist()]
    stack = np.stack(corners, axis=-1)
    active = stack.any(axis=-1) & ~stack.all(axis=-1)
    cubes = np.argwhere(active)  # 정육면체의 원점 격자점
    if not len(cubes):
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    vals = stack[active]  # (n, 8)
    base = cubes[:, None, :] + _CORNER[None, :, :]  # (n, 8, 3) 격자점 좌표
    flat = np.ravel_multi_index(base.reshape(-1, 3).T, solid.shape).reshape(-1, 8)

    tris_keys: list[np.ndarray] = []
    tris_inside: list[np.ndarray] = []  # 방향 맞추기용: 각 삼각형에 대한 「안」 격자점 하나
    for tet in _TETS:
        tv = vals[:, tet]  # (n, 4)
        tf = flat[:, tet]
        case = (tv * (1 << np.arange(4))).sum(axis=1)
        for cnum in range(1, 15):
            rows = np.nonzero(case == cnum)[0]
            if not len(rows):
                continue
            inside_v = [v for v in range(4) if cnum >> v & 1][0]
            for tri in _TABLE[cnum]:
                e = _TET_EDGES[tri]  # (3, 2) 사면체 꼭짓점 번호
                ga = tf[rows][:, e[:, 0]]
                gb = tf[rows][:, e[:, 1]]
                keys = np.minimum(ga, gb) * solid.size + np.maximum(ga, gb)  # 격자 가장자리 = 꼭짓점 이름
                tris_keys.append(keys)
                tris_inside.append(tf[rows][:, inside_v])
    keys = np.concatenate(tris_keys)
    inside_pt = np.concatenate(tris_inside)
    uniq, inv = np.unique(keys.reshape(-1), return_inverse=True)
    faces = inv.reshape(-1, 3).astype(np.int64)
    ga, gb = uniq // solid.size, uniq % solid.size
    pa = np.stack(np.unravel_index(ga, solid.shape), axis=1).astype(np.float64)
    pb = np.stack(np.unravel_index(gb, solid.shape), axis=1).astype(np.float64)
    verts = lo + ((pa + pb) * 0.5 + 0.5) * pitch  # 칸 가운데 사이의 가운데

    # 방향: 면 법선이 「안」 격자점에서 멀어지는 쪽(바깥)을 보게.
    tri = verts[faces]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ip = lo + (np.stack(np.unravel_index(inside_pt, solid.shape), axis=1) + 0.5) * pitch
    out_dir = tri.mean(axis=1) - ip
    flip = np.einsum("ij,ij->i", normal, out_dir) < 0
    faces[flip] = faces[flip][:, [0, 2, 1]]
    return verts, faces


def taubin_smooth(pos: np.ndarray, faces: np.ndarray, rounds: int = 8, lam: float = 0.5, mu: float = -0.53) -> np.ndarray:
    """줄어들지 않는 고르기. 이웃 평균 쪽으로 λ 만큼 갔다가 μ 만큼 되돌린다(연결은 안 바뀐다)."""
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    deg = np.bincount(edges.ravel(), minlength=len(pos)).astype(np.float64)
    deg[deg == 0] = 1
    p = pos.copy()
    for _ in range(rounds):
        for w in (lam, mu):
            acc = np.zeros_like(p)
            np.add.at(acc, edges[:, 0], p[edges[:, 1]])
            np.add.at(acc, edges[:, 1], p[edges[:, 0]])
            p = p + w * (acc / deg[:, None] - p)
    return p


def _erode(mask: np.ndarray) -> np.ndarray:
    out = mask.copy()
    out[1:] &= mask[:-1]
    out[:-1] &= mask[1:]
    out[:, 1:] &= mask[:, :-1]
    out[:, :-1] &= mask[:, 1:]
    out[:, :, 1:] &= mask[:, :, :-1]
    out[:, :, :-1] &= mask[:, :, 1:]
    out[0], out[-1] = False, False
    return out


def _box_pass(mask: np.ndarray, grow: bool) -> np.ndarray:
    """정육면체(3×3×3) 모양으로 한 칸 깎기/불리기 — 축마다 따로 해서 곱한다(모서리 · 꼭짓점이 돌아온다)."""
    out = mask
    for ax in range(3):
        a = np.moveaxis(out, ax, 0)
        b = a.copy()
        if grow:
            b[1:] |= a[:-1]
            b[:-1] |= a[1:]
        else:
            b[1:] &= a[:-1]
            b[:-1] &= a[1:]
            b[0] = b[-1] = False
        out = np.moveaxis(b, 0, ax)
    return out


def thin_cells(solid: np.ndarray, pitch: float, min_thickness_mm: float) -> np.ndarray:
    """최소 굵기보다 가는 칸: 굵기의 절반만큼 깎았다가 다시 불려도 돌아오지 않는 칸(열림 연산).

    11-14: 십자 모양으로 하면 두꺼운 상자의 모서리까지, 딱 맞게 불리면 겉 한 겹까지(12%) 「얇다」로 잡혔다
    — 정육면체 모양으로, 한 칸 더 불린다.
    """
    steps = max(1, int(round(min_thickness_mm / pitch / 2)))
    core = solid
    for _ in range(steps):
        core = _box_pass(core, grow=False)
    back = core
    for _ in range(steps + 1):  # 한 칸 더: 표면을 칸으로 찍을 때 생기는 겉 한 겹의 들쭉날쭉은 얇은 곳이 아니다
        back = _box_pass(back, grow=True)
    return solid & ~back


def cell_components(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """참인 칸들의 덩이 번호(6-이웃). 돌려주는 것: (칸 좌표 (n,3), 덩이 번호 (n,)) — 격자 전체가 아니라 참인 칸만 다룬다."""
    cells = np.argwhere(mask)
    n = len(cells)
    if not n:
        return cells, np.zeros(0, dtype=np.int64)
    dims = np.array(mask.shape, dtype=np.int64)
    lin = np.ravel_multi_index(cells.T, mask.shape)
    order = np.argsort(lin)
    lin_sorted = lin[order]
    us, vs = [], []
    for ax in range(3):
        step = int(np.prod(dims[ax + 1:]))
        ok = cells[:, ax] + 1 < dims[ax]
        nb = lin[ok] + step
        pos = np.searchsorted(lin_sorted, nb)
        pos = np.clip(pos, 0, n - 1)
        hit = lin_sorted[pos] == nb
        us.append(np.nonzero(ok)[0][hit])
        vs.append(order[pos[hit]])
    u = np.concatenate(us)
    v = np.concatenate(vs)
    lab = np.arange(n, dtype=np.int64)
    while True:
        prev = lab
        lo = np.minimum(lab[u], lab[v])
        lab = lab.copy()
        np.minimum.at(lab, u, lo)
        np.minimum.at(lab, v, lo)
        lab = lab[lab]  # 건너뛰기
        lab = lab[lab]
        if np.array_equal(lab, prev):
            break
    return cells, lab


#: 굵힐 막대: 평균 단면 < 2 × 목표² · 길이 ≥ 8 × 목표 — 11-14 배: 밧줄(87mm)만 맞고 돛 벽(판) · 둥근 창 테두리(6mm) · 깃발(판)은 아님.
ROD_SECTION_FACTOR = 2.0
ROD_LENGTH_FACTOR = 8.0
ROD_DEFAULT_MM = 1.6  # 굵히기를 껐을 때 막대를 가르는 기준 굵기


def rod_like(thin: np.ndarray, pitch: float, target_mm: float) -> np.ndarray:
    """얇은 칸 덩이 가운데 「길고 가는 막대」만 남긴다. 얇은 판(벽 · 돛 · 깃발)은 잘 출력되고(11-14 실물),
    길고 가는 막대(밧줄)는 층마다 작은 점이 흔들려 털 · 구슬이 됐다."""
    cells, lab = cell_components(thin)
    out = np.zeros_like(thin)
    if not len(cells):
        return out
    uniq, inv, cnt = np.unique(lab, return_inverse=True, return_counts=True)
    lo = np.full((len(uniq), 3), np.iinfo(np.int64).max)
    hi = np.full((len(uniq), 3), -1)
    for ax in range(3):
        np.minimum.at(lo[:, ax], inv, cells[:, ax])
        np.maximum.at(hi[:, ax], inv, cells[:, ax])
    span = (hi - lo + 1) * pitch
    length = np.sqrt((span ** 2).sum(axis=1))  # 비스듬한 막대는 대각선 길이
    section = cnt * pitch ** 3 / np.maximum(length, pitch)
    keep = (section < ROD_SECTION_FACTOR * target_mm ** 2) & (length >= ROD_LENGTH_FACTOR * target_mm)
    sel = keep[inv]
    out[tuple(cells[sel].T)] = True
    return out


def thicken_thin(solid: np.ndarray, pitch: float, target_mm: float, max_rounds: int | None = None,
                 trigger_mm: float | None = None) -> tuple[np.ndarray, int, int]:
    """가는 곳만 한 겹씩 불린다 — 두꺼운 몸통은 그대로, 가는 곳만 굵어진다.

    `trigger_mm`(기본 = 목표) 보다 가는 칸과 그 둘레만 목표 굵기까지 불린다. 11-14 배: 목표(1.6)로 바로 찾으면
    1.2~1.6mm 돛 벽까지 통째로 불려 3,407mm³ 가 붙었다 — 1.2mm 로 출력되는 벽은 건드리지 않는다.
    바닥(가장 낮은 안 칸) 아래로는 불리지 않는다(판에 닿는 면이 그대로). 격자 맨 바깥 줄도 비운다.
    돌려주는 것: (새 안 칸, 더한 칸 수, 돈 횟수).
    """
    if target_mm <= 0 or not solid.any():
        return solid, 0, 0
    z_any = np.nonzero(solid.any(axis=(0, 1)))[0]
    floor_z = int(z_any[0])
    if max_rounds is None:
        max_rounds = max(1, int(np.ceil(target_mm / pitch / 2))) + 1
    zone = thin_cells(solid, pitch, trigger_mm if trigger_mm else target_mm)
    if not zone.any():
        return solid, 0, 0
    zone = rod_like(zone, pitch, target_mm)
    if not zone.any():
        return solid, 0, 0
    for _ in range(max_rounds + 1):  # 불릴 수 있는 구역: 처음 가는 칸에서 불리는 횟수만큼 + 한 칸
        zone = _box_pass(zone, grow=True)
    out = solid.copy()
    added = 0
    rounds = 0
    for _ in range(max_rounds):
        thin = thin_cells(out, pitch, target_mm) & zone
        if not thin.any():
            break
        grow = _box_pass(thin, grow=True) & ~out
        grow[:, :, :floor_z] = False
        grow[0], grow[-1] = False, False
        grow[:, 0], grow[:, -1] = False, False
        grow[:, :, 0], grow[:, :, -1] = False, False
        n = int(grow.sum())
        if not n:
            break
        out |= grow
        added += n
        rounds += 1
    if added:
        # 굵히다 틈을 막아 갇힌 공기 방울 · 대각선으로만 닿은 부스러기를 정리(11-15 리락쿠마: 굵히기만 켜면 34덩이)
        before = int(out.sum())
        out = drop_specks(~_sweep_outside(out))
        out[0], out[-1] = False, False
        out[:, 0], out[:, -1] = False, False
        out[:, :, 0], out[:, :, -1] = False, False
        added += int(out.sum()) - before
    return out, added, rounds


def remesh(pos: np.ndarray, faces: np.ndarray, pitch: float = 0.2, smooth_rounds: int = 8, *,
           floor_cut_mm: float = 0.0, min_thickness_mm: float = 1.2, thicken_to_mm: float = 0.0,
           snap_to_source: bool = False, keep_grid: bool = False) -> RemeshResult:
    """밀리미터 자리의 메시(위치 · 면)를 닫힌 메시로 다시 뜬다."""
    pos = np.asarray(pos, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if not len(faces):
        return RemeshResult(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), pitch, (0, 0, 0), notes=["삼각형이 없다"])
    lo, hi = pos.min(axis=0), pos.max(axis=0)
    span = hi - lo
    notes: list[str] = []
    pitch = float(pitch)
    while True:
        dims = (np.ceil(span / pitch).astype(np.int64) + 1) + 2 * PAD_CELLS  # 둘레 여유
        if int(np.prod(dims)) <= MAX_CELLS:
            break
        pitch *= 1.15
    if pitch > 0.2001:
        notes.append(f"격자 칸을 {pitch:.3f}mm 로 키웠다(칸 수 상한 {MAX_CELLS:,}) — 그보다 가는 디테일은 둥글어진다")
    origin = lo - PAD_CELLS * pitch
    shell = _surface_cells(pos, faces, origin, pitch, dims)
    thickened = 0
    leaked = False
    for attempt in range(MAX_THICKEN + 1):
        outside = _sweep_outside(shell)
        solid = ~outside
        # 맨 바깥 줄은 무슨 일이 있어도 바깥 — 여기에 안이 닿으면 겉이 열린다(그 밖에 칸이 없다).
        solid[0, :, :] = solid[-1, :, :] = False
        solid[:, 0, :] = solid[:, -1, :] = False
        solid[:, :, 0] = solid[:, :, -1] = False
        shell_n = int(shell.sum())
        solid_n = int(solid.sum())
        # 안이 껍질과 거의 같으면(속이 비었으면) 안이 바깥으로 샌 것.
        if solid_n > shell_n * 1.05 or attempt == MAX_THICKEN:
            leaked = solid_n <= shell_n * 1.05
            break
        if attempt == 0:
            # 껍질을 불리기 전에 세 방향 투표로 속을 채워 본다(11-15 리락쿠마: 트렐리스 결과에 구멍이 많아 물 채우기가
            # 속까지 새고, 껍질을 두 번 불려도 못 막아 속 빈 껍질 · 8분). 모양이 부풀지 않는다.
            voted, valid = parity_inside(shell, with_valid=True)
            voted[0, :, :] = voted[-1, :, :] = False
            voted[:, 0, :] = voted[:, -1, :] = False
            voted[:, :, 0] = voted[:, :, -1] = False
            # 고장 구멍인가, 진짜 입구인가(컵 · 돛): 새로 채울 속 칸 가운데 세 방향이 다 믿을 만한 칸의 몫으로 가른다.
            # 11-15 실측: 리락쿠마 70.7% · 뚜껑 반쪽 없는 상자 50.6% · 입구 활짝 열린 컵 0% — 30% 아래면 채우지 않고 「샜다」.
            fresh = voted & outside & ~shell
            trust = float((valid[fresh] == 3).mean()) if fresh.any() else 0.0
            if int(voted.sum()) > shell_n * 1.05 and trust >= VOTE_TRUST_MIN:
                voted = drop_specks(voted)
                # 몸속에 갇힌 공기 방울을 메운다(11-15 리락쿠마: 부스러기를 버려도 744덩이 — 안쪽 빈 공간마다 겉이 따로 생김)
                voted = ~_sweep_outside(voted)
                solid, solid_n = voted, int(voted.sum())
                notes.append("구멍 사이로 속이 새서 세 방향 투표로 속을 채웠다(원래 모델의 구멍을 메운 것 · 모양은 그대로)")
                break
        shell = _dilate(shell)
        thickened += 1
    if leaked:
        notes.append("구멍이 커서 속을 못 채웠다 — 속 빈 껍질로 나온다(벽 두께 = 칸 몇 개). 원래 그림의 큰 구멍을 확인할 것")
    # 바닥 평평 자르기(선택): 가장 낮은 안 칸에서 위로 floor_cut_mm 만큼 지운다 — 겉뜨기가 평평한 바닥을 저절로 닫는다.
    cut_layers = 0
    floor_z: float | None = None
    if floor_cut_mm > 0 and solid.any():
        z_any = np.nonzero(solid.any(axis=(0, 1)))[0]
        cut_layers = max(1, int(round(floor_cut_mm / pitch)))
        solid[:, :, : z_any[0] + cut_layers] = False
        # 자른 바닥 평면의 높이(칸 k-1 빈 칸과 k 안 칸 사이의 꼭짓점 자리 = origin + k · pitch)
        floor_z = float(origin[2] + (z_any[0] + cut_layers) * pitch)
    # 얇은 곳 재기(노즐 0.4 × 3줄 = 1.2mm 기본).
    def measure(s: np.ndarray) -> tuple[float, list[list[float]] | None]:
        thin = thin_cells(s, pitch, min_thickness_mm) if min_thickness_mm > 0 and s.any() else np.zeros_like(s)
        wall_share[0] = int(thin.sum()) / max(1, int(s.sum()))
        # 문제는 길고 가는 막대(11-14 실물: 밧줄) — 얇은 판(돛 벽 · 깃발)은 잘 나왔다. 몫 · 자리는 막대만 센다.
        thin = rod_like(thin, pitch, rod_mm) if thin.any() else thin
        n = int(thin.sum())
        if not n:
            return 0.0, None
        idx = np.argwhere(thin)
        lo_i, hi_i = idx.min(axis=0), idx.max(axis=0) + 1
        return n / max(1, int(s.sum())), [[round(float(v), 1) for v in (origin + lo_i * pitch)],
                                          [round(float(v), 1) for v in (origin + hi_i * pitch)]]

    rod_mm = thicken_to_mm if thicken_to_mm > 0 else ROD_DEFAULT_MM
    wall_share = [0.0]
    share_before, bbox_before = measure(solid)
    added = rounds = 0
    grown = None
    if thicken_to_mm > 0 and share_before > 0:
        # 가는 곳 굵게(11-14 대표 「그렇게 하는 게 맞다」): 찾은 곳만 목표 굵기까지 불리고 다시 잰다.
        before_solid = solid
        solid, added, rounds = thicken_thin(solid, pitch, thicken_to_mm, trigger_mm=min_thickness_mm)
        if added:
            grown = solid & ~before_solid
    share, bbox = measure(solid) if added else (share_before, bbox_before)
    verts, out_faces = _marching_tets(solid, origin, pitch)
    if smooth_rounds and len(verts):
        verts = taubin_smooth(verts, out_faces, rounds=smooth_rounds)
    snap_receipt: dict[str, Any] | None = None
    if snap_to_source and len(verts):
        # 겉면 다시 붙이기(설계 `설계_조립부품나누기` §4-2): 계단 잔물결을 원래 표면으로 되돌린다. 굵힌 자리는 그대로.
        from .snap import MeshSurface, snap

        radius = (1.5 + thickened) * pitch
        frozen = None
        if grown is not None:
            near = _box_pass(_box_pass(grown, grow=True), grow=True)
            cell = np.clip(np.floor((verts - origin) / pitch).astype(np.int64), 0, np.array(solid.shape) - 1)
            frozen = near[cell[:, 0], cell[:, 1], cell[:, 2]]
        targets: dict[str, Any] = {"original": MeshSurface(pos, faces, radius)}
        exclude = None
        if floor_z is not None:
            # 자른 바닥은 원래 겉면이 아니라 그 평면에 붙인다 — 11-15: 붙이기가 자른 바닥을 원래 공 겉으로 끌어내려
            # 판에 닿는 넓이가 131 → 0mm² 이 됐다. 바닥 칸 높이 근처에서 아래를 보는 꼭짓점이 자른 면이다.
            from .snap import Plane, vertex_normals

            targets["floor"] = Plane(np.array([0.0, 0.0, floor_z]), np.array([0.0, 0.0, 1.0]), radius)
            vn = vertex_normals(verts, out_faces)
            on_floor = (np.abs(verts[:, 2] - floor_z) < 0.75 * pitch) & (vn[:, 2] < -0.5)
            exclude = {"original": on_floor}
        sn = snap(verts, out_faces, targets, frozen=frozen, edge_mm=0.5 * pitch if floor_z is not None else 0.0, crease_guard=True,
                  exclude=exclude)
        verts = sn.positions
        snap_receipt = {**sn.receipt(), "vertices": int(len(verts)), "radius_mm": round(radius, 3)}
    return RemeshResult(verts, out_faces, pitch, (int(dims[0]), int(dims[1]), int(dims[2])),
                        shell_thickened=thickened, leaked=leaked, solid_cells=solid_n, shell_cells=shell_n, notes=notes,
                        thin_share=share, thin_bbox_mm=bbox,
                        min_thickness_mm=float(min_thickness_mm), floor_cut_mm=round(cut_layers * pitch, 3),
                        thin_share_before=share_before, thin_bbox_before_mm=bbox_before,
                        thicken_to_mm=float(thicken_to_mm) if added else 0.0, thickened_cells=added, thicken_rounds=rounds,
                        snap=snap_receipt, thin_wall_share=wall_share[0],
                        cells=(solid, origin, grown) if keep_grid else None)
