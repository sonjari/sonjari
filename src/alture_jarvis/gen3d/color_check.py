"""3D 색 대조 검사 — 구운 3D 의 색 그림(텍스처)이 넣은 그림의 물체와 크게 다른가 (2026-11-16 밤).

## 왜

11-16 밤 팩 잇기 시험: 평평한 파란 아이콘풍 로봇 그림을 세 번 구웠더니 3D 색 그림이 검게 나왔다(검은 칸 57% · 100% · 26%).
배경 지우기 · 실행기 · 색 단위는 정상이었고, 풀기 직전 PBR 값이 어둡고 금속성 0.40 — **3D 모델의 예측** 이었다(씨앗마다 크게 흔들림).
모양은 멀쩡해서 영수증 숫자로는 안 보였고, 사람이 판 그림을 열기 전엔 몰랐다(영상 첫 장면으로 실루엣이 넘어갔다).

## 기준 (26판 역검증 · 11-16)

- **검은 칸 비율**(색 그림에서 밝기 2 이하인 칸): 로봇 세 판 0.57 · 1.00 · 0.26 / 정상 23판 모두 0.04 이하.
- **밝기 비율**(색 그림 밝기 ÷ 넣은 그림 물체 밝기): 로봇 0.09 · 0.00 · 0.41 / 정상 23판 0.28 이상.
- 판정: 검은 칸 > 0.10 **또는** 밝기 비율 < 0.20 → 이상. 26판에 대면 로봇 셋 다 걸리고 정상 23판은 0.
- 「평평한 면 비율」로 굽기 전에 가르는 것은 버렸다 — 리락쿠마(0.65~0.80)도 평평한데 색은 정상이었다(헛경고).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

DARK_SHARE_MAX = 0.10
RATIO_MIN = 0.20
_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _load(path: Path, size: int = 256) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(path).convert("RGB").resize((size, size)), dtype=np.float32)


def object_luma(image: Path) -> float | None:
    """넣은 그림에서 물체(가장자리 바탕색과 다른 칸)의 평균 밝기. 물체를 못 찾으면 None."""
    pixels = _load(image)
    border = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    background = np.median(border, axis=0)
    mask = np.abs(pixels - background).sum(axis=2) > 40
    if mask.sum() < 50:
        return None
    return float((pixels @ _LUMA)[mask].mean())


def measure(image: Path, texture: Path) -> dict[str, Any]:
    """`{ok, dark_share, ratio, input_luma, texture_luma, why}` — 재지 못하면 ok=None(모름 · 막지 않음)."""
    try:
        luma = _load(texture) @ _LUMA
    except Exception as exc:  # noqa: BLE001 — 재기는 덤
        return {"ok": None, "why": f"색 그림을 못 읽음: {exc}"[:200]}
    dark = luma <= 2.0
    dark_share = float(dark.mean())
    texture_luma = float(luma[~dark].mean()) if (~dark).mean() > 0.05 else float(luma.mean())
    try:
        input_luma = object_luma(image)
    except Exception:  # noqa: BLE001
        input_luma = None
    ratio = (texture_luma / max(input_luma, 1.0)) if input_luma else None
    why: list[str] = []
    if dark_share > DARK_SHARE_MAX:
        why.append(f"색 그림의 {dark_share:.0%} 가 검다(기준 {DARK_SHARE_MAX:.0%})")
    if ratio is not None and ratio < RATIO_MIN:
        why.append(f"넣은 그림보다 많이 어둡다(밝기 비율 {ratio:.2f} · 기준 {RATIO_MIN})")
    return {
        "ok": not why, "dark_share": round(dark_share, 3), "ratio": None if ratio is None else round(ratio, 2),
        "input_luma": None if input_luma is None else round(input_luma), "texture_luma": round(texture_luma),
        "why": why,
    }


def score(result: dict[str, Any]) -> float:
    """다시 구운 판끼리 고를 때 — 높을수록 낫다(검은 칸이 적고 밝기가 원본에 가까울수록)."""
    dark = float(result.get("dark_share") or 0.0)
    ratio = result.get("ratio")
    closeness = 1.0 - min(abs(1.0 - float(ratio)), 1.0) if ratio is not None else 0.5
    return closeness - dark


__all__ = ["DARK_SHARE_MAX", "RATIO_MIN", "measure", "object_luma", "score"]
