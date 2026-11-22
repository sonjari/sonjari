"""3D 로 보낼 그림 살피기 — `gen_3d_check` (2026-11-14 · ADR-3D-1 `docs/ADR_3D입력판정_2026-11-14.ko.md`).

손자리는 **재기만** 한다. 어느 길(그대로 · 클로드가 다시 그림 · 묻기)로 갈지는 클로드가 이 숫자와 사람의 뜻으로 정한다.
막는 것은 결정론으로 확실한 것 하나뿐 — 너무 작은 그림(긴 변 256px 미만).

그래픽카드를 쓰지 않는다(CPU · 1초 안). 물체 가림막은 BiRefNet 이 아니라 **투명도 또는 가장자리 바탕색과의 거리**로 잡는다 —
값싼 대신 바탕이 복잡한 사진에서는 가림막이 틀린다. 그래서 `background` 가 단색이 아니면 objects · line_like 를 「믿기 어려움」으로 표시한다.

재는 것(모두 긴 변 256px 로 줄인 그림에서):
- `objects`: 가림막의 연결 덩어리 중 전체 물체 면적의 2% 이상인 것의 수
- `cut_edge`: 가림막이 그림 테두리에 닿는 비율(테두리 픽셀 중)
- `line_like`: 물체 픽셀 중 두께가 얇은(2px 깎으면 사라지는) 픽셀의 비율 — 선만 있는 낙서는 높고 색칠한 그림은 낮다
- `fill`: 그림 안에서 물체가 차지하는 비율
- `background`: plain(투명 · 단색) / busy(사진 같은 바탕)
- `colors`: 물체 안 색 수(16단계로 줄여 센 것)

문턱(`LINE_LIKE_HIGH` 등)은 표시용이다. 실측 표본으로 정했다 — 시험 `test_gen3d_check_1114.py` 의 표본표를 보라.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

MIN_SIDE = 256
WORK_SIDE = 256
#: 이보다 얇은 픽셀 비율이 크면 「선 그림」 — 표본표에서 정한다.
LINE_LIKE_HIGH = 0.6
#: 물체 하나로 칠 덩어리의 최소 크기(물체 면적 대비).
OBJECT_MIN_SHARE = 0.02
#: 바탕색과 이만큼 다르면 물체(0~441 RGB 거리).
BG_DISTANCE = 40.0
#: 테두리의 이 비율 넘게 바탕색에서 벗어나면 바탕이 단색이 아니다.
BUSY_BORDER = 0.25
#: 덩어리를 세기 전에 이어 붙이는 두께(px · 줄인 그림 기준).
JOIN_STEPS = 4


def _load(path: Path) -> tuple[Any, Any, tuple[int, int]]:
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        size = image.size
        image = image.convert("RGBA")
        scale = WORK_SIDE / max(size)
        if scale < 1:
            image = image.resize((max(1, round(size[0] * scale)), max(1, round(size[1] * scale))), Image.Resampling.BILINEAR)
        rgba = np.asarray(image, dtype=np.float32)
    return rgba[..., :3], rgba[..., 3], size


def _border(array: Any) -> Any:
    import numpy as np

    return np.concatenate([array[0], array[-1], array[1:-1, 0], array[1:-1, -1]])


def _components(mask: Any) -> list[int]:
    """4방향 연결 덩어리 크기들(큰 것부터)."""
    height, width = mask.shape
    seen = [[False] * width for _ in range(height)]
    sizes: list[int] = []
    rows = mask.tolist()
    for y in range(height):
        for x in range(width):
            if not rows[y][x] or seen[y][x]:
                continue
            seen[y][x] = True
            queue, count = deque([(y, x)]), 0
            while queue:
                cy, cx = queue.popleft()
                count += 1
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < height and 0 <= nx < width and rows[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        queue.append((ny, nx))
            sizes.append(count)
    return sorted(sizes, reverse=True)


def _erode(mask: Any, steps: int) -> Any:
    import numpy as np

    out = mask.copy()
    for _ in range(steps):
        padded = np.pad(out, 1, constant_values=False)
        out = (padded[1:-1, 1:-1] & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    return out


def check_image(path: Path) -> dict[str, Any]:
    import numpy as np

    path = Path(path)
    rgb, alpha, size = _load(path)
    out: dict[str, Any] = {"size": list(size), "blocked": [], "notes": []}
    if max(size) < MIN_SIDE:
        out["blocked"].append(f"too_small: 긴 변 {max(size)}px — {MIN_SIDE}px 이상이어야 3D 가 모양을 읽는다")
        return out

    transparent = float((_border(alpha) < 16).mean()) > 0.5
    if transparent:
        mask = alpha >= 128
        background = "plain"
    else:
        border = _border(rgb)
        bg = np.median(border, axis=0)
        off_border = float((np.linalg.norm(border - bg, axis=1) > BG_DISTANCE).mean())
        background = "busy" if off_border > BUSY_BORDER else "plain"
        mask = np.linalg.norm(rgb - bg, axis=2) > BG_DISTANCE

    area = int(mask.sum())
    total = mask.size
    out["background"] = background
    out["fill"] = round(area / total, 3)
    if area == 0:
        out["notes"].append("empty: 바탕과 다른 것이 거의 없다 — 그림이 비었거나 바탕과 같은 색이다")
        out.update({"objects": 0, "line_like": None, "cut_edge": 0.0, "colors": 0})
        return out

    # 끊긴 선(돛대 · 밧줄)이 따로 세어지지 않게 4px 이어 붙인 뒤 센다 — 11-14 배 낙서가 「2개」로 잡혔다.
    #   떨어진 물체 사이는 보통 4px(줄인 그림 기준 · 원본 약 1.5%)보다 멀다.
    joined = mask.copy()
    for _ in range(JOIN_STEPS):
        padded = np.pad(joined, 1, constant_values=False)
        joined = padded[1:-1, 1:-1] | padded[:-2, 1:-1] | padded[2:, 1:-1] | padded[1:-1, :-2] | padded[1:-1, 2:]
    sizes = _components(joined)
    area_joined = int(joined.sum())
    out["objects"] = sum(1 for count in sizes if count >= OBJECT_MIN_SHARE * area_joined)
    thin = mask & ~_erode(mask, 2)
    # 2px 깎아 사라지는 몫 — 깎은 뒤 살아남은 덩어리를 다시 불려 두께 있는 면을 되돌린 뒤 센다(외곽선 1겹은 늘 얇으니 빼고 본다).
    core = _erode(mask, 2)
    grown = core.copy()
    for _ in range(3):
        padded = np.pad(grown, 1, constant_values=False)
        grown = padded[1:-1, 1:-1] | padded[:-2, 1:-1] | padded[2:, 1:-1] | padded[1:-1, :-2] | padded[1:-1, 2:]
    line_pixels = int((thin & ~grown).sum())
    out["line_like"] = round(line_pixels / area, 3)
    out["cut_edge"] = round(float(_border(mask.astype(np.float32)).mean()), 3)
    inside = (rgb[mask] // 16).astype(np.int32)
    out["colors"] = int(len({tuple(row) for row in inside.tolist()}))

    if background == "busy":
        out["notes"].append("busy_background: 바탕이 단색이 아니다(사진 같음) — objects · line_like 는 믿기 어렵다")
    if out["objects"] >= 2:
        out["notes"].append(f"several_objects: 덩어리 {out['objects']}개 — 3D 는 물체 하나씩이다. 무엇을 만들지 사람에게 묻거나 나눠라")
    if out["line_like"] is not None and out["line_like"] >= LINE_LIKE_HIGH and background == "plain":
        out["notes"].append("line_drawing: 선만 있는 그림 같다 — 그대로 넣으면 선이 철사로 나온다(11-14 배 낙서). 색면 · 명암으로 다시 그려라")
    if out["cut_edge"] > 0.05 and background == "plain":
        out["notes"].append("cut_off: 물체가 그림 가장자리에서 잘렸다 — 잘린 쪽은 3D 에서 비거나 짐작으로 채워진다")
    return out
