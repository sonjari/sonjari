# -*- coding: utf-8 -*-
"""맥스에서 읽은 키 → 엇박자 루프 계획 (2026-11-02 · 애니메이터 팩).

읽기 스크립트가 쓴 JSON(maxscript.read_script)을 받아, 트랙(rx…pz)마다 뼈 줄 전체를 offset.offset_chain 으로 계산한다.
- 값 읽기는 맥스가 직접 잰 프레임 표본(samples) — 베지어 곡선 모양 그대로다(선형 보간은 표본 사이에서만).
- 키를 옮길 때 탄젠트 종류(smooth · linear · custom …)를 원래 키에서 그대로 가져간다. 이음매 키는 원래 S 키의 것을 쓴다.
- 늦춤은 마디 순서(뿌리 = 0)로 센다. 어떤 마디에 그 트랙이 없어도 순번은 그대로다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .offset import EPS, Key, link_shift, offset_chain, wrap_time
from .maxscript import TRACKS


def _sampled(samples: Sequence[float], start: int):
    """맥스 표본으로 값 읽기 — 정수 프레임은 그대로, 사이는 직선."""
    values = [float(v) for v in samples]

    def evaluate(_keys: Sequence[Key], t: float) -> float:
        x = t - start
        if x <= 0:
            return values[0]
        if x >= len(values) - 1:
            return values[-1]
        i = int(x)
        frac = x - i
        return values[i] if frac < EPS else values[i] + (values[i + 1] - values[i]) * frac
    return evaluate


@dataclass
class TrackPlan:
    node: str
    handle: int
    track: str
    shift: float
    before: int                                # 읽을 때 [S, E] 안 키 수 — 쓰기 직전 다시 세어 다르면 안 쓴다
    keys: list[dict[str, Any]]                 # 쓸 키 [S, E] (구간 밖 키는 맥스에 그대로 있으므로 싣지 않는다)
    moved: int = 0
    wrapped: int = 0
    collisions: int = 0
    seam: float | None = None


@dataclass
class OffsetPlan:
    start: int
    end: int
    tracks: list[TrackPlan] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)    # (이름, 까닭)
    no_track: list[str] = field(default_factory=list)               # "노드 rx" — XYZ 로 나뉜 곡선이 없음
    unchanged: list[str] = field(default_factory=list)              # 늦춤 0(뿌리) — 쓰지 않음

    def preview(self) -> list[dict[str, Any]]:
        """사람에게 먼저 보일 표 — 노드마다 한 줄."""
        rows: dict[str, dict[str, Any]] = {}
        for tp in self.tracks:
            row = rows.setdefault(tp.node, {"마디": tp.node, "늦춤(프레임)": tp.shift, "트랙": [], "옮긴 키": 0,
                                            "감긴 키": 0, "겹쳐 버린 키": 0})
            row["트랙"].append(tp.track)
            row["옮긴 키"] += tp.moved
            row["감긴 키"] += tp.wrapped
            row["겹쳐 버린 키"] += tp.collisions
        for row in rows.values():
            row["트랙"] = " ".join(row["트랙"])
        return list(rows.values())


def build_plan(dump: dict[str, Any], per_link: float, shifts: Sequence[float] | None = None,
               whole_frames: bool = True, tracks: Sequence[str] | None = None) -> OffsetPlan:
    start, end = int(dump["start"]), int(dump["end"])
    if end - start < 2:
        raise ValueError("루프 구간이 너무 짧다(끝 - 시작 ≥ 2 프레임)")
    nodes = list(dump.get("nodes") or [])
    if not nodes:
        raise ValueError("읽은 노드가 없다 — 맥스에서 뼈 줄을 고르고(또는 nodes 로 이름을 주고) 읽기를 다시 돌려라")
    plan = OffsetPlan(start=start, end=end, skipped=[(str(a), str(b)) for a, b in dump.get("skipped") or []])
    use = [t for t in (tracks or TRACKS) if t in TRACKS]
    for track in use:
        chain: list[list[Key]] = []
        evaluators = []
        raw_keys: list[list[list[Any]]] = []
        for node in nodes:
            spec = (node.get("tracks") or {}).get(track)
            if not spec:
                if track in (node.get("tracks") or {}):
                    plan.no_track.append(f"{node.get('name')} {track}")
                chain.append([])
                evaluators.append(None)
                raw_keys.append([])
                continue
            keys = [list(k) for k in spec.get("keys") or []]
            raw_keys.append(keys)
            chain.append([(float(k[0]), float(k[1])) for k in keys])
            samples = spec.get("samples") or []
            evaluators.append(_sampled(samples, start) if len(samples) == end - start + 1 else None)
        result = offset_chain(chain, start, end, per_link, whole_frames=whole_frames,
                              evaluators=evaluators, shifts=shifts)
        for i, node in enumerate(nodes):
            if not chain[i]:
                continue
            rep = result.reports[i]
            name = str(node.get("name"))
            if abs(rep.shift) < EPS:
                plan.unchanged.append(f"{name} {track}")
                continue
            # 탄젠트: 새 시각 → 원래 키의 탄젠트(같은 식 wrap_time 으로 짝을 짓는다)
            tangent: dict[float, list[Any]] = {}
            s_tangent: list[Any] | None = None
            for k in raw_keys[i]:
                t = float(k[0])
                if abs(t - start) < EPS:
                    s_tangent = k
                if start - EPS <= t < end - EPS:
                    nt, _ = wrap_time(t, start, end, rep.shift)
                    tangent[round(nt, 6)] = k
            out_keys = []
            for t, v in result.keys[i]:
                if not (start - EPS <= t <= end + EPS):
                    continue                    # 구간 밖은 맥스에 그대로 있다
                src = tangent.get(round(t, 6))
                if src is None and (abs(t - start) < EPS or abs(t - end) < EPS):
                    src = s_tangent
                key: dict[str, Any] = {"t": t, "v": v}
                if src is not None and len(src) >= 8:
                    key.update({"in": str(src[2]), "out": str(src[3]), "iv": float(src[4]), "ov": float(src[5]),
                                "il": float(src[6]), "ol": float(src[7])})
                out_keys.append(key)
            before = sum(1 for t, _ in chain[i] if start - EPS <= t <= end + EPS)
            plan.tracks.append(TrackPlan(node=name, handle=int(node.get("handle") or 0), track=track, shift=rep.shift,
                                         before=before, keys=out_keys, moved=rep.moved, wrapped=rep.wrapped,
                                         collisions=rep.collisions, seam=rep.seam_value))
    return plan


def shifts_for(nodes: int, per_link: float, shifts: Sequence[float] | None, whole_frames: bool) -> list[float]:
    return [link_shift(i, per_link, shifts, whole_frames) for i in range(nodes)]
