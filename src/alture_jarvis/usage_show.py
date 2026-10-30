"""「쓰는 법」 쇼를 봤는지 (2026-10-27 대표 · 설계서 generated_reports/usage_show_1027/설계서.md).

사람들은 스토어에서 받아 바로 연다 — 앱을 연 첫 10초가 우리 소개다. 그래서 앱 안에 네 장짜리 「쓰는 법」 쇼를 두고,
아직 안 본 사람에게 **한 번** 띄운다.

- 「바뀐 것」(`whats_new`)은 판 번호마다 다시 뜨지만, 이 쇼는 **한 번**이다 — 판 번호와 상관없다.
  내용을 크게 고쳐 다시 보여 주고 싶을 때만 `SHOW_VERSION` 을 올린다.
- 처음 깐 사람은 첫 설정(마법사)을 마친 뒤에 뜬다(`setup_done`). 이미 쓰던 사람은 다음에 켤 때 한 번.
- 「봤다」는 데이터 폴더의 `usage_show_seen.json` 에 적는다(「바뀐 것」의 `whats_new_seen.json` 과 같은 방식 · 다른 파일).
- 언제든 다시 보는 길(사이드바 「쓰는 법」)은 이 기록과 상관없이 늘 열린다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

#: 쇼의 판. 이 값보다 낮은 판을 본 사람에게는 다시 뜬다.
SHOW_VERSION = 1
SEEN_NAME = "usage_show_seen.json"


def _seen_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / SEEN_NAME


def read_seen(data_dir: str | Path) -> int:
    """본 판 번호. 기록이 없거나 깨졌으면 0(= 안 봤다)."""
    try:
        value = json.loads(_seen_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(value, dict):
        return 0
    seen = value.get("version")
    return seen if isinstance(seen, int) and not isinstance(seen, bool) and seen > 0 else 0


def mark_seen(data_dir: str | Path) -> dict[str, Any]:
    path = _seen_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps({"version": SHOW_VERSION, "at": int(time.time())}), encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}"}
    return {"ok": True, "version": SHOW_VERSION}


def status(data_dir: str | Path, *, setup_done: bool) -> dict[str, Any]:
    """화면이 쇼를 띄울지. 첫 설정을 아직 안 마친 사람(마법사 중)에게는 띄우지 않는다."""
    seen = read_seen(data_dir)
    return {"show": bool(setup_done) and seen < SHOW_VERSION, "version": SHOW_VERSION, "seen": seen}
