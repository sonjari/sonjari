"""사진 손질 — 3D 로 굽기 전 1차 보정 (2026-11-15 · 설계 `docs/설계_3D두번굽기_분업_2026-11-15.ko.md` §4-1).

손자리는 손, 클로드는 판단: 클로드는 **번호 격자 그림**을 보고 「C3 은 배경으로 · D7 은 주변 색으로」처럼 칸만 말한다(좌표를 지어내지 않는다).
11-15 리락쿠마(290×347 사진): 작아서 얼굴 · 햄버거가 뭉개짐 · 정수리 열쇠고리 고리가 혹으로 · 볼 점무늬가 좁쌀로 나왔다.

- 자르기(선택 · 칸 범위) → 긴 변 `size` 로 키우기(LANCZOS) → 지우기(칸마다 「배경으로」 흰색 / 「주변 색으로」 둘레 띠 가운데값)
  → 잔무늬 펴기(가운데값 필터 · 가장자리 보존) → 흰 바탕 여백.
- 「배경으로」는 윤곽째 지운다(튀어나온 고리) — 실행기(BiRefNet)가 흰 바탕을 배경으로 지운다. 「주변 색으로」는 안쪽 점 · 반사.
- AI 로 새로 그려 넣지는 않는다(지우고 펴기만 · 새 부품 없음).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

#: 잔무늬 펴기 — **키우기 전 원래 크기에서** 건다(11-15: 키운 뒤에 걸면 점이 필터보다 커져 안 지워지고 햄버거 눈 · 코만 뭉갬).
SMOOTH_LEVELS = {0: (), 1: (3,), 2: (5,), 3: (5, 3)}
GRID_RANGE = (6, 48)
_CELL = re.compile(r"^([A-Za-z]{1,2})(\d{1,2})$")


def col_name(i: int) -> str:
    """0 → A · 25 → Z · 26 → AA (격자 열 이름)."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_cell(name: str, cols: int, rows: int) -> tuple[int, int]:
    m = _CELL.match(str(name).strip())
    if not m:
        raise ValueError(f"칸 이름은 「C3」 꼴 — 받은 것: {name!r}")
    letters, num = m.group(1).upper(), int(m.group(2))
    c = 0
    for ch in letters:
        c = c * 26 + (ord(ch) - 64)
    c -= 1
    r = num - 1
    if not (0 <= c < cols and 0 <= r < rows):
        raise ValueError(f"칸 {name} 이 격자({col_name(cols - 1)}{rows}) 밖이다")
    return c, r


def _cells_box(spec: str, cols: int, rows: int) -> tuple[int, int, int, int]:
    """「C3」 또는 「C3:E5」 → (c0, r0, c1, r1) 끝 포함."""
    parts = [p for p in str(spec).split(":") if p]
    a = parse_cell(parts[0], cols, rows)
    b = parse_cell(parts[-1], cols, rows)
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def grid_image(img: Any, cols: int, rows: int, view: tuple[int, int, int, int] | None = None, cell_px: int = 0) -> Any:
    """칸 선 + 가장자리 이름표(위: 열 글자 · 왼쪽: 행 번호). 칸 안에는 글자를 쓰지 않는다 — 48칸에서 이름이 그림을 덮었다(11-15).
    view=(c0, r0, c1, r1) 면 그 칸들만 잘라 크게(칸 하나 cell_px 픽셀)."""
    from PIL import Image, ImageDraw

    from .preview import _font

    src = img.convert("RGB")
    w, h = src.size
    cw, ch = w / cols, h / rows
    c0, r0, c1, r1 = view if view else (0, 0, cols - 1, rows - 1)
    box = (int(c0 * cw), int(r0 * ch), int((c1 + 1) * cw), int((r1 + 1) * ch))
    part = src.crop(box)
    nc, nr = c1 - c0 + 1, r1 - r0 + 1
    if cell_px:
        part = part.resize((nc * cell_px, nr * cell_px), Image.LANCZOS)
    pw, ph = part.size
    sx, sy = pw / nc, ph / nr
    head = max(18, int(min(sx, sy) * 0.6)) if view else 22
    font = _font(max(10, min(16, int(head * 0.6))))
    out = Image.new("RGB", (pw + head, ph + head), (250, 250, 250))
    out.paste(part, (head, head))
    draw = ImageDraw.Draw(out)
    for i in range(nc + 1):
        x = head + i * sx
        draw.line([(x, head), (x, head + ph)], fill=(0, 190, 255), width=1)
    for j in range(nr + 1):
        y = head + j * sy
        draw.line([(head, y), (head + pw, y)], fill=(0, 190, 255), width=1)
    step_c = max(1, int(np.ceil(18 / sx)))  # 이름표가 겹치지 않게 몇 칸 걸러
    step_r = max(1, int(np.ceil(14 / sy)))
    for i in range(0, nc, step_c):
        draw.text((head + i * sx + 2, 3), col_name(c0 + i), fill=(200, 0, 80), font=font)
    for j in range(0, nr, step_r):
        draw.text((2, head + j * sy + 2), str(r0 + j + 1), fill=(200, 0, 80), font=font)
    return out


