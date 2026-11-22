"""참조 사진 → 첫 그림(그림 → 영상의 시작 장면) (2026-11-16 · 설계 §10-3 ② · 모델 없음 · 1초 안).

하는 일:
1. 배경 떼기 — **정해진 규칙만**(모델 없음):
   - 투명 PNG 면 그 투명을 그대로 쓴다(`alpha`).
   - 가장자리 띠가 한 색(표준편차 작음)이면 그 색과 가까운 칸을 가장자리에서부터 지운다(`flat_border`).
   - 가장자리가 복잡하면 **못 지운다** — 지웠다고 하지 않고 원본을 바탕 위에 그대로 얹고 `cutout: none` 으로 알린다.
2. 바탕 얹기 — 단색(`#rrggbb`) 또는 바탕 그림(꽉 채워 자름) 위에, 물체를 가운데 · 화면 높이의 `scale` 만큼.
3. 크기 — 콘티 화면비 그대로(16:9 → 832×480).

원본은 건드리지 않는다. 결과는 판 폴더 안 새 파일.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
BORDER = 6
FLAT_STD = 12.0
KEY_DIST = 38.0


def _border(rgb: np.ndarray, width: int = BORDER) -> np.ndarray:
    return np.concatenate([rgb[:width].reshape(-1, 3), rgb[-width:].reshape(-1, 3),
                           rgb[:, :width].reshape(-1, 3), rgb[:, -width:].reshape(-1, 3)])


def cut_out(rgba: np.ndarray) -> tuple[np.ndarray, str]:
    """(H,W,4) uint8 → (알파를 고친 RGBA, 방법). 방법은 alpha · flat_border · none."""
    alpha = rgba[..., 3]
    if (alpha < 250).mean() > 0.01:
        return rgba, "alpha"
    rgb = rgba[..., :3].astype(np.float32)
    edge = _border(rgb)
    if float(edge.std(axis=0).max()) > FLAT_STD:
        return rgba, "none"
    key = np.median(edge, axis=0)
    near = np.sqrt(((rgb - key) ** 2).sum(axis=2)) < KEY_DIST
    # 가장자리와 이어진 「바탕색 칸」만 지운다(물체 안의 같은 색은 남긴다). scipy 없이 numpy 로 번져 나간다(4방향).
    background = np.zeros_like(near)
    background[0], background[-1], background[:, 0], background[:, -1] = near[0], near[-1], near[:, 0], near[:, -1]
    while True:
        grown = background.copy()
        grown[1:] |= background[:-1]
        grown[:-1] |= background[1:]
        grown[:, 1:] |= background[:, :-1]
        grown[:, :-1] |= background[:, 1:]
        grown &= near
        if np.array_equal(grown, background):
            break
        background = grown
    out = rgba.copy()
    out[..., 3] = np.where(background, 0, 255).astype(np.uint8)
    if background.mean() > 0.97:
        return rgba, "none"  # 다 지워지면 물체가 바탕과 같은 색 — 지운 것으로 치지 않는다
    return out, "flat_border"


def _background(spec: str | None, size: tuple[int, int], resolve: Any) -> tuple[Any, str]:
    from PIL import Image, ImageOps

    width, height = size
    text = str(spec or "#1b1b1f").strip()
    if (m := _HEX.fullmatch(text)):
        value = m.group(1)
        color = tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
        return Image.new("RGB", size, color), f"#{value.lower()}"
    path = resolve(text) if resolve else Path(text)
    with Image.open(path) as image:
        return ImageOps.fit(image.convert("RGB"), (width, height)), Path(path).name


def make_first_frame(image: Path, out: Path, *, size: tuple[int, int], background: str | None = None,
                     scale: float = 0.62, resolve: Any = None) -> dict[str, Any]:
    from PIL import Image

    if not 0.2 <= float(scale) <= 0.95:
        raise ValueError("scale 은 0.2~0.95(화면 높이에 대한 물체 크기)")
    with Image.open(image) as source:
        small = source.convert("RGBA")
        small.thumbnail((1024, 1024))  # 첫 그림은 832 폭이 끝 — 큰 사진은 먼저 줄여 번지기를 빠르게
        rgba = np.array(small)
    cut, method = cut_out(rgba)
    ys, xs = np.nonzero(cut[..., 3] > 16)
    if len(xs) == 0:
        raise ValueError("그림에 보이는 물체가 없다(전부 투명)")
    crop = Image.fromarray(cut[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
    canvas, bg_name = _background(background, size, resolve)
    width, height = size
    ratio = min(height * float(scale) / crop.height, width * 0.9 / crop.width)
    crop = crop.resize((max(1, int(crop.width * ratio)), max(1, int(crop.height * ratio))), Image.LANCZOS)
    canvas.paste(crop, ((width - crop.width) // 2, (height - crop.height) // 2), crop)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    notes = []
    if method == "none":
        notes.append("배경을 못 지웠다(가장자리가 한 색이 아니다) — 원본을 그대로 얹었다. 투명 PNG 를 주거나 단색 바탕 사진으로 다시")
    return {"first_image": str(out), "size": [width, height], "cutout": method, "background": bg_name,
            "object_box": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], "notes": notes}
