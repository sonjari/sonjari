"""윈도우 알림 위쪽 큰 그림(hero) 여섯 장을 만든다 — 종류 셋(끝났어요 · 기다려요 · 막혔어요) × 언어 둘(ko · en).

2026-10-27 대표 요청(윈도우 알림에 손자리 디자인). 규격은 토스트 hero 그대로 728x364(2:1) PNG.
색과 글꼴은 앱 `ui/src/tokens.css` 와 같다 — 따뜻한 흑연 바닥(surface-2) · 글자(text-1/3) · 뜻이 있는 색(ok · signal · stop) · 손자리 표식(brand 고리+점) ·
글꼴 Noto Sans KR. 글은 짧게(제목 한 줄 + 보조 한 줄).

    python ui/scripts/make_notify_heroes.py            # → ui/src-tauri/icons/notify/hero_{done,waiting,stuck}_{ko,en}.png
    python ui/scripts/make_notify_heroes.py --preview   # 세 장을 한 판에 이어 붙인 미리보기도 만든다

MSIX 에는 `build_app_package.ps1` 이 `icons/notify/*.png` 를 패키지 `Assets\\notify\\` 로 복사한다. 글꼴 파일(NotoSansKR-VF.ttf)이 없는 PC 에서는 돌지 않는다 —
그림은 저장소에 같이 올려 두므로 보통은 다시 만들 일이 없다.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, SS = 728, 364, 2  # 2배로 그려 줄여서 가장자리를 곱게

# tokens.css 의 값(rgb)
SURFACE_2 = (20, 18, 16)
SURFACE_3 = (27, 24, 21)
LINE = (40, 36, 32)
TEXT_1 = (241, 237, 230)
TEXT_3 = (178, 172, 163)
BRAND = (147, 132, 224)
TONES = {
    "done": {"base": (111, 169, 135), "dim": (40, 74, 58), "bright": (150, 197, 173)},       # ok
    "waiting": {"base": (217, 164, 65), "dim": (108, 82, 33), "bright": (235, 194, 116)},    # signal
    "stuck": {"base": (207, 90, 76), "dim": (92, 40, 34), "bright": (226, 133, 119)},        # stop
}
TEXT = {
    "ko": {"done": ("끝났어요", "결과를 확인해 보세요"), "waiting": ("기다려요", "손자리가 기다리고 있어요"), "stuck": ("막혔어요", "확인이 필요해요")},
    "en": {"done": ("Done", "Your results are ready"), "waiting": ("Waiting", "Sonjari is waiting for you"), "stuck": ("Stuck", "It needs your attention")},
}
FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\NotoSansKR-VF.ttf"),
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts/NotoSansKR-VF.ttf",
]


def font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if path.is_file():
            f = ImageFont.truetype(str(path), size * SS)
            try:
                f.set_variation_by_axes([weight])
            except Exception:  # noqa: BLE001 — 가변 글꼴이 아니면 그대로
                pass
            return f
    raise SystemExit("Noto Sans KR 글꼴(NotoSansKR-VF.ttf)을 찾지 못했다")


def glow(img: Image.Image, center: tuple[int, int], radius: int, color: tuple[int, int, int], strength: float) -> None:
    """tone-dim 색의 부드러운 빛 — 면을 반투명으로 겹치지 않고 한 번만 얹는다."""
    mask = Image.radial_gradient("L").resize((radius * 2, radius * 2))  # 가운데 검정(0) → 가장자리 흰(255)
    # 가장자리 한가운데가 0 이 되게(모서리에서 255) 1.4143 배 — 안 그러면 네모 테두리가 보인다
    mask = mask.point(lambda v: int(max(0.0, 255 - v * 1.4143) * strength))
    layer = Image.new("RGB", mask.size, color)
    img.paste(layer, (center[0] - radius, center[1] - radius), mask)


def ring(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, width: float, color, gap_deg: float = 62.0, start_deg: float = -33.0) -> None:
    """손자리 표식의 고리 — 일부가 열린 원(ontelic-mark.svg: 110/138.2 만큼 그리고 28.2 비움)."""
    outer = r + width / 2  # PIL arc 의 width 는 바깥 반지름에서 안쪽으로 자란다 — 중심선이 r 이 되게
    box = [cx - outer, cy - outer, cx + outer, cy + outer]
    draw.arc(box, start=start_deg, end=start_deg + 360.0 - gap_deg, fill=color, width=int(width))
    for angle in (start_deg, start_deg + 360.0 - gap_deg):  # 둥근 끝
        x, y = cx + r * math.cos(math.radians(angle)), cy + r * math.sin(math.radians(angle))
        draw.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=color)


def mark(draw: ImageDraw.ImageDraw, x: float, y: float, size: float) -> None:
    """작은 손자리 표식(고리 + 점) — 왼쪽 위 라벨 옆."""
    s = size / 64.0
    ring(draw, x + 32 * s, y + 32 * s, 22 * s, 5.2 * s, BRAND, gap_deg=360 * 28.2 / 138.2, start_deg=-33.0)
    dx, dy, dr = x + 44.8 * s, y + 32 * s, 5.0 * s
    draw.ellipse([dx - dr, dy - dr, dx + dr, dy + dr], fill=BRAND)


def glyph(draw: ImageDraw.ImageDraw, tone: str, cx: float, cy: float, color) -> None:
    w = 11 * SS
    if tone == "done":  # 확인 표시
        pts = [(cx - 36 * SS, cy + 2 * SS), (cx - 10 * SS, cy + 28 * SS), (cx + 38 * SS, cy - 26 * SS)]
        draw.line(pts, fill=color, width=w, joint="curve")
        for px, py in (pts[0], pts[2]):
            draw.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill=color)
    elif tone == "waiting":  # 점 셋(기다림)
        for i in (-1, 0, 1):
            x = cx + i * 34 * SS
            draw.ellipse([x - 9 * SS, cy - 9 * SS, x + 9 * SS, cy + 9 * SS], fill=color)
    else:  # 느낌표
        draw.line([(cx, cy - 34 * SS), (cx, cy + 8 * SS)], fill=color, width=w)
        for py in (cy - 34 * SS, cy + 8 * SS):
            draw.ellipse([cx - w / 2, py - w / 2, cx + w / 2, py + w / 2], fill=color)
        draw.ellipse([cx - 7 * SS, cy + 24 * SS, cx + 7 * SS, cy + 38 * SS], fill=color)


def make(tone: str, lang: str) -> Image.Image:
    c = TONES[tone]
    img = Image.new("RGB", (W * SS, H * SS), SURFACE_2)
    # 오른쪽 아래에서 번지는 tone-dim 빛 + 아래 머리카락 선
    glow(img, (int(W * 0.80 * SS), int(H * 0.52 * SS)), int(260 * SS), c["dim"], 0.9)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, (H - 2) * SS, W * SS, H * SS], fill=LINE)

    # 왼쪽 위: 표식 + 「Sonjari」 라벨(두 언어 모두)
    pad = 48 * SS
    mark(draw, pad, 40 * SS, 34 * SS)
    draw.text((pad + 46 * SS, 57 * SS), "Sonjari", font=font(22, 500), fill=TEXT_3, anchor="lm")  # 대표 결정: 두 언어 모두 영어 이름표

    # 제목 + 보조 한 줄
    title, caption = TEXT[lang][tone]
    draw.text((pad, 196 * SS), title, font=font(78, 700), fill=TEXT_1, anchor="ls")
    draw.text((pad, 250 * SS), caption, font=font(26, 500), fill=c["bright"], anchor="ls")

    # 오른쪽: tone 색 고리 + 뜻 그림
    cx, cy = int(W * 0.795 * SS), int(H * 0.5 * SS)
    ring(draw, cx, cy, 88 * SS, 12 * SS, c["base"], gap_deg=62.0)
    glyph(draw, tone, cx, cy, c["base"])
    return img.resize((W, H), Image.LANCZOS)


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "src-tauri" / "icons" / "notify"
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for lang in ("ko", "en"):
        for tone in ("done", "waiting", "stuck"):
            path = out / f"hero_{tone}_{lang}.png"
            make(tone, lang).save(path, optimize=True)
            made.append(path)
            print(path)
    if "--preview" in sys.argv:
        sheet = Image.new("RGB", (W, H * 3 + 24), (0, 0, 0))
        for i, tone in enumerate(("done", "waiting", "stuck")):
            sheet.paste(Image.open(out / f"hero_{tone}_ko.png"), (0, i * (H + 12)))
        preview = out.parents[5] / "generated_reports" / "notify_1027" / "hero_preview.png"
        preview.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(preview)
        print(preview)


if __name__ == "__main__":
    main()
