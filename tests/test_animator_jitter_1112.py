"""튐 점검(2026-11-12 · 시험 중) — 양방향: 심은 꺾임은 잡고, 고른 움직임(빠르든 느리든)은 안 잡는다."""
from __future__ import annotations

import math

import numpy as np

from alture_jarvis.animator import jitter
from alture_jarvis.animator.fitcheck import BONES


def _flat(rot: np.ndarray, pos: np.ndarray) -> list[float]:
    return [*rot[0], *rot[1], *rot[2], *pos]


def _rz(deg: float) -> np.ndarray:
    r = math.radians(deg)
    return np.array([[math.cos(r), math.sin(r), 0], [-math.sin(r), math.cos(r), 0], [0, 0, 1.0]])


def _dump(n: int = 60, speed: float = 2.0, spin: float = 3.0, kink_pos: int | None = None,
          kink_rot: int | None = None, noise: float = 0.0) -> dict:
    rng = np.random.default_rng(1)
    frames = []
    for f in range(n):
        row = [f]
        for b in BONES:
            z = {"Head": 160.0, "L Foot": 5.0, "R Foot": 5.0}.get(b, 100.0)
            pos = np.array([speed * f, 0.0, z]) + rng.normal(0, noise, 3)
            ang = spin * f + rng.normal(0, noise)
            if b == "Pelvis" and f == kink_pos:
                pos = pos + np.array([0, 8.0, 0])          # 한 프레임만 옆으로 8 튐(몸 크기 155 의 5%)
            if b == "R Hand" and f == kink_rot:
                ang += 40.0                                 # 한 프레임만 40° 꺾임
            row.append(_flat(_rz(ang), pos))
        frames.append(row)
    return {"bones": BONES, "frames": frames}


def test_catches_planted_kinks() -> None:
    out = jitter.scan(_dump(kink_pos=30, kink_rot=45, noise=0.2))
    where = {r["where"]: r for r in out["table"]}
    assert "몸통(골반) 위치" in where and where["몸통(골반) 위치"]["peak_frame"] == 30
    assert "오른 손목 회전" in where and where["오른 손목 회전"]["peak_frame"] == 45
    assert where["몸통(골반) 위치"]["ranges"] == ["29~31"], "구간은 앞뒤 한 프레임까지(두 번째 차이)"
    assert "왼 손목 회전" not in where, "꺾지 않은 손목은 조용해야 한다"


def test_quiet_on_smooth_motion_even_if_fast() -> None:
    for speed, spin in ((0.5, 0.5), (12.0, 15.0)):
        out = jitter.scan(_dump(speed=speed, spin=spin, noise=0.2))
        assert out["table"] == [], (speed, spin, out["table"])


def test_tiny_noise_is_not_jitter() -> None:
    """떨림이 바닥값 아래면(몸 크기 0.6% · 4°) 표에 안 오른다 — 모캡 잔떨림으로 표가 넘치지 않게."""
    out = jitter.scan(_dump(noise=0.3))
    assert out["table"] == []


def test_too_short_is_reported_not_crashed() -> None:
    out = jitter.scan(_dump(n=3))
    assert out["table"] == [] and "5개" in out["note"]
