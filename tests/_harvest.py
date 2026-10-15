"""외부 스킬 수확물이 있는가 — 수확물에 기대는 시험의 공용 표시 (2026-09-29 공개판 준비).

`skills/vendor/*` 는 모노레포 `.gitignore` 로 일부러 깃에서 뺀 **수확물**이다(남의 저장소에서 받아 온 것 —
`scripts/harvest_skills.py`). 공개 저장소는 그것을 다시 배포하지 않고 받아 오게 한다. 그래서 새로 받은 저장소에는
`vendor` 폴더가 **일부만** 있다(깃에 올린 몇 묶음). 예전 판정(`vendor` 폴더가 있나)은 그 상태를 「수확됨」으로 읽었다.

판정: 깃에 안 올라가는 묶음(`engineering`)이 있으면 수확된 것이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[1] / "skills"
HARVESTED = (SKILLS / "vendor" / "engineering").is_dir()

needs_harvest = pytest.mark.skipif(
    not HARVESTED, reason="외부 스킬 수확 전 — `python scripts/harvest_skills.py` 로 받은 뒤 돈다"
)


def _monorepo_script(name: str) -> Path | None:
    """모노레포 루트 `scripts/<name>` — 공개 저장소엔 없다(그 PC 의 운영 스크립트다)."""
    here = Path(__file__).resolve()
    if len(here.parents) < 4:
        return None
    path = here.parents[3] / "scripts" / name
    return path if path.is_file() else None


#: 모노레포의 운영 스크립트(워치독 등)를 읽는 시험. 공개 저장소에서는 이유를 밝히고 건너뛴다.
WATCHDOG = _monorepo_script("watchdog_ollama.ps1")
needs_monorepo_watchdog = pytest.mark.skipif(
    WATCHDOG is None, reason="모노레포 운영 스크립트(scripts/watchdog_ollama.ps1) — 공개 저장소에는 없다"
)
