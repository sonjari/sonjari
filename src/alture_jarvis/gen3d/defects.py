"""흠집 숫자 — 굽기 직후 모델을 같은 잣대로 잰다 (2026-11-15 · 설계 `설계_3D작업대_블렌더마무리` §4-②).

★ 붙인 까닭과 한계. 영수증의 열린 모서리 · 메운 구멍 · 덩이 수로는 흠집을 못 갈랐다(11-15 판 13개: 열린 모서리 모두 0 —
  실행기가 구멍을 메운 뒤에 잰다). 후보 다섯을 사람 눈 표본 13판에 대 보니 **둘만** 갈랐다:
  - `fill_parts` 채운 뒤 덩이 수(0.5mm 칸): 찢김 · 구멍 판 3/3 이 32~83, 나머지 10판은 1~2 → 문턱 10.
  - `off_volume` 본체 밖 부피 몫: 햄버거가 떨어진 판만 13.75%, 나머지 ≤0.06% → 문턱 1%.
  막대 칸 몫 · 거친 면 몫은 돌기 · 뒷목 띠를 못 갈라(놓침 · 헛걸림 둘 다) **넣지 않았다.** 돌기 · 띠 · 「꼬리가 상추로」 같은 것은
  모양 판을 클로드가 본다. n=13 · 그림 하나(리락쿠마)라 문턱은 표본이 쌓이면 다시 잰다.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from .glb import Mesh
from .remesh import PAD_CELLS, _surface_cells, _sweep_outside, cell_components, parity_inside

#: 재는 크기 · 칸 — 긴 변을 이 크기로 맞춰 잰다(프린트 기본 크기와 같다).
MEASURE_SIZE_MM = 80.0
MEASURE_PITCH_MM = 0.5
#: 문턱(11-15 · n=13) — 위 설명 참고.
FILL_PARTS_MAX = 10
OFF_VOLUME_MAX = 0.01


def measure(mesh: Mesh, size_mm: float = MEASURE_SIZE_MM, pitch: float = MEASURE_PITCH_MM) -> dict[str, Any]:
    """{fill_parts, off_volume, flags[], sec}. flags 는 사람 말 한 줄씩(문턱을 넘은 것만)."""
    t0 = time.time()
    pos = np.asarray(mesh.positions, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if not len(faces):
        return {"fill_parts": 0, "off_volume": 0.0, "flags": ["삼각형이 없다"], "sec": 0.0}
    lo = pos.min(axis=0)
    span = float((pos.max(axis=0) - lo).max()) or 1.0
    p = (pos - lo) * (size_mm / span)
    dims = (np.ceil(p.max(axis=0) / pitch).astype(np.int64) + 1) + 2 * PAD_CELLS
    origin = -PAD_CELLS * pitch * np.ones(3)
    shell = _surface_cells(p, faces, origin, pitch, dims)
    solid = ~_sweep_outside(shell)
    if int(solid.sum()) < int(shell.sum()) * 1.05:  # 속이 샜다 — 세 방향 투표로 채워 본다(다시 뜨기와 같은 길)
        solid = parity_inside(shell)
    _, lab = cell_components(solid)
    if len(lab):
        _, counts = np.unique(lab, return_counts=True)
        counts = np.sort(counts)[::-1]
    else:
        counts = np.zeros(0, dtype=np.int64)
    total = int(counts.sum()) or 1
    parts = int(len(counts))
    off = float(counts[1:].sum()) / total if parts > 1 else 0.0
    flags: list[str] = []
    if parts > FILL_PARTS_MAX:
        flags.append(f"속을 채우면 {parts}덩이로 갈린다 — 겉이 찢기거나 구멍이 크다(뒤 · 바닥 · 정수리를 모양 판에서 볼 것)")
    if off > OFF_VOLUME_MAX:
        flags.append(f"본체와 떨어진 덩어리가 부피의 {off * 100:.1f}% — 떨어져 뜬 부분이 있다(모양 판 옆 · 위에서 볼 것)")
    return {"fill_parts": parts, "off_volume": round(off, 4), "flags": flags, "sec": round(time.time() - t0, 1)}


# ── 뒤에 붙은 판(11-17) ────────────────────────────────────────────────
#: 명암 없는 평면 아이콘을 넣으면 TRELLIS.2 가 「흰 판에 붙은 부조(간판 · 스티커)」를 만든다(공식 이슈 microsoft/TRELLIS.2#45 —
#: 관리자: 학습 데이터의 평면 2D 그림 탓 · 3D 렌더처럼 바꿔 넣어라). 모양으로는 「가로 방향을 보는 한 평면에 놓인 면들이
#: 그 방향 단면(상자)만큼 넓은데 **앞 · 뒤 두 면이 같은 띠에** 있다」(얇은 판). 한쪽 면만 넓은 상자 앞면 · 바닥은 안 걸린다.
#: 운영 기록 30판(11-14~17 · 사람 눈 정답: 판 2 · 정상 28)에 대 본 값: 판 0.805 · 0.771, 정상 최대 0.173(로봇 첫 판) → 문턱 0.4.
#: y(위)는 바닥 · 받침 평면이라 보지 않는다. 가로 두 축 중 큰 값(「앞」이 꼭 입력 방향은 아니다 · preview.py).
#: n=2(그림 하나 · 로봇)라 표본이 쌓이면 다시 잰다.
BACKING_FLAT_MAX = 0.4
_BACKING_AXES = {"x": 0, "z": 2}
_BACKING_BAND = 0.01  # 긴 변의 1% 띠(이웃 띠까지 합쳐 ±1)
_BACKING_COS = 0.97  # 법선이 축과 약 14° 안


def flat_backing(mesh: Mesh) -> dict[str, Any]:
    """{share: {x, z}, axis, flag}. share = 한 평면 띠에 놓인 앞쪽 · 뒤쪽 면 넓이 중 작은 쪽 ÷ 그 축 방향 상자 단면. flag 는 넘을 때만."""
    pos = np.asarray(mesh.positions, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if not len(faces):
        return {"share": {}, "axis": None, "flag": None}
    a, b, c = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    cross = np.cross(b - a, c - a)
    double = np.linalg.norm(cross, axis=1)
    keep = double > 0
    normal = cross[keep] / double[keep, None]
    area = double[keep] / 2
    center = ((a + b + c) / 3)[keep]
    ext = pos.max(axis=0) - pos.min(axis=0)
    band = _BACKING_BAND * (float(ext.max()) or 1.0)
    share: dict[str, float] = {}
    for name, k in _BACKING_AXES.items():
        i, j = [axis for axis in range(3) if axis != k]
        section = float(ext[i] * ext[j])
        sel = np.abs(normal[:, k]) > _BACKING_COS
        if section <= 0 or not sel.any():
            share[name] = 0.0
            continue
        slot = np.floor(center[sel, k] / band).astype(np.int64)
        keys, inverse = np.unique(slot, return_inverse=True)
        best = keys[int(np.argmax(np.bincount(inverse, weights=area[sel])))]
        near = np.abs(slot - best) <= 1
        facing = normal[sel, k] > 0
        # 앞 · 뒤 두 면이 같은 띠에 있어야 판이다 — 한쪽만 넓은 것(상자 앞면 · 바닥)은 작은 쪽이 0 에 가깝다
        front = float(area[sel][near & facing].sum())
        back = float(area[sel][near & ~facing].sum())
        share[name] = round(min(front, back) / section, 3)
    axis = max(share, key=share.get) if share else None
    flag = None
    if axis is not None and share[axis] > BACKING_FLAT_MAX:
        flag = (f"뒤에 얇은 판이 붙었다(앞 · 뒤 면이 한 평면에서 단면의 {share[axis]:.2f}배씩) — 명암 없는 평면 그림을 TRELLIS 가 「판에 붙은 "
                "부조」로 만든 모양이다. 판을 잘라 쓰기보다 둥근 명암 · 질감을 넣은 그림으로 다시 굽는 편이 낫다(공식 이슈 TRELLIS.2#45)")
    return {"share": share, "axis": axis, "flag": flag}
