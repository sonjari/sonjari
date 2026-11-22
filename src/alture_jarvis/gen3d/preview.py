"""미리보기 그림 — 앞 · 옆 webp(긴 변 ≤512 · 설계 §3-1) (2026-11-14).

블렌더 · OpenGL 없이 numpy + Pillow 로 그린다: 직교 투영 · 뒷면 버림 · 먼 면부터 칠하기(화가 방식).
면 색은 바탕색 그림에서 면 가운데 UV 의 색 × 빛(앞 위에서 오는 빛 하나). 클로드가 「모양이 섰나」를 보는 용도라 이 정도면 된다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .glb import Mesh

MAX_SIDE = 512

#: 이름 → 보는 방향(카메라 → 물체). glTF 는 y 위 · 물체의 앞이 +z.
#: ★ 11-14 실측: trellis 는 입력 그림의 카메라 각도를 지키지 않고 **물체를 제 자세로** 놓는다 — 옆모습으로 그린 배도, 정면으로
#:   그린 캐릭터도 앞(뱃머리 · 얼굴)이 z 축을 본다. 그래서 「앞」은 입력 그림과 같은 모습이 아닐 수 있다(배는 「옆」이 입력에 가깝고,
#:   같은 그림 두 판이 서로 좌우 반대로 놓였다 — 방향은 판마다 고정이 아니다).
VIEWS = {
    "front": np.array([0.0, 0.0, -1.0]),
    "side": np.array([-1.0, 0.0, 0.0]),
}


#: 6방향 판(설계 `설계_3D두번굽기_분업` §4-2) — glTF(y 위 · 앞 +z) 기준. 위 · 아래는 화면 위쪽을 -z(뒤)로 둔다.
SIX_VIEWS = (
    ("앞", np.array([0.0, 0.0, -1.0])),
    ("뒤", np.array([0.0, 0.0, 1.0])),
    ("왼쪽", np.array([1.0, 0.0, 0.0])),
    ("오른쪽", np.array([-1.0, 0.0, 0.0])),
    ("위", np.array([0.0, -1.0, 0.0])),
    ("아래", np.array([0.0, 1.0, 0.0])),
)


def _basis(view: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    up = np.array([0.0, 1.0, 0.0])
    if abs(float(np.dot(view, up))) > 0.99:  # 위 · 아래에서 볼 때: 화면 위쪽 = 물체의 뒤(-z)
        up = np.array([0.0, 0.0, -1.0])
    right = np.cross(view, up)
    right /= np.linalg.norm(right)
    true_up = np.cross(right, view)
    return right, true_up


#: 그림 둘레 여백(한 변의 몫) — render · 칸 → 3D 자리 바꾸기가 같은 값을 쓴다.
MARGIN = 0.05


def frame(mesh: Mesh, view: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float, float]:
    """한 방향 그림의 투영 틀: (오른쪽 축 · 위 축 · 가로 가운데 · 세로 가운데 · 긴 폭). render 와 region 이 같은 틀을 쓴다."""
    right, up = _basis(view)
    xs = mesh.positions @ right
    ys = mesh.positions @ up
    lo_x, hi_x, lo_y, hi_y = float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())
    span = max(hi_x - lo_x, hi_y - lo_y, 1e-9)
    return right, up, (lo_x + hi_x) / 2, (lo_y + hi_y) / 2, span


def to_unit(points: np.ndarray, view: np.ndarray, fr: tuple[np.ndarray, np.ndarray, float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    """3D 점 → 그림 위 자리(0~1 · 왼쪽 위가 0,0)."""
    right, up, mx, my, span = fr
    scale = (1 - 2 * MARGIN) / span
    u = (points @ right - mx) * scale + 0.5
    v = 0.5 - (points @ up - my) * scale
    return u, v


def region(mesh: Mesh, view_name: str, cells: str, grid: int, depth: float | None) -> dict:
    """모양 판 격자 칸(「C3:E5」) → 3D 자리. 그 방향에서 칸을 지나는 기둥이 겉면과 처음 닿는 곳부터 depth(모델 단위)까지.
    depth=None 이면 **보는 쪽 절반**(물체 두께의 반) — 따로 떨어진 조각을 통째로 지울 때(erase_part).
    11-15: 기둥 전체로 잡았더니 뒤에서 짚은 목 띠와 같은 높이의 **앞쪽 햄버거 층 조각 셋**까지 지웠다.

    돌려주는 것: sel(꼭짓점 참/거짓) · box(가운데 · 축 셋 · 반 길이 셋 — 블렌더에 넘기는 모양). 칸 안에 점이 없으면 ValueError."""
    from .prep import _cells_box

    views = dict(SIX_VIEWS)
    if view_name not in views:
        raise ValueError(f"방향은 {[n for n, _ in SIX_VIEWS]} 가운데 하나")
    view = views[view_name]
    c0, r0, c1, r1 = _cells_box(cells, grid, grid)
    fr = frame(mesh, view)
    u, v = to_unit(mesh.positions, view, fr)
    u0, u1, v0, v1 = c0 / grid, (c1 + 1) / grid, r0 / grid, (r1 + 1) / grid
    inside = (u >= u0) & (u < u1) & (v >= v0) & (v < v1)
    if not inside.any():
        raise ValueError(f"{view_name} {cells} 칸에 물체가 없다 — 모양 판 격자를 다시 볼 것")
    along = mesh.positions @ view  # 카메라 → 물체 방향 · 작을수록 카메라에 가깝다
    near = float(along[inside].min())
    if depth is None:
        depth = (float(along.max()) - float(along.min())) / 2
    sel = inside & (along <= near + depth)
    right, up, mx, my, span = fr
    scale = (1 - 2 * MARGIN) / span
    cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
    center = right * ((cu - 0.5) / scale + mx) + up * ((0.5 - cv) / scale + my) + view * (near + depth / 2)
    half = np.array([(u1 - u0) / 2 / scale, (v1 - v0) / 2 / scale, depth / 2])
    return {"sel": sel, "box": {"center": center.tolist(), "axes": [right.tolist(), up.tolist(), view.tolist()],
                                "half": half.tolist()}, "count": int(sel.sum())}


def face_colors(mesh: Mesh) -> np.ndarray:
    n = len(mesh.faces)
    if mesh.texture is None or mesh.uv is None:
        return np.full((n, 3), 200.0)
    tex = np.asarray(mesh.texture, dtype=np.float64)
    h, w = tex.shape[:2]
    uv = mesh.uv[mesh.faces].mean(axis=1)
    u = np.clip((uv[:, 0] % 1.0) * (w - 1), 0, w - 1).astype(np.int64)
    v = np.clip((uv[:, 1] % 1.0) * (h - 1), 0, h - 1).astype(np.int64)  # glTF UV 원점은 왼쪽 위
    return tex[v, u, :3]


def render(mesh: Mesh, view: np.ndarray, side: int = MAX_SIDE, colors: np.ndarray | None = None, limit: int = MAX_SIDE):
    from PIL import Image, ImageDraw

    side = min(int(side), int(limit))
    tri = mesh.positions[mesh.faces]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(normal, axis=1)
    normal = normal / np.maximum(length, 1e-20)[:, None]
    facing = normal @ (-view) > 0
    right, up = _basis(view)
    if colors is None:
        colors = face_colors(mesh)
    light = -view + up * 0.6 + right * 0.3
    light /= np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.clip(normal @ light, 0, 1)
    rgb = np.clip(colors * shade[:, None], 0, 255).astype(np.uint8)

    depth = (tri @ view).mean(axis=1)
    fr = frame(mesh, view)
    pu, pv = to_unit(tri.reshape(-1, 3), view, fr)
    px = pu.reshape(-1, 3) * side
    py = pv.reshape(-1, 3) * side

    image = Image.new("RGB", (side, side), (245, 245, 243))
    draw = ImageDraw.Draw(image)
    order = np.argsort(-depth)  # 먼 것부터
    order = order[facing[order]]
    for i in order.tolist():
        pts = ((px[i, 0], py[i, 0]), (px[i, 1], py[i, 1]), (px[i, 2], py[i, 2]))
        color = tuple(int(c) for c in rgb[i])
        draw.polygon(pts, fill=color, outline=color)
    return image


def _font(size: int):
    from PIL import ImageFont

    for path in ("C:/Windows/Fonts/malgun.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                 "/System/Library/Fonts/Supplemental/AppleGothic.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


#: 모양 판의 면 색 — 프린트 판과 같은 회색(색이 모양을 가리지 않게 · 11-15 햄버거가 색 판에선 좋아 보였는데 실제론 매끈한 통).
SHAPE_GRAY = 200.0


def _gridded(img, grid: int):
    """그림 한 칸에 사진 손질과 같은 격자(위 열 글자 · 왼쪽 행 번호)를 깐다 — 클로드가 「뒤 G9:J10」처럼 자리를 짚는다."""
    from .prep import grid_image

    return grid_image(img, grid, grid)


def view_sheet(mesh: Mesh, target: Path, cell: int = 480, colors: np.ndarray | None = None, shape: bool = False,
               grid: int = 0) -> str:
    """앞 · 뒤 · 왼쪽 · 오른쪽 · 위 · 아래 여섯 칸을 이름표 붙여 한 장(3×2 · 긴 변 ≤1500)으로. 클로드가 한눈에 대조한다.

    shape=True 면 색을 버리고 회색 한 가지로 — 모양(굴곡 · 돌기 · 띠)만 본다.
    grid>0 이면 칸마다 격자 — 칸 이름은 `region()` 이 3D 자리로 바꾼다(이름표는 아래 왼쪽으로 옮긴다)."""
    from PIL import Image, ImageDraw

    cell = min(int(cell), 500)
    if shape:
        colors = np.full((len(mesh.faces), 3), SHAPE_GRAY)
    elif colors is None:
        colors = face_colors(mesh)
    sheet = Image.new("RGB", (cell * 3, cell * 2), (245, 245, 243))
    draw = ImageDraw.Draw(sheet)
    font = _font(max(14, cell // 18))
    for i, (name, view) in enumerate(SIX_VIEWS):
        img = render(mesh, view, cell, colors)
        if grid:
            img = _gridded(img, grid).resize((cell, cell), Image.LANCZOS)
        x, y = (i % 3) * cell, (i // 3) * cell
        sheet.paste(img, (x, y))
        draw.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(200, 200, 196))
        draw.text((x + 8, y + (cell - font.size - 10 if grid else 6)), name, fill=(40, 40, 40), font=font)
    sheet.save(target)
    return str(target)


#: 전후 판 한 방향 크게(zoom) 칸 크기 — 줄무늬 · 입선 같은 잔결은 512 칸에서 잘 안 보인다.
ZOOM_SIDE = 900


def compare_sheet(before: Mesh, after: Mesh, target: Path, cell: int = 400, only: str | None = None) -> str:
    """마무리 전 · 후 회색 모양 판 한 장 — 방향마다 왼쪽 전 · 오른쪽 후를 붙여 놓는다(3줄 × 2쌍). only 를 주면 그 방향 한 쌍만 크게.
    두 칸은 같은 틀(전 · 후를 합친 크기)로 찍는다 — 펴기로 크기가 조금 줄어도 그림이 움직여 차이처럼 보이지 않게."""
    from PIL import Image, ImageDraw

    views = [(name, view) for name, view in SIX_VIEWS if only is None or name == only]
    if not views:
        raise ValueError(f"방향은 {[n for n, _ in SIX_VIEWS]} 가운데 하나")
    side = ZOOM_SIDE if only else min(int(cell), MAX_SIDE)
    pairs_per_row = 1 if only else 2
    rows = -(-len(views) // pairs_per_row)
    sheet = Image.new("RGB", (side * 2 * pairs_per_row, side * rows), (245, 245, 243))
    draw = ImageDraw.Draw(sheet)
    font = _font(max(14, side // 18))
    gray_b = np.full((len(before.faces), 3), SHAPE_GRAY)
    gray_a = np.full((len(after.faces), 3), SHAPE_GRAY)
    # 같은 틀: 두 모양에 합친 상자의 여덟 모서리를 보이지 않게 붙인다(면은 안 그린다 · 틀만 맞춘다)
    lo = np.minimum(before.positions.min(axis=0), after.positions.min(axis=0))
    hi = np.maximum(before.positions.max(axis=0), after.positions.max(axis=0))
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    framed_b = Mesh(np.vstack([before.positions, corners]), before.faces)
    framed_a = Mesh(np.vstack([after.positions, corners]), after.faces)
    for i, (name, view) in enumerate(views):
        for j, (mesh, colors, tag) in enumerate(((framed_b, gray_b, "전"), (framed_a, gray_a, "후"))):
            img = render(mesh, view, side, colors, limit=side)
            x = ((i % pairs_per_row) * 2 + j) * side
            y = (i // pairs_per_row) * side
            sheet.paste(img, (x, y))
            draw.rectangle([x, y, x + side - 1, y + side - 1], outline=(200, 200, 196))
            draw.text((x + 8, y + 6), f"{name} · {tag}", fill=(40, 40, 40) if tag == "전" else (20, 90, 160), font=font)
    sheet.save(target)
    return str(target)


def view_one(mesh: Mesh, name: str, target: Path, colors: np.ndarray | None = None, grid: int = 0) -> str:
    """한 방향만 크게(512 · 미리보기 상한). grid>0 이면 격자를 깐다."""
    views = dict(SIX_VIEWS)
    if name not in views:
        raise ValueError(f"방향은 {[n for n, _ in SIX_VIEWS]} 가운데 하나")
    img = render(mesh, views[name], MAX_SIDE, colors if colors is not None else face_colors(mesh))
    (_gridded(img, grid) if grid else img).save(target)
    return str(target)


def write_previews(mesh: Mesh, out_dir: Path, stem: str) -> list[str]:
    colors = face_colors(mesh)
    files = []
    for name, view in VIEWS.items():
        target = out_dir / f"{stem}_{name}.webp"
        render(mesh, view, MAX_SIDE, colors).save(target, format="WEBP", quality=82)
        files.append(str(target))
    return files
