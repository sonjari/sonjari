"""Ontelic 마크(고리와 점)로 앱 아이콘·트레이 상태 프레임을 만든다 (2026-09-15, 로고 시안 A 확정).

    python scripts/make_brand_icons.py

모양은 앱 표식 `ui/src/workspace/JarvisMark.tsx` 와 같다(32 칸 r11 · 획 2.6 · 점선 55/14.1 · -33°를 64 칸으로 두 배).
24px 아래는 획을 굵힌 **작은판**을 쓴다 — 가는 획은 16px 트레이에서 흐려진다.

만드는 것
- `ui/src-tauri/icons/`  icon.png(1024) · icon.ico(16~256, 32 이하는 작은판) · 32/64/128/128@2x · Square*Logo · StoreLogo
- `ui/src-tauri/icons/tray/*.rgba`  32×32 RGBA 원시 바이트 — 트레이가 상태마다 바꿔 끼운다(lib.rs `tray_status`)
    brand_0..7  일하는 중(고리가 45°씩 돈다) · brand_dim 듣는 중(숨쉬기) · signal_on/signal_dim 승인 기다림(숨쉬기) ·
    stop 멈춤 · offline 연결 끊김
- `ui/public/ontelic-mark.svg` · `ontelic-mark-small.svg`  원본 벡터(파비콘·문서용)
"""

from __future__ import annotations

import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "ui" / "src-tauri" / "icons"
TRAY = ICONS / "tray"
PUBLIC = ROOT / "ui" / "public"

MARK_ON_DARK = (0xBA, 0xB0, 0xF0)
#: 트레이는 밝은·어두운 작업 표시줄 둘 다에 놓인다 — 중간 밝기 보라가 양쪽에서 읽힌다.
TONES = {"brand": (0x93, 0x84, 0xE0), "signal": (0xD9, 0xA4, 0x41), "stop": (0xCF, 0x5A, 0x4C), "offline": (0x8A, 0x90, 0x99)}

# (반지름, 획, 점선 길이, 점 x, 점 반지름) — 64 칸
REGULAR = (22.0, 5.2, 110.0, 44.8, 5.0)
SMALL = (21.0, 8.0, 102.0, 45.0, 7.0)

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <circle cx="32" cy="32" r="{r}" fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-dasharray="{d} {g}" transform="rotate(-33 32 32)"/>
  <circle cx="{dx}" cy="32" r="{dr}" fill="{c}"/>
