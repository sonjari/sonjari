"""튐 점검(2026-11-12 · 시험 중) — 입힌 동작에서 몸통 · 허리 · 머리 · 손목이 한 프레임에 확 꺾이는 곳을 표로.

계기: TA 카페(TAN) Max Mocap Tool 글 「전체 동작을 무조건 부드럽게 누르기보다, … 튀는 구간을 먼저 정리」 · 현업 애니메이터 판정 흐름
(뚫림 점검처럼 어디를 볼지 짚어 주고 사람이 진짜 / 아님을 가른다). 고치기(세기 0~10)는 맥스에서 재 본 뒤에 붙인다.

읽기는 뚫림 점검과 같은 파일(`fitcheck.read_script` 의 dump.json — 프레임마다 뼈 월드 행렬)을 쓴다. 맥스는 읽기만 한다.
판정: 프레임마다 **두 번째 차이**(속도가 갑자기 바뀌는 양)를 재고, 그 동작의 보통 수준(중앙값 · MAD)보다 훨씬 크고
몸 크기 기준 바닥값도 넘는 프레임만 튐으로 본다. 빠르지만 고른 움직임은 튐이 아니다.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .fitcheck import _mats, _ranges

#: 부위 → 뼈(dump 의 bones 이름). 골반은 COM 이 끌고 가므로 「몸통」으로 본다.
PARTS = {"몸통(골반)": "Pelvis", "허리": "Spine", "목": "Neck", "머리": "Head", "왼 손목": "L Hand", "오른 손목": "R Hand"}
Z_LIMIT = 6.0          # 보통 수준(MAD) 대비 이만큼 넘어야 튐
POS_FLOOR = 0.006      # 몸 크기(머리~발 높이) 비율 — 이보다 작은 위치 꺾임은 보지 않는다
ROT_FLOOR = 4.0        # 도 — 이보다 작은 회전 꺾임은 보지 않는다


def _angle(m: np.ndarray) -> float:
    """3x3 회전의 각(도)."""
    c = (np.trace(m) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def _unit_rot(m: np.ndarray) -> np.ndarray:
    """행 벡터 축 세 개를 정규화(스케일 빼기)."""
    r = m[:3, :3].copy()
    return r / np.linalg.norm(r, axis=1, keepdims=True)


def _robust(x: np.ndarray) -> tuple[float, float]:
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med))) * 1.4826
    return med, mad


def scan(dump: dict[str, Any]) -> dict[str, Any]:
    names = dump["bones"]
    rows = [r for r in dump["frames"] if r and r[0] != "fig"]
    if len(rows) < 5:
        return {"frames": len(rows), "table": [], "note": "프레임이 5개보다 적어 재지 않았다"}
    frames = [int(r[0]) for r in rows]
    mats = {n: np.stack([_mats(r[1 + i]) for r in rows]) for i, n in enumerate(names)}
    # 몸 크기: 머리와 발 높이 차의 최댓값(없으면 1)
    size = 1.0
    if "Head" in mats and "L Foot" in mats:
        size = float(np.max(mats["Head"][:, 3, 2] - mats["L Foot"][:, 3, 2])) or 1.0
    table = []
    for part, bone in PARTS.items():
        if bone not in mats:
            continue
        m = mats[bone]
        pos = m[:, 3, :3]
        acc = np.linalg.norm(pos[2:] - 2 * pos[1:-1] + pos[:-2], axis=1)          # 가운데 프레임마다
        rots = [_unit_rot(x) for x in m]
        step = [rots[i + 1] @ rots[i].T for i in range(len(rots) - 1)]            # 프레임 사이 회전
        racc = np.array([_angle(step[i + 1] @ step[i].T) for i in range(len(step) - 1)])
        for kind, a, floor, unit in (("위치", acc, POS_FLOOR * size, ""), ("회전", racc, ROT_FLOOR, "°")):
            med, mad = _robust(a)
            z = (a - med) / (mad + 1e-9)
            hit = np.where((z > Z_LIMIT) & (a > floor))[0]
            if hit.size == 0:
                continue
            hf = [frames[i + 1] for i in hit]
            worst = float(a[hit].max())
            # 한 프레임 꺾임도 두 번째 차이는 앞뒤 프레임까지 걸린다(29~31) — 가장 심한 프레임을 따로 짚는다
            peak = frames[int(hit[np.argmax(a[hit])]) + 1]
            table.append({"where": f"{part} {kind}", "frames": len(hf), "of": len(frames),
                          "ranges": _ranges(hf)[:8], "peak_frame": peak, "worst": round(worst, 2 if unit else 3),
                          "worst_unit": unit or f"(몸 크기의 {worst / size * 100:.1f}%)",
                          "times_usual": round(worst / (med + 1e-9), 1) if med > 1e-9 else None})
    table.sort(key=lambda r: -r["frames"])
    return {"frames": len(frames), "table": table,
            "how": f"프레임마다 속도가 갑자기 바뀌는 양을 재서, 그 동작의 보통 수준보다 {Z_LIMIT:g}배(MAD) 넘게 크고 "
                   f"바닥값(위치 몸 크기의 {POS_FLOOR * 100:.1f}% · 회전 {ROT_FLOOR:g}°)도 넘는 프레임만 표에 올렸다."}
