"""프린트용 면 줄이기 — 개수가 아니라 오차로, 닫힘은 우리가 잰다 (2026-11-14 · `docs/ADR_3D면줄이기_2026-11-14.ko.md`).

다시 뜬 메시는 100mm 배에 삼각형 205만 개라 뱀부 스튜디오가 느려지고 경고한다. 프린터가 그리는 굵기(노즐 0.4 · 층 0.2)보다
훨씬 작은 차이는 출력물에 안 나오므로 면을 줄인다. 줄이는 부품(pyfqmr · MIT)은 닫힘을 보장하지 않는다 — 11-14 실측에서
면 수에 따라 들쭉날쭉하게 꼬인 모서리가 생겼고, 닫혀 있어도 한 곳이 1mm 무너진 판이 있었다. 그래서:

1. 많이 줄이기부터 사다리를 내려간다(원래의 10% · 세기 5 → 7 → 15% … → 30% · 세기 3).
2. 단계마다 **닫힘**(가장자리마다 면 둘 · 같은 방향 가장자리 없음)과 **오차**(양쪽 방향 점-삼각형 거리, 표본 2만+2만)를 잰다.
3. 처음 통과한 것(= 면이 가장 적은 통과)을 쓴다. 다 떨어지면 원래 것을 쓰고 그렇다고 적는다. 부품이 없어도 원래 것.

복잡한 모형은 많이 줄이면 오차 검사에 걸려 저절로 면이 더 남는다(대표 11-14 「복잡한 건 삼각형이 많을 수밖에」).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

#: 오차 문턱(mm) — 층 0.2 의 4분의 1 / 4분의 3. 첫 실물 출력 뒤 다시 정한다.
TOL_P999_MM = 0.05
TOL_MAX_MM = 0.15
#: 이보다 적으면 줄이지 않는다(뱀부가 무리 없이 다루는 크기).
SKIP_BELOW_FACES = 300_000
#: (원래 대비 목표 비율, 세기) — 많이 줄이기부터. 11-14 실측(배 205만 · 캐릭터 166만): 10% 에서 오차 최대 0.044mm,
#: 그 아래(7 · 5 · 3 · 2 · 1%)는 닫힘이 늘 깨지고 오차가 0.1mm 를 넘는다 → 10% 부터. 닫힘은 같은 비율에서도 세기에 따라
#: 들쭉날쭉 깨지므로 비율마다 세기 둘을 해 본다. 세기 3 은 많이 못 줄이지만(원래의 25~30% 에서 멈춤) 거의 늘 닫힌다(마지막 기댐).
LADDER: tuple[tuple[float, int], ...] = ((0.10, 5), (0.10, 7), (0.15, 5), (0.15, 7), (0.20, 5), (0.20, 7),
                                          (0.30, 5), (0.30, 7), (0.30, 3))
SAMPLES = 20_000

Decimator = Callable[[np.ndarray, np.ndarray, int, int], tuple[np.ndarray, np.ndarray]]


@dataclass
class SimplifyResult:
    positions: np.ndarray
    faces: np.ndarray
    faces_before: int
    used: dict[str, Any] | None = None  # 고른 단계(비율 · 세기 · 오차)
    tried: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sec: float = 0.0

    def receipt(self) -> dict[str, Any]:
        return {"faces_before": self.faces_before, "faces_after": int(len(self.faces)), "used": self.used,
                "tried": self.tried, "sec": round(self.sec, 1), "tol_p999_mm": TOL_P999_MM, "tol_max_mm": TOL_MAX_MM}


def closed_ok(faces: np.ndarray) -> tuple[bool, int]:
    """닫힌 2-다양체인가: 가장자리마다 면이 정확히 둘 · 같은 방향 가장자리가 두 번 나오지 않음. (참/거짓, 어긋난 가장자리 수)."""
    if not len(faces):
        return False, 0
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    _, cnt = np.unique(np.sort(e, axis=1), axis=0, return_counts=True)
    bad = int((cnt != 2).sum())
    _, dcnt = np.unique(e, axis=0, return_counts=True)
    bad += int((dcnt > 1).sum())
    return bad == 0, bad


def _closest_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """점 p 와 삼각형 (a, b, c) 쌍마다 가장 가까운 거리(Ericson 「Real-Time Collision Detection」 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - b
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - c
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2

    def safe(x: np.ndarray) -> np.ndarray:
        return np.where(x == 0, 1e-30, x)

    den = safe(va + vb + vc)
    res = a + ab * (vb / den)[:, None] + ac * (vc / den)[:, None]
    m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    t = (d4 - d3) / safe((d4 - d3) + (d5 - d6))
    res[m] = (b + (c - b) * t[:, None])[m]
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = d2 / safe(d2 - d6)
    res[m] = (a + ac * t[:, None])[m]
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = d1 / safe(d1 - d3)
    res[m] = (a + ab * t[:, None])[m]
    m = (d6 >= 0) & (d5 <= d6)
    res[m] = c[m]
    m = (d3 >= 0) & (d4 <= d3)
    res[m] = b[m]
    m = (d1 <= 0) & (d2 <= 0)
    res[m] = a[m]
    return np.linalg.norm(p - res, axis=1)


class TriIndex:
    """삼각형을 「자기 상자 + reach」가 닿는 모든 칸(cell mm)에 넣어 둔 색인 — 한 번 만들고 여러 번 묻는다(사다리 단계마다
    원래 메시 205만 면 색인을 다시 만들면 단계당 20초였다)."""

    def __init__(self, pos: np.ndarray, faces: np.ndarray, cell: float = 2.0, reach: float = 0.5) -> None:
        self.cell, self.reach = cell, reach
        self.tri = pos[faces] if len(faces) else np.zeros((0, 3, 3))
        if not len(faces):
            return
        lo_c = np.floor((self.tri.min(axis=1) - reach) / cell).astype(np.int64)
        hi_c = np.floor((self.tri.max(axis=1) + reach) / cell).astype(np.int64)
        self.origin = lo_c.min(axis=0)
        lo_c -= self.origin
        hi_c -= self.origin
        span = hi_c - lo_c + 1
        self.dims = hi_c.max(axis=0) + 1
        n_cells = span.prod(axis=1)
        tri_of = np.repeat(np.arange(len(faces)), n_cells)
        k = np.arange(len(tri_of)) - np.repeat(np.cumsum(n_cells) - n_cells, n_cells)  # 삼각형 안에서 몇 번째 칸
        sp = span[tri_of]
        cx = lo_c[tri_of, 0] + k // (sp[:, 1] * sp[:, 2])
        cy = lo_c[tri_of, 1] + (k // sp[:, 2]) % sp[:, 1]
        cz = lo_c[tri_of, 2] + k % sp[:, 2]
        lin = (cx * self.dims[1] + cy) * self.dims[2] + cz
        order = np.argsort(lin, kind="stable")
        self.sl, self.st = lin[order], tri_of[order]

    def distance(self, q: np.ndarray, batch: int = 2000) -> np.ndarray:
        out = np.full(len(q), np.inf)
        if not len(self.tri) or not len(q):
            return out
        qc = np.floor(q / self.cell).astype(np.int64) - self.origin
        inside = (qc >= 0).all(axis=1) & (qc < self.dims).all(axis=1)
        ql = (qc[:, 0] * self.dims[1] + qc[:, 1]) * self.dims[2] + qc[:, 2]
        tri = self.tri
        for start in range(0, len(q), batch):
            sel = np.arange(start, min(start + batch, len(q)))
            sel = sel[inside[sel]]
            if not len(sel):
                continue
            s0 = np.searchsorted(self.sl, ql[sel], "left")
            s1 = np.searchsorted(self.sl, ql[sel], "right")
            cnt = s1 - s0
            if not cnt.any():
                continue
            qi = np.repeat(sel, cnt)
            ti = self.st[np.repeat(s0, cnt) + (np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt))]
            d = _closest_dist(q[qi], tri[ti, 0], tri[ti, 1], tri[ti, 2])
            d[d > self.reach] = np.inf
            np.minimum.at(out, qi, d)
        return out


def surface_distance(q: np.ndarray, pos: np.ndarray, faces: np.ndarray, cell: float = 2.0, reach: float = 0.5) -> np.ndarray:
    """점 q 마다 (pos, faces) 겉면까지 거리. reach(mm) 안이면 정확하고, 그보다 멀면 inf(= 문턱을 넘은 것으로 친다).

    11-14: 처음엔 무게중심 칸 + 이웃 27칸으로 찾아서, 면을 줄여 생긴 큰 평면 삼각형(20mm)을 못 보고 멀쩡한 결과를 버렸다.
    """
    return TriIndex(pos, faces, cell, reach).distance(q)


def _samples(pos: np.ndarray, faces: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """겉면 위 고른 점 n 개(넓이 비례)."""
    a, b, c = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    pr = area / area.sum() if area.sum() > 0 else None
    i = rng.choice(len(faces), n, p=pr)
    u = rng.random((n, 2))
    flip = u.sum(axis=1) > 1
    u[flip] = 1 - u[flip]
    return a[i] + (b[i] - a[i]) * u[:, :1] + (c[i] - a[i]) * u[:, 1:]


def deviation(pos0: np.ndarray, faces0: np.ndarray, pos1: np.ndarray, faces1: np.ndarray, n: int = SAMPLES,
              index0: TriIndex | None = None, samples0: np.ndarray | None = None) -> dict[str, float]:
    """두 겉면의 차이(mm) — 양쪽 방향으로 표본 n 개씩. 한쪽만 재면 한쪽으로 무너진 곳을 놓친다.
    index0 · samples0(원래 쪽 색인 · 표본)을 주면 다시 만들지 않는다(사다리)."""
    rng = np.random.default_rng(0)
    if index0 is None:
        index0 = TriIndex(pos0, faces0)
    if samples0 is None:
        samples0 = _samples(pos0, faces0, n, np.random.default_rng(1))
    d = np.concatenate([index0.distance(_samples(pos1, faces1, n, rng)), TriIndex(pos1, faces1).distance(samples0)])
    return {"p50": float(np.median(d)), "p999": float(np.percentile(d, 99.9)), "max": float(d.max())}


def _pyfqmr(pos: np.ndarray, faces: np.ndarray, target: int, aggressiveness: int) -> tuple[np.ndarray, np.ndarray]:
    import pyfqmr  # type: ignore[import-not-found]  # MIT · 없으면 호출한 쪽이 ImportError 를 받는다

    s = pyfqmr.Simplify()
    s.setMesh(pos, faces)
    s.simplify_mesh(target_count=int(target), aggressiveness=int(aggressiveness), preserve_border=True, verbose=False)
    p, f, _ = s.getMesh()
    return np.asarray(p, dtype=np.float64), np.asarray(f, dtype=np.int64)


def simplify_closed(pos: np.ndarray, faces: np.ndarray, *, decimate: Decimator | None = None,
                    tol_p999: float = TOL_P999_MM, tol_max: float = TOL_MAX_MM,
                    skip_below: int = SKIP_BELOW_FACES, ladder: tuple[tuple[float, int], ...] = LADDER) -> SimplifyResult:
    """닫힘과 오차 문턱을 지키는 가장 적은 면으로 줄인다. 못 하면 원래 것 그대로(그렇다고 notes 에)."""
    pos = np.asarray(pos, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    n0 = int(len(faces))
    res = SimplifyResult(pos, faces, n0)
    if n0 < skip_below:
        return res
    t0 = time.time()
    if decimate is None:
        try:
            import pyfqmr  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            res.notes.append(f"면 줄이기 부품(pyfqmr)이 없어 {n0:,}개 그대로 — 뱀부 스튜디오가 느리거나 경고할 수 있다")
            return res
        decimate = _pyfqmr
    index0 = TriIndex(pos, faces)
    samples0 = _samples(pos, faces, SAMPLES, np.random.default_rng(1))
    for ratio, agg in ladder:
        target = max(1000, int(n0 * ratio))
        row: dict[str, Any] = {"ratio": ratio, "aggressiveness": agg, "target": target}
        try:
            p, f = decimate(pos, faces, target, agg)
        except Exception as e:  # noqa: BLE001 — 부품이 터져도 원래 것으로 간다
            row["error"] = f"{type(e).__name__}: {e}"[:200]
            res.tried.append(row)
            continue
        row["faces"] = int(len(f))
        if len(f) >= n0:
            row["why"] = "줄지 않음"
            res.tried.append(row)
            continue
        ok, bad = closed_ok(f)
        row["closed"] = ok
        if not ok:
            row["why"] = f"닫힘 깨짐(어긋난 가장자리 {bad})"
            res.tried.append(row)
            continue
        dev = deviation(pos, faces, p, f, index0=index0, samples0=samples0)
        row.update({k: (round(v, 4) if np.isfinite(v) else None) for k, v in dev.items()})
        if not (dev["p999"] <= tol_p999 and dev["max"] <= tol_max):
            row["why"] = "오차 문턱 넘음"
            res.tried.append(row)
            continue
        res.tried.append(row)
        res.positions, res.faces, res.used = p, f, row
        break
    res.sec = time.time() - t0
    if res.used is None:
        res.notes.append(f"면을 줄이면 닫힘이 깨지거나 {tol_max}mm 넘게 어긋나서 {n0:,}개 그대로 둔다 — 뱀부가 느릴 수 있다")
    return res