</svg>
"""


def draw_mark(size: int, color: tuple[int, int, int], *, spec=REGULAR, rotate: float = 0.0, scale: float = 1.0,
              alpha: int = 255, base: Image.Image | None = None) -> Image.Image:
    """64 칸 마크를 `size` px 에 그린다. 8배로 그리고 줄여 가장자리를 부드럽게 한다."""
    ss = 8
    big = size * ss
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    unit = big / 64 * scale
    offset = big / 2 - 32 * unit
    cx = cy = big / 2
    radius, stroke, dash, dot_x, dot_r = spec
    r = radius * unit
    w = stroke * unit
    sweep = dash / (2 * math.pi * radius) * 360
    start = -33 + rotate
    end = start + sweep
    fill = (*color, alpha)
    box = (cx - r - w / 2, cy - r - w / 2, cx + r + w / 2, cy + r + w / 2)
    # PIL 호는 선 중심이 아니라 바깥 상자 기준이다 — 두께를 안쪽으로 채우므로 상자를 획 절반만큼 넓힌다.
    draw.arc(box, start, end, fill=fill, width=int(round(w)))
    for angle in (start, end):  # 둥근 끝
        a = math.radians(angle)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        draw.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=fill)
    a = math.radians(rotate)
    dx = (dot_x - 32) * unit
    px, py = cx + dx * math.cos(a), cy + dx * math.sin(a)
    dr = dot_r * unit
    draw.ellipse((px - dr, py - dr, px + dr, py + dr), fill=fill)
    del offset
    small = layer.resize((size, size), Image.LANCZOS)
    if base is not None:
        base.alpha_composite(small)
        return base
    return small


def tile(size: int) -> Image.Image:
    """스토어·시작 메뉴 타일 — 흑연 둥근 사각형 + 밝은 보라 마크. 작은 크기는 작은판."""
    ss = 4
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    grad = Image.new("RGBA", (big, big))
    top, bottom = (0x1B, 0x1F, 0x27), (0x10, 0x12, 0x16)
    gd = ImageDraw.Draw(grad)
    for y in range(big):
        t = y / max(1, big - 1)
        gd.line([(0, y), (big, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (big, big), 0)
    radius = int(big * 0.22)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)
    border = max(1, big // 88)
    ImageDraw.Draw(img).rounded_rectangle((0, 0, big - 1, big - 1), radius=radius, outline=(0x2A, 0x2F, 0x38, 255), width=border)
    img = img.resize((size, size), Image.LANCZOS)
    spec = SMALL if size <= 32 else REGULAR
    return draw_mark(size, MARK_ON_DARK, spec=spec, scale=0.62 if size > 32 else 0.74, base=img)


def glyph(size: int, color=MARK_ON_DARK) -> Image.Image:
    return draw_mark(size, color, spec=SMALL if size <= 32 else REGULAR, scale=0.9)


def write_ico(path: Path, sizes: list[int]) -> None:
    """PNG 를 담은 ICO — 크기마다 따로 그린 그림을 넣는다(PIL 은 가장 큰 그림을 줄여 넣는다)."""
    blobs = []
    for size in sizes:
        buf = io.BytesIO()
        tile(size).save(buf, "PNG")
        blobs.append((size, buf.getvalue()))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    data = b""
    for size, blob in blobs:
        entries += struct.pack("<BBBBHHII", 0 if size >= 256 else size, 0 if size >= 256 else size, 0, 0, 1, 32,
                               len(blob), offset + len(data))
        data += blob
    path.write_bytes(header + entries + data)


#: 스토어 패키지 그림 — 배율(scale)·표시 크기(targetsize)마다 **따로 그린** 한 장씩 (2026-09-29).
MSIX_SCALES = (100, 125, 150, 200, 400)
MSIX_TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256)


def write_msix_assets(folder: Path) -> list[str]:
    """노트북 베타에서 로고가 「이상한 것」으로 보였다 — 44px 한 장만 넣었기 때문이다 (2026-09-29).

    작업 표시줄·시작 메뉴는 `Square44x44Logo` 의 **targetsize·unplated** 판을 찾는다. 없으면 윈도우가 44px 한 장을
    늘리거나 강조색 **판(plate) 위에 작게 얹어서** 바탕화면 아이콘(exe 의 icon.ico)과 다른 그림이 된다.
    그래서 크기마다 따로 그린 판을 만들고, 빌드가 `resources.pri` 로 묶는다(build_app_package.ps1).
    unplated 판도 바탕화면과 **같은 타일**(흑연 사각형+보라 마크)을 쓴다 — 대표 판정: 「정확히 저 로고로」.
    """
    if folder.exists():
        for old in folder.glob("*.png"):
            old.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def save(img: Image.Image, name: str) -> None:
        img.save(folder / name)
        written.append(name)

    for scale in MSIX_SCALES:
        save(tile(round(44 * scale / 100)), f"Square44x44Logo.scale-{scale}.png")
        save(tile(round(150 * scale / 100)), f"Square150x150Logo.scale-{scale}.png")
        save(tile(round(50 * scale / 100)), f"StoreLogo.scale-{scale}.png")
    for size in MSIX_TARGET_SIZES:
        img = tile(size)
        save(img, f"Square44x44Logo.targetsize-{size}.png")
        save(img, f"Square44x44Logo.targetsize-{size}_altform-unplated.png")
        save(img, f"Square44x44Logo.targetsize-{size}_altform-lightunplated.png")
    return written


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    TRAY.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)

    tile(1024).save(ICONS / "icon.png")
    for name, size in {"32x32.png": 32, "64x64.png": 64, "128x128.png": 128, "128x128@2x.png": 256}.items():
        tile(size).save(ICONS / name)
    for size in (30, 44, 71, 89, 107, 142, 150, 284, 310):
        tile(size).save(ICONS / f"Square{size}x{size}Logo.png")
    tile(50).save(ICONS / "StoreLogo.png")
    write_ico(ICONS / "icon.ico", [16, 24, 32, 48, 64, 128, 256])
    write_msix_assets(ICONS / "msix")

    frames = {f"brand_{i}": draw_mark(32, TONES["brand"], spec=SMALL, rotate=45 * i, scale=0.94) for i in range(8)}
    frames["brand_dim"] = draw_mark(32, TONES["brand"], spec=SMALL, scale=0.94, alpha=110)  # 듣는 중 — 숨쉬기
    frames["signal_on"] = draw_mark(32, TONES["signal"], spec=SMALL, scale=0.94)
    frames["signal_dim"] = draw_mark(32, TONES["signal"], spec=SMALL, scale=0.94, alpha=110)
    frames["stop"] = draw_mark(32, TONES["stop"], spec=SMALL, scale=0.94)
    frames["offline"] = draw_mark(32, TONES["offline"], spec=SMALL, scale=0.94, alpha=200)
    for name, img in frames.items():
        (TRAY / f"{name}.rgba").write_bytes(img.convert("RGBA").tobytes())
        img.save(TRAY / f"{name}.png")  # 사람이 눈으로 확인하는 용 — 코드는 .rgba 를 쓴다

    for name, spec in (("ontelic-mark.svg", REGULAR), ("ontelic-mark-small.svg", SMALL)):
        radius, stroke, dash, dot_x, dot_r = spec
        gap = round(2 * math.pi * radius - dash, 1)
        (PUBLIC / name).write_text(SVG.format(r=radius, c="#9384E0", w=stroke, d=dash, g=gap, dx=dot_x, dr=dot_r),
                                   encoding="utf-8")
    print("icons:", sorted(p.name for p in ICONS.glob("*.png")))
    print("tray frames:", len(frames))


if __name__ == "__main__":
    main()
