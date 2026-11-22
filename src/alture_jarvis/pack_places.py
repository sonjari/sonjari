"""팩 모델이 「사람이 설정한 자리」에 이미 있나 — 판정 한 자리 (2026-11-16 · 팩 잇기 시험 구멍).

## 왜

이 PC 는 `.env` 의 `JARVIS_GEN3D_BIN_DIR` · `JARVIS_GEN3D_MODELS_DIR` 로 3D 가 잘 돈다. 그런데 팩 모델 상태
(`/v1/packs/gen3d/models`)는 팩이 받는 기본 자리만 봐서 「missing · 받기 10.6GB」로 보였다 — 누르면 같은 것을 또 받는다.

도구(`gen3d_dirs` · `genvideo_dirs`)는 설정 자리를 먼저 쓴다. 팩 모델 상태도 같은 자리를 보게 한다:
**설정 자리에 그 모델이 쓸 수 있는 꼴로 있으면 「설정한 자리에 있음(받지 않아도 됨)」.**
「켜고 받기」(받을 것이 남았나) · 맡김(받을 것이 없을 때만 카드 없이) · 화면 받기 단추가 모두 이 판정을 쓴다.

## 지킬 것

- **있는 판정은 그 팩 도구가 쓰는 함수 그대로**(새 짐작 없음): 3D 실행기 `gen3d.runner.find_exe` · 3D 모델
  `gen3d.runner.models_ready`(그 폴더나 `q8/` 아래) · 영상 실행기 `genvideo.commands.find_exe` · 영상 모델 `genvideo.commands.find_files`.
- 설정이 비었거나 그 자리에 없으면 `None` — 그때는 원래대로 팩 자리를 본다(받기).
- 설정한 자리에 **있다고 말한 것만** 받지 않는다. 일부만 있으면 나머지는 받는다(모델마다 따로 판정).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

#: 영상 생성 팩 — 모델 id → `genvideo.commands.FILE_PATTERNS` 의 역할.
GENVIDEO_ROLES = {
    "fastwan-5b-q8": "fastwan",
    "wan22-5b-q8": "wan",
    "umt5-xxl-q8": "umt5",
    "wan22-vae": "wan_vae",
    "taew2-2": "tae",
}


def _dir(config: Any, name: str) -> Path | None:
    value = str(getattr(config, name, "") or "").strip()
    return Path(value) if value else None


def _gen3d(config: Any, model: dict[str, Any], platform: str) -> Path | None:
    from .gen3d.runner import find_exe, models_ready

    if model.get("kind") == "binary":
        bin_dir = _dir(config, "gen3d_bin_dir")
        return bin_dir if bin_dir is not None and find_exe(bin_dir, platform) is not None else None
    models = _dir(config, "gen3d_models_dir")
    if models is None:
        return None
    for candidate in (models, models / "q8"):
        if candidate.is_dir() and not models_ready(candidate):
            return candidate
    return None


def _genvideo(config: Any, model: dict[str, Any]) -> Path | None:
    from .genvideo import commands

    model_id = str(model.get("id") or "")
    if model.get("kind") == "binary":
        bin_dir = _dir(config, "genvideo_bin_dir")
        if bin_dir is None:
            return None
        if model_id.startswith("sdcpp-cudart"):
            # cudart DLL 묶음 — 실행기와 같은 자리(또는 한 칸 아래)에 있어야 실행기가 PATH 로 찾는다(`genvideo.runner._env`).
            hits = [*bin_dir.glob("cudart64_*.dll"), *bin_dir.glob("*/cudart64_*.dll")] if bin_dir.is_dir() else []
            return bin_dir if hits else None
        return bin_dir if commands.find_exe([bin_dir]) is not None else None
    role = GENVIDEO_ROLES.get(model_id)
    models = _dir(config, "genvideo_models_dir")
    if role is None or models is None:
        return None
    found = commands.find_files([models]).get(role)
    return found.parent if found is not None else None


def configured_finder(config: Any, *, platform: str | None = None) -> Callable[[str, dict[str, Any]], Path | None]:
    """`ModelFetcher(configured=…)` 에 꽂는 판정 — (팩 id, 모델 칸) → 설정한 자리(있을 때만) · 아니면 None."""
    here = platform or sys.platform

    def find(pack_id: str, model: dict[str, Any]) -> Path | None:
        if pack_id == "gen3d":
            return _gen3d(config, model, here)
        if pack_id == "genvideo":
            return _genvideo(config, model)
        return None

    return find


__all__ = ["GENVIDEO_ROLES", "configured_finder"]
