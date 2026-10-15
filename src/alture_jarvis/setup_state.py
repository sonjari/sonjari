"""첫 실행을 끝냈는가 — `data/setup_state.json` (W2, 2026-09-15).

마법사는 원래 `?mode=setup` 으로만 열렸고 앱 어디서도 여는 길이 없었다. 이제 앱(Tauri)이 이 파일이
**없으면** 작업 화면 대신 마법사 창을 연다. 파일은 백엔드만 쓴다 — 화면이 `localStorage` 에 적던
「끝냈다」 표시는 앱을 지우고 다시 깔거나 창이 바뀌면 사라져서 판정 근거가 될 수 없었다.

설정 > 「첫 실행 다시 하기」는 이 파일을 지우지 않고 옆으로 옮긴다(되돌릴 수 있게).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

FILE_NAME = "setup_state.json"
STEPS = ("pc_check", "model", "connect")


def read(data_dir: Path) -> dict[str, Any]:
    path = Path(data_dir) / FILE_NAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"completed": False, "steps": [], "path": str(path)}
    if not isinstance(value, dict):
        return {"completed": False, "steps": [], "path": str(path)}
    return {"completed": bool(value.get("completed")), "steps": list(value.get("steps") or []),
            "completed_at": value.get("completed_at"), "path": str(path)}


def write(data_dir: Path, *, steps: list[str], completed: bool, clock: float | None = None) -> dict[str, Any]:
    path = Path(data_dir) / FILE_NAME
    known = [step for step in STEPS if step in set(steps)]
    body = {"completed": bool(completed), "steps": known, "completed_at": (clock or time.time()) if completed else None}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return read(data_dir)


def reset(data_dir: Path, *, clock: float | None = None) -> dict[str, Any]:
    path = Path(data_dir) / FILE_NAME
    if path.exists():
        path.replace(path.with_name(f"{path.stem}.reset-{int(clock or time.time())}.json"))
    return read(data_dir)


__all__ = ["FILE_NAME", "read", "reset", "write"]