def prep_image(src: Path, out_dir: Path, *, size: int = 1024, grid: int = 16, crop: str | None = None,
               erase: list[dict[str, Any]] | None = None, smooth: int = 0, margin: float = 0.06,
               view: str | None = None) -> dict[str, Any]:
    """손질본 · 격자 그림 · 전/후 그림을 out_dir 에 쓴다. 칸 이름은 **키운 그림의 격자** 기준(같은 grid 로 다시 부르면 같은 칸)."""
    from PIL import Image, ImageFilter

    if not GRID_RANGE[0] <= int(grid) <= GRID_RANGE[1]:
        raise ValueError(f"grid 는 {GRID_RANGE[0]}~{GRID_RANGE[1]}")
    if int(smooth) not in SMOOTH_LEVELS:
        raise ValueError("smooth 는 0~3")
    if not 256 <= int(size) <= 2048:
        raise ValueError("size 는 256~2048")
    out_dir.mkdir(parents=True, exist_ok=True)
    original = Image.open(src).convert("RGB")
    im = original
    notes: list[str] = []
    if crop:
        # 자르기 칸은 원본 그림의 격자 기준(같은 grid)
        w0, h0 = im.size
        c0, r0, c1, r1 = _cells_box(crop, grid, grid)
        box = (int(c0 * w0 / grid), int(r0 * h0 / grid), int((c1 + 1) * w0 / grid), int((r1 + 1) * h0 / grid))
        im = im.crop(box)
        notes.append(f"{crop} 로 잘랐다")
    for k in SMOOTH_LEVELS[int(smooth)]:
        im = im.filter(ImageFilter.MedianFilter(k))
    if SMOOTH_LEVELS[int(smooth)]:
        notes.append(f"잔무늬를 폈다(세기 {smooth} · 원래 크기에서)")
    w, h = im.size
    scale = int(size) / max(w, h)
    big = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    if scale > 1.05:
        notes.append(f"{scale:.1f}배로 키웠다({w}×{h} → {big.size[0]}×{big.size[1]})")
    a = np.asarray(big).astype(np.float64)
    H, W, _ = a.shape
    cw, ch = W / grid, H / grid
    erased = 0
    for item in erase or []:
        spec = str(item.get("cells") or item.get("cell") or "")
        mode = str(item.get("mode") or "fill")
        if mode not in ("bg", "fill"):
            raise ValueError("mode 는 bg(배경으로 · 윤곽째) 또는 fill(주변 색으로)")
        c0, r0, c1, r1 = _cells_box(spec, grid, grid)
        x0, y0, x1, y1 = int(c0 * cw), int(r0 * ch), int((c1 + 1) * cw), int((r1 + 1) * ch)
        if mode == "bg":
            a[y0:y1, x0:x1] = 255.0
        else:
            pad = max(4, int(min(cw, ch) * 0.35))
            Y0, Y1, X0, X1 = max(0, y0 - pad), min(H, y1 + pad), max(0, x0 - pad), min(W, x1 + pad)
            ring = np.ones((Y1 - Y0, X1 - X0), dtype=bool)
            ring[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = False
            around = a[Y0:Y1, X0:X1][ring]
            fill = np.median(around, axis=0)
            # 칸 가장자리가 튀지 않게 가운데로 갈수록 채움색 · 가장자리는 둘레와 섞음
            yy, xx = np.mgrid[y0:y1, x0:x1]
            d = np.minimum.reduce([yy - y0, y1 - 1 - yy, xx - x0, x1 - 1 - xx]).astype(float)
            wgt = np.clip(d / max(2.0, pad * 0.5), 0, 1)[..., None]
            a[y0:y1, x0:x1] = a[y0:y1, x0:x1] * (1 - wgt) + fill * wgt
        erased += (c1 - c0 + 1) * (r1 - r0 + 1)
    if erased:
        notes.append(f"{erased}칸을 지웠다")
    done = Image.fromarray(a.clip(0, 255).astype(np.uint8))
    # 흰 바탕 여백
    pad_px = int(max(done.size) * margin)
    canvas = Image.new("RGB", (done.size[0] + 2 * pad_px, done.size[1] + 2 * pad_px), (255, 255, 255))
    canvas.paste(done, (pad_px, pad_px))
    stem = src.stem[:40]
    prepped = out_dir / f"{stem}_prep.png"
    canvas.save(prepped)
    # 격자는 지우기 전 「키운 그림」 위에 — 다음 부르기에서 같은 칸 이름으로 고르게
    grid_path = out_dir / f"{stem}_grid{grid}.png"
    grid_image(big, grid, grid).save(grid_path)
    zoom_path = None
    if view:
        # 일부 칸만 크게(칸 하나 60px) — 작은 고리 · 점을 고를 때
        zoom_path = out_dir / f"{stem}_grid{grid}_{view.replace(':', '-')}.png"
        grid_image(big, grid, grid, _cells_box(view, grid, grid), cell_px=60).save(zoom_path)
    side = out_dir / f"{stem}_before_after.png"
    before = big.resize(done.size)
    pair = Image.new("RGB", (done.size[0] * 2 + 12, done.size[1]), (255, 255, 255))
    pair.paste(before, (0, 0))
    pair.paste(done, (done.size[0] + 12, 0))
    pair.thumbnail((1500, 1500))
    pair.save(side)
    return {"image": str(prepped), "grid": str(grid_path), "zoom": str(zoom_path) if zoom_path else None,
            "before_after": str(side), "size": list(canvas.size),
            "grid_n": int(grid), "scale": round(scale, 2), "erased_cells": erased, "smooth": int(smooth), "notes": notes,
            "how": ("격자 그림(칸 이름 = 왼쪽 위 글자)을 보고 지울 칸을 erase=[{cells: 「C3」 또는 「C3:D4」, mode: bg|fill}] 로 다시 부른다. "
                    "bg = 흰 바탕으로(튀어나온 고리 · 딸려 온 배경 덩어리 — 윤곽째), fill = 주변 색으로(안쪽 점 · 반사). "
                    "작은 것은 grid 를 키우고(32 · 48) view=「M3:Q8」 로 그 칸들만 크게 본다. 이름은 가장자리(위 열 글자 · 왼쪽 행 번호). 손질본(image)을 gen_3d 에 넣는다.")}
