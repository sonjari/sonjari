# -*- coding: utf-8 -*-
"""다듬은 것 기억하기(2026-11-13 · 시험 중) — 같은 손질을 두 번째 하면 습관으로 남길지 **묻는다**.

★ 까닭: 현업 애니메이터 11-12 「이건 내가 대화하며 디벨롭할 수밖에」 → 기능을 더 붙이기보다 대화로 한 손질을 잊지 않는 것.
설계: docs/설계_애니메이터_블렌더중심_2026-11-13.ko.md §4.

- 센다: **손자리 도구를 거친 값만**(입히기의 팔 벌림 · 보폭 · 발 고정 · 첫끝 덮기 · 섞는 비율, 엇박자의 마디당 늦춤).
  사람이 그 인자를 **직접 준 것만** 손질로 친다(기본값 · 습관으로 채운 값은 안 센다).
- 상황 열쇠 = (입힐 캐릭터, 템플릿 목록) — 「상황마다 다르다」(11-02)를 지킨다. 다른 상황의 같은 값은 따로 센다.
- 두 번째 같은 손질이면 결과에 `habit_ask` 한 줄(한 번에 한 번만 · 여럿이면 묶음). 「응」은 사람의 다음 말에서만 → 클로드가 anim_habit(save).
  「아니」면 anim_habit(decline) → 그 상황 · 그 값은 다시 묻지 않는다.
- 남긴 습관은 그 인자를 안 줬을 때만 쓰이고, 쓰이면 결과에 `habits_applied` 로 **늘 보인다**(숨은 기본값을 만들지 않는다).
- 파일 둘(이 PC 안 · 사람 이름 없음): `animator_edits.jsonl`(손질 기록) · `animator_habits.json`(남긴 습관 · 거절).
  콜드 스타트 습관 파일(`animator_prefs.json`)과 섞지 않는다 — 그 파일은 「있으면 확인됨」으로 읽히기 때문.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

#: 손질 → (사람 말 이름, 같다고 보는 폭 — None 이면 값이 똑같아야)
TRACKED: dict[str, tuple[str, float | None]] = {
    "arm_spread": ("팔 벌림(도)", 5.0),
    "stride": ("보폭 배율", 0.1),
    "blend": ("섞는 비율", 0.1),
    "foot_lock": ("발 고정", None),
    "bookend": ("첫끝 포즈 덮기", None),
    "per_link": ("마디당 늦춤(프레임)", None),
}


def situation(target: str, kind: str) -> str:
    return f"{(target or '').strip() or '캐릭터 이름 없음'} · {(kind or '').strip() or '목록 없음'}"


def log_path(root: Path) -> Path:
    return root / "animator_edits.jsonl"


def store_path(root: Path) -> Path:
    return root / "animator_habits.json"


def _store(root: Path) -> dict[str, Any]:
    p = store_path(root)
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("habits", {})
                data.setdefault("declined", [])
                return data
        except ValueError:
            pass
    return {"habits": {}, "declined": []}


def _write_store(root: Path, data: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    store_path(root).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def same(param: str, a: Any, b: Any) -> bool:
    tol = TRACKED[param][1]
    if isinstance(a, bool) or isinstance(b, bool) or tol is None:
        return a == b
    try:
        return abs(float(a) - float(b)) <= tol + 1e-9
    except (TypeError, ValueError):
        return a == b


def _history(root: Path) -> list[dict[str, Any]]:
    p = log_path(root)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def lookup(root: Path, where: str) -> dict[str, Any]:
    """그 상황에 남긴 습관 — {손질: 값}."""
    return {k: v["value"] for k, v in (_store(root)["habits"].get(where) or {}).items() if k in TRACKED}


def record(root: Path, tool: str, where: str, values: dict[str, Any]) -> dict[str, Any] | None:
    """사람이 직접 준 손질을 한 줄 남기고, 같은 상황에서 같은 손질이 두 번째(이상)이면 물을 것을 돌려준다."""
    values = {k: v for k, v in values.items() if k in TRACKED and v is not None}
    if not values:
        return None
    before = [h for h in _history(root) if h.get("where") == where]
    root.mkdir(parents=True, exist_ok=True)
    with log_path(root).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": tool, "where": where, "values": values},
                           ensure_ascii=False) + "\n")
    st = _store(root)
    saved = st["habits"].get(where) or {}
    asks = []
    for k, v in values.items():
        if k in saved and same(k, saved[k]["value"], v):
            continue                                                   # 이미 그 값으로 남겼다
        if any(d.get("where") == where and d.get("param") == k and same(k, d.get("value"), v) for d in st["declined"]):
            continue                                                   # 사람이 「아니」라고 했다
        prev = [h for h in before if k in h.get("values", {}) and same(k, h["values"][k], v)]
        if prev:
            asks.append({"param": k, "label": TRACKED[k][0], "value": v, "times": len(prev) + 1, "first": prev[0].get("when", "")[:10]})
    if not asks:
        return None
    said = " · ".join(f"{a['label']} {a['value']}" for a in asks)
    first = min(a["first"] for a in asks)
    return {
        "where": where, "items": asks,
        "ask": f"지난번({first})에도 「{where}」에 {said} 을(를) 쓰셨습니다. 이 상황 기본으로 남길까요?",
        "how": ("사람에게 이 한 줄만 묻고 멈춰라. 사람이 다음 말에서 「응」이라고 하면 anim_habit(action=save, where, values) · "
                "「아니」면 anim_habit(action=decline, …) — 그러면 다시 묻지 않는다. 스스로 정해 저장하지 마라."),
        "save_args": {"action": "save", "where": where, "values": {a["param"]: a["value"] for a in asks}},
    }


def save(root: Path, where: str, values: dict[str, Any], by: str = "") -> dict[str, Any]:
    bad = [k for k in values if k not in TRACKED]
    if bad or not values:
        raise ValueError(f"남길 수 있는 손질은 {list(TRACKED)} — 받은 것: {bad or '없음'}")
    st = _store(root)
    slot = st["habits"].setdefault(where, {})
    for k, v in values.items():
        slot[k] = {"value": v, "saved": time.strftime("%Y-%m-%d %H:%M:%S"), "by": by or "사람 말"}
    st["declined"] = [d for d in st["declined"] if not (d.get("where") == where and d.get("param") in values)]
    _write_store(root, st)
    return {"where": where, "habits": {k: v["value"] for k, v in slot.items()}}


def forget(root: Path, where: str, params: list[str]) -> dict[str, Any]:
    st = _store(root)
    slot = st["habits"].get(where) or {}
    gone = [p for p in params if slot.pop(p, None) is not None]
    if not slot:
        st["habits"].pop(where, None)
    _write_store(root, st)
    return {"where": where, "forgot": gone, "habits": {k: v["value"] for k, v in slot.items()}}


def decline(root: Path, where: str, values: dict[str, Any]) -> dict[str, Any]:
    st = _store(root)
    for k, v in values.items():
        if k in TRACKED:
            st["declined"].append({"where": where, "param": k, "value": v, "when": time.strftime("%Y-%m-%d %H:%M:%S")})
    _write_store(root, st)
    return {"where": where, "declined": [k for k in values if k in TRACKED]}


def listing(root: Path) -> dict[str, Any]:
    st = _store(root)
    return {"habits": {w: {k: v["value"] for k, v in s.items()} for w, s in st["habits"].items()},
            "declined": len(st["declined"]), "edits_logged": len(_history(root))}
