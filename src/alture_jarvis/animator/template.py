# -*- coding: utf-8 -*-
"""회사 모션 템플릿에 창고 동작을 배치한다 — 사람 확정 규칙 + 모델 제안 (2026-11-04).

현업 애니메이터 회사 모션 리스트는 「목록 › 상태 › 클립명」 세 층이다(예: 공격 모션 › 차지 공격 › ChargeAttack_Start).
회사마다 템플릿이 다르므로 **코드에 박지 않는다** — 창고 옆 `template.json` 하나에 둔다:

    {"template": [{"목록": "...", "상태": "...", "클립명": ["..."]}, ...],
     "rules":    [{"match": "hit_active", "목록": "...", "상태": "...", "클립명": "...", "by": "현업 애니메이터 11-04", "note": "..."}]}

- rules = **사람이 확정한 것**(손자리가 애매하다고 물은 것에 대한 답). 파일 이름 조각(정규식)이 걸리면 그대로 쓴다.
- 규칙에 안 걸리는 동작은 모델(손자리 · 클로드)이 템플릿을 보고 제안해 `propose()` 로 넣는다 — 「모델 제안」 표시.
- 상태가 바뀐 변형(possession · awakening_3 같은)은 원래 칸에 넣고 `variant` 로 표시한다(현업 애니메이터 11-04 승인 질문).
- 결과는 창고 칸의 entry.json `"template"` 에 쓴다. 찾기(library.find)가 그 낱말로도 찾는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

FILE = "template.json"
CONFIRMED = "사람 확정"
PROPOSED = "모델 제안"
# 원래 칸에 넣고 표시만 하는 변형 조각(현업 애니메이터 11-04: 상태 바뀐 버전은 원래 칸 + 표시)
VARIANTS = {"possession": "빙의", "awakening_3": "각성3", "awakening": "각성", "expire": "종료"}


def path(root: Path) -> Path:
    return root / FILE


def load(root: Path) -> dict[str, Any]:
    try:
        data = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("template", [])
    data.setdefault("rules", [])
    return data


def save(root: Path, data: dict[str, Any]) -> Path:
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return p


def _motion_part(name: str) -> str:
    """Hero_A_hit_active_1_240101_01_v2 → hit_active_1 (날짜 앞까지). 캐릭터 이름 칸은 뺀다."""
    core = re.sub(r"^(?:Hero|NPC)_[^_]+_", "", name)
    return re.split(r"_\d{6,7}", core, maxsplit=1)[0]


def variant_of(name: str, matched: str = "") -> str:
    part = _motion_part(name).lower()
    return " · ".join(v for k, v in VARIANTS.items() if k in part and k not in matched.lower())


def rule_for(name: str, rules: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """먼저 적힌 규칙이 이긴다. 이름 전체가 아니라 동작 조각(캐릭터 이름 뺀 것)에 맞춘다."""
    part = _motion_part(name)
    for rule in rules:
        if re.search(rule["match"], part, re.I):
            return rule
    return None


def classify(entry: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
    rule = rule_for(entry.get("name", ""), data["rules"])
    if rule is None:
        return None
    out = {k: rule[k] for k in ("목록", "상태", "클립명") if k in rule}
    out.update({"by": CONFIRMED, "source": rule.get("by", ""), "rule": rule["match"]})
    v = variant_of(entry.get("name", ""), rule["match"])
    if v:
        out["variant"] = v
    return out


def write_entry(folder: Path, placed: dict[str, Any]) -> None:
    ej = folder / "entry.json"
    entry = json.loads(ej.read_text(encoding="utf-8"))
    entry["template"] = placed
    ej.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")


def apply_rules(entries: Iterable[dict[str, Any]], data: dict[str, Any], *, overwrite_proposals: bool = True) -> dict[str, Any]:
    """규칙이 걸리는 칸은 「사람 확정」으로 쓴다. 이미 사람 확정인 칸은 규칙이 바뀌어도 같은 값이면 그대로."""
    placed, left = [], []
    for e in entries:
        if e.get("kind") == "model":
            continue
        got = classify(e, data)
        folder = Path(e["bip"]).parent if e.get("bip") else None
        if got is None or folder is None:
            left.append(e.get("id"))
            continue
        current = e.get("template") or {}
        if current.get("by") == PROPOSED and not overwrite_proposals:
            left.append(e.get("id"))
            continue
        write_entry(folder, got)
        placed.append(e.get("id"))
    return {"confirmed": len(placed), "left_for_model": left}


def propose(folder: Path, 목록: str, 상태: str, 클립명: str = "", why: str = "") -> dict[str, Any]:
    """모델이 템플릿을 보고 제안한 배치. 사람 확정 칸은 덮지 않는다."""
    ej = folder / "entry.json"
    entry = json.loads(ej.read_text(encoding="utf-8"))
    if (entry.get("template") or {}).get("by") == CONFIRMED:
        return entry["template"]
    placed = {"목록": 목록, "상태": 상태, "클립명": 클립명, "by": PROPOSED, "why": why}
    v = variant_of(entry.get("name", ""))
    if v:
        placed["variant"] = v
    write_entry(folder, placed)
    return placed


def words(entry: dict[str, Any]) -> list[str]:
    """찾기용 낱말: 목록 · 상태 · 클립명 · 변형."""
    t = entry.get("template") or {}
    out = [t.get("목록", ""), t.get("상태", ""), t.get("클립명", ""), *(t.get("variant", "").split(" · "))]
    return [w.strip().lower() for w in out if w and w.strip()]
