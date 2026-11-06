# -*- coding: utf-8 -*-
"""엇박자 루프 — 참조 구현 (2026-11-02 · 설계: docs/설계_게임애니메이션팩_2026-11-02.ko.md §3-2).

맥스 스크립트(offset_loop.ms)는 이 계산과 키 시각이 1:1 로 같아야 한다. 이 파일은 맥스 없이 시험하는 기준이다.

계산(뼈 줄의 마디 i, 0 = 뿌리)
    L  = E - S
    t' = S + ((t - S + i*d) mod L)          늦춘 뒤 구간 밖으로 나간 키는 앞으로 감는다
    이음매: 원래 곡선을 (S - i*d) 에서 읽은 값으로 S 와 E 에 키를 놓는다(끝 = 처음)

- 원래 E 에 있던 키는 S 키의 복사본(루프 이음매)으로 보고 늦추기 전에 뺀다 — 안 빼면 S 와 같은 자리로 감겨 겹친다.
- 구간 밖 키는 건드리지 않고 그대로 둔다(보고에 센다).
- 같은 시각에 두 키가 오면 늦게 계산된 것이 남는다(보고에 센다).
- 값 읽기(evaluate)는 바꿔 끼운다: 시험에서는 선형 보간, 맥스에서는 맥스가 직접 곡선을 읽는다(at time).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

EPS = 1e-6
Key = tuple[float, float]                     # (시각, 값)
Evaluate = Callable[[Sequence[Key], float], float]


def linear(keys: Sequence[Key], t: float) -> float:
    """시험용 값 읽기 — 키 사이를 직선으로. 구간 끝 밖은 가장 가까운 키 값."""
    pts = sorted(keys)
    if not pts:
        raise ValueError("키가 없다")
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            return v0 if t1 - t0 < EPS else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def cyclic(keys: Sequence[Key], start: float, end: float, evaluate: Evaluate) -> Callable[[float], float]:
    """[S, E) 를 한 바퀴로 보고 아무 시각이나 읽는다 — 이음매 값 계산용."""
    span = end - start

    def read(t: float) -> float:
        return evaluate(keys, start + ((t - start) % span))
    return read


@dataclass
class LinkReport:
    link: int
    shift: float
    moved: int = 0
    wrapped: int = 0            # 구간 끝을 넘어 앞으로 감긴 키 수
    collisions: int = 0         # 같은 시각에 겹쳐 하나가 버려진 수
    outside: int = 0            # 루프 구간 밖이라 그대로 둔 키 수
    seam_value: float | None = None


@dataclass
class OffsetResult:
    keys: list[list[Key]]                       # 마디마다 새 키(시각 순)
    reports: list[LinkReport] = field(default_factory=list)


def link_shift(i: int, per_link: float, shifts: Sequence[float] | None = None, whole_frames: bool = False) -> float:
    """마디 i 의 늦춤. 사람이 마디마다 적어 준 값(shifts)이 있으면 그것, 없으면 i × per_link."""
    shift = float(shifts[i]) if shifts is not None and i < len(shifts) else i * per_link
    return float(round(shift)) if whole_frames else shift


def wrap_time(t: float, start: float, end: float, shift: float) -> tuple[float, bool]:
    """키 하나의 새 시각과 「감겼나」. offset_chain 과 맥스에 쓸 키가 같은 식을 쓰도록 하나로 둔다."""
    span = end - start
    raw = t - start + shift
    return start + (raw % span), (raw >= span - EPS or raw < -EPS)


def offset_chain(chain: Sequence[Sequence[Key]], start: float, end: float, per_link: float,
                 evaluate: Evaluate = linear, whole_frames: bool = False,
                 evaluators: Sequence[Evaluate | None] | None = None,
                 shifts: Sequence[float] | None = None) -> OffsetResult:
    """뼈 줄(마디마다 한 트랙의 키 목록)을 엇박자 루프로 바꾼 결과. 입력은 바꾸지 않는다.

    evaluators: 마디마다 다른 값 읽기(맥스에서 받은 프레임 표본) — 없거나 None 인 칸은 evaluate.
    shifts: 마디마다 사람이 정한 늦춤(프레임) — 없으면 i × per_link."""
    if end - start <= EPS:
        raise ValueError("루프 구간이 비었다(끝이 시작보다 커야 한다)")
    out = OffsetResult(keys=[])
    for i, keys in enumerate(chain):
        shift = link_shift(i, per_link, shifts, whole_frames)
        rep = LinkReport(link=i, shift=shift)
        if not keys:
            out.keys.append([])
            out.reports.append(rep)
            continue
        inside = [(t, v) for t, v in keys if start - EPS <= t < end - EPS]
        outside = [(t, v) for t, v in keys if not (start - EPS <= t <= end + EPS)]
        rep.outside = len(outside)
        # 값 읽기는 원래 곡선 그대로(E 의 이음매 키 포함) — 끝 근처를 처음 값 쪽으로 이어서 읽어야 한다
        loop_keys = [(t, v) for t, v in keys if start - EPS <= t <= end + EPS] or list(keys)
        own = evaluators[i] if evaluators is not None and i < len(evaluators) else None
        read = cyclic(loop_keys, start, end, own or evaluate)
        placed: dict[float, float] = {}
        for t, v in inside:
            nt, wrapped = wrap_time(t, start, end, shift)
            if wrapped:
                rep.wrapped += 1
            key = round(nt, 6)
            if key in placed:
                rep.collisions += 1
            placed[key] = v
            rep.moved += 1
        seam = read(start - shift)
        rep.seam_value = seam
        # 늦춘 곡선의 S 값 = 원래 곡선의 (S - 늦춤) 값. S 와 E 에 같은 값을 놓아 루프를 닫는다.
        placed[round(start, 6)] = seam
        placed[round(end, 6)] = seam
        merged = sorted(list(placed.items()) + outside)
        out.keys.append(merged)
        out.reports.append(rep)
    return out


def preview_rows(result: OffsetResult) -> list[dict]:
    """사람에게 먼저 보일 「무엇이 바뀌나」 표의 줄."""
    return [{"마디": r.link, "늦춤(프레임)": r.shift, "옮긴 키": r.moved, "감긴 키": r.wrapped,
             "겹쳐 버린 키": r.collisions, "구간 밖이라 그대로": r.outside} for r in result.reports]


def seam_ok(keys: Sequence[Key], start: float, end: float) -> bool:
    """이음매 검사 — 처음 키와 끝 키의 값이 같은가."""
    at = {round(t, 6): v for t, v in keys}
    s, e = at.get(round(start, 6)), at.get(round(end, 6))
    return s is not None and e is not None and abs(s - e) < 1e-6
