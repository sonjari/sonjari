"""그래픽카드 쓰는 법 — 사람이 고른다 (2026-11-11 대표: 「램 부스트를 사용자가 하고 안 하고 고르게」).

- `speed`  속도 우선 · 모델을 그래픽카드에 다 올린다. 넘쳐도 바꾸지 않고 알리기만 한다.
- `auto`   자동(기본) · 평소엔 속도 우선, 넘치면 그때 빠른 모델 + 램 부스트로 넘어간다(11-11 출시 전 시험에서 확인한 길).
- `keep_free` 그래픽카드 비워 두기(3D 작업용) · 판이 시작되면 넘치지 않아도 램 부스트를 걸어 그래픽카드를 `KEEP_FREE_GB` 만큼 비워 둔다.
  3ds Max · 유니티는 작업 중에 그래픽 메모리를 더 잡기도 해서, 넘친 뒤에 비키면 늦다(대표 11-11).

같은 날 3060 12GB 실측(3.6 2비트 · n=1): 다 올림 초당 58토큰 · 그래픽카드 9.5GB / 비워 둠 초당 34토큰 · 3.5GB.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODES = ("speed", "auto", "keep_free")
DEFAULT_MODE = "auto"
STATE_FILE = "gpu_mode.json"
#: 「비워 두기」가 그래픽카드에 남겨 둘 몫(GB) — 3ds Max 장면이 흔히 쥐는 4~6GB(10-23 · 11-11 짐 프로그램 흉내)에 맞춘다.
KEEP_FREE_GB = 6.0


def read_mode(data_dir: Path | str) -> str:
    try:
        value = json.loads((Path(data_dir) / STATE_FILE).read_text(encoding="utf-8")).get("mode")
    except Exception:  # noqa: BLE001 — 없거나 깨졌으면 기본
        return DEFAULT_MODE
    return value if value in MODES else DEFAULT_MODE


def write_mode(data_dir: Path | str, mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"gpu_mode_unknown: {mode} — {', '.join(MODES)} 중 하나")
    path = Path(data_dir) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mode": mode}, ensure_ascii=False), encoding="utf-8")
    return mode


def kept_free_line(english: bool) -> str:
    if english:
        return (f"Keeping the graphics card free: moved part of the model into spare RAM so {KEEP_FREE_GB:.0f}GB of the card stays free "
                "for your other programs (RAM Boost)")
    return f"그래픽카드 비워 두기 — 모델 일부를 남는 램으로 옮겨 그래픽카드를 {KEEP_FREE_GB:.0f}GB 비워 두었습니다(램 부스트)"


def view(data_dir: Path | str, booster: Any = None) -> dict[str, Any]:
    """설정 화면이 그리는 전부 — 지금 고른 것 · 램 부스트가 켜져 있나 · 이 PC 에서 쓸 수 있나."""
    return {
        "mode": read_mode(data_dir),
        "modes": list(MODES),
        "keep_free_gb": KEEP_FREE_GB,
        "available": booster is not None,
        "boost_active": bool(getattr(booster, "active", False)) if booster is not None else False,
    }


__all__ = ["DEFAULT_MODE", "KEEP_FREE_GB", "MODES", "kept_free_line", "read_mode", "view", "write_mode"]
