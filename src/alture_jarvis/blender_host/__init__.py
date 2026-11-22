"""블렌더 작업대 — 팩들이 같이 쓰는 블렌더 공통 층 (2026-11-18 · `docs/설계_블렌더공통층_워크플로우_2026-11-18.ko.md`).

- `find` — 블렌더 하나를 찾고 판을 읽는다(3D · 애니메이터가 따로 들고 있던 두 벌을 합침).
- `scripts/` — 블렌더 **안에서** 도는 스크립트(`import bpy`)는 여기에만 둔다. 이 폴더만 GPL-3.0-or-later(같은 폴더 LICENSE).
  손자리 코드는 이 파일들을 블렌더에 넘겨 따로 실행만 하고, 파일(GLB · JSON · .blend)로만 주고받는다.
"""
from __future__ import annotations

from pathlib import Path

#: 블렌더 안에서 도는 스크립트 폴더(GPL).
SCRIPTS = Path(__file__).with_name("scripts")


def script_text(name: str) -> str:
    """`scripts/<name>` 의 글 그대로."""
    return (SCRIPTS / name).read_text(encoding="utf-8")
