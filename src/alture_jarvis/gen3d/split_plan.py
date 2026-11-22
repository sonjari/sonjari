"""나눌 자리 후보 찾기 + 그림 (2026-11-14 · 설계 `설계_조립부품나누기` §4-5).

손자리가 숫자를 내고 클로드가 고른다. 모델을 1mm 칸으로 거칠게 만든 뒤 세 축으로 썰어 가며 단면 덩이를 따라간다:
- **목**: 따라가던 덩이의 단면이 앞뒤보다 확 좁아지는 곳(곰의 목 · 눈사람 허리)
- **밑동**: 따로 오던 덩이(귀 · 팔 · 돛대)가 더 큰 덩이에 합쳐지기 바로 앞
후보마다 자르는 점 · 방향 · 단면 넓이 · 작은 쪽 부피(대략) · 좁은 정도를 주고, 앞 · 옆 · 위 그림에 번호를 그어 준다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .remesh import cell_components

PLAN_PITCH_MM = 1.0
NECK_RATIO = 0.8        # 단면이 양쪽 최대의 80% 아래면 목 · 밑동은 합쳐지는 덩이의 80% 아래(11-14 눈사람 목 0.71 이 0.6 에 빠짐)
BRANCH_RATIO = 0.35     # 갈래: 나뉜 가지 중 가장 굵은 것이 몸통 단면의 35% 아래(배 갑판 0.027 · 눈사람 두 공 옆 0.62 는 아님)
MIN_SIDE_SHARE = 0.01   # 작은 쪽이 전체 부피의 1% 넘어야(긁힌 자국 · 털 같은 건 후보 아님)
MAX_CANDIDATES = 12
AXES = ("x", "y", "z")


def coarse(solid: np.ndarray, origin: np.ndarray, pitch: float, target: float = PLAN_PITCH_MM
           ) -> tuple[np.ndarray, np.ndarray, float]:
    f = max(1, int(round(target / pitch)))
    nx, ny, nz = (s // f * f for s in solid.shape)
    s = solid[:nx, :ny, :nz].reshape(nx // f, f, ny // f, f, nz // f, f)
    return s.any(axis=(1, 3, 5)), np.asarray(origin, dtype=np.float64), pitch * f


def _slice_components(sl: np.ndarray) -> list[np.ndarray]:
    """2D 단면의 덩이마다 칸 좌표(n,2)."""
    cells, lab = cell_components(sl[:, :, None])
    out = []
    for k in np.unique(lab):
        out.append(cells[lab == k][:, :2])
    return out


def candidates(solid: np.ndarray, origin: np.ndarray, pitch: float) -> list[dict[str, Any]]:
    """거친 칸 격자(1mm)에서 목 · 밑동 후보."""
    total = float(solid.sum())
    found: list[dict[str, Any]] = []
    for ax in range(3):
        moved = np.moveaxis(solid, ax, 0)
        other = [a for a in range(3) if a != ax]
        layers: list[list[dict[str, Any]]] = []
        for k in range(moved.shape[0]):
            comps = []
            for c in _slice_components(moved[k]) if moved[k].any() else []:
                key = set(map(tuple, c.tolist()))
                comps.append({"cells": c, "key": key, "area": len(c)})
            layers.append(comps)
        # 이웃 층과 겹치는 덩이 잇기
        links_up: list[list[list[int]]] = []
        for k in range(len(layers) - 1):
            row = []
            for a in layers[k]:
                row.append([j for j, b in enumerate(layers[k + 1]) if a["key"] & b["key"]])
            links_up.append(row)
        links_dn: list[list[list[int]]] = [[[] for _ in layers[0]]]
        for k in range(1, len(layers)):
            links_dn.append([[i for i, a in enumerate(layers[k - 1]) if b["key"] & a["key"]] for b in layers[k]])
        # 사슬: 위아래로 하나씩만 이어진 덩이들
        seen: set[tuple[int, int]] = set()
        for k in range(len(layers)):
            for i in range(len(layers[k])):
                if (k, i) in seen:
                    continue
                chain = [(k, i)]
                seen.add((k, i))
                kk, ii = k, i
                while kk + 1 < len(layers) and len(links_up[kk][ii]) == 1:
                    j = links_up[kk][ii][0]
                    if len(links_dn[kk + 1][j]) != 1:
                        break
                    kk, ii = kk + 1, j
                    chain.append((kk, ii))
                    seen.add((kk, ii))
                areas = np.array([layers[a][b]["area"] for a, b in chain], dtype=float)
                vol_chain = float(areas.sum())

                def emit(pos: int, kind: str, sign: float, small: float, ratio: float, edge: int = 0, pieces: int = 1) -> None:
                    """edge: 0 = 그 층 한가운데(목) · +1 = 그 층 윗면 · -1 = 그 층 아랫면(밑동 · 갈래는 바뀌는 경계에서 —
                    11-14 배: 갑판 칸 한가운데를 자르니 위 부품에 1mm 갑판 판이 딸려 가 핀을 못 놓았다)."""
                    a, b = chain[pos]
                    c = layers[a][b]["cells"].mean(axis=0)
                    pt = np.zeros(3)
                    pt[ax] = origin[ax] + (a + 0.5 + 0.5 * edge) * pitch
                    pt[other[0]] = origin[other[0]] + (c[0] + 0.5) * pitch
                    pt[other[1]] = origin[other[1]] + (c[1] + 0.5) * pitch
                    n = np.zeros(3)
                    n[ax] = sign
                    found.append({"kind": kind, "axis": AXES[ax], "point": pt, "normal": n,
                                  "section_mm2": round(float(areas[pos]) * pitch ** 2, 1),
                                  "small_side_mm3": round(small * pitch ** 3, 0),
                                  "ratio": round(ratio, 3), "_edge": edge, "pieces": pieces})

                # 목: 사슬 안 극솟값
                if len(chain) >= 5:
                    for p in range(2, len(chain) - 2):
                        left, right = areas[:p].max(), areas[p + 1:].max()
                        if areas[p] <= areas[p - 1] and areas[p] <= areas[p + 1] and areas[p] < NECK_RATIO * min(left, right):
                            small = min(areas[:p].sum(), areas[p + 1:].sum())
                            emit(p, "목", 1.0, small, float(areas[p]) / min(left, right))
                # 밑동: 사슬 끝에서 더 큰 덩이로 합쳐짐(위로 합쳐지면 +, 아래로 합쳐지면 -)
                # 밑동 조건: 합쳐지는 덩이의 절반 아래이고(같은 크기 귀 둘이 서로를 「더 큰 덩이」로 막지 않게 — 11-14 귀 시험),
                # 가지가 자기 폭의 절반 이상 튀어나와 있어야 한다(11-14 눈사람: 머리 공 옆구리가 1~2칸 따로 보였다 합쳐지는 자리가 잡혔다).
                ka, ia = chain[-1]
                if ka + 1 < len(layers) and len(links_up[ka][ia]) == 1:
                    j = links_up[ka][ia][0]
                    merged = float(layers[ka + 1][j]["area"])
                    others = [layers[ka][o]["area"] for o in links_dn[ka + 1][j] if o != ia]
                    if others and areas[-1] < 0.5 * merged and len(chain) >= 0.5 * np.sqrt(areas[-1]):
                        emit(len(chain) - 1, "밑동", -1.0, vol_chain, float(areas[-1]) / merged, edge=1)
                kb, ib = chain[0]
                if kb > 0 and len(links_dn[kb][ib]) == 1:
                    j = links_dn[kb][ib][0]
                    merged = float(layers[kb - 1][j]["area"])
                    others = [layers[kb][o]["area"] for o in links_up[kb - 1][j] if o != ib]
                    if others and areas[0] < 0.5 * merged and len(chain) >= 0.5 * np.sqrt(areas[0]):
                        emit(0, "밑동", 1.0, vol_chain, float(areas[0]) / merged, edge=-1)
                # 갈래: 사슬 끝에서 여러 가지로 나뉨(배의 갑판 → 돛 · 밧줄들). 그 바로 앞을 자르면 몸통과 위 전부가 갈린다.
                ups = links_up[ka][ia] if ka + 1 < len(layers) else []
                if len(chain) >= 3 and len(ups) >= 2:
                    top = max(layers[ka + 1][u]["area"] for u in ups)
                    if top < BRANCH_RATIO * areas[-1]:
                        emit(len(chain) - 1, "갈래", 1.0, float(areas.sum()), top / float(areas[-1]), edge=1, pieces=len(ups))
                dns = links_dn[kb][ib] if kb > 0 else []
                if len(chain) >= 3 and len(dns) >= 2:
                    top = max(layers[kb - 1][u]["area"] for u in dns)
                    if top < BRANCH_RATIO * areas[0]:
                        emit(0, "갈래", -1.0, float(areas.sum()), top / float(areas[0]), edge=-1, pieces=len(dns))
    # 걸러내기: 작은 쪽이 너무 작은 것 · 거의 같은 자리
    keep: list[dict[str, Any]] = []
    for c in found:
        # 작은 쪽 = 둘 중 작은 쪽(갈래는 사슬이 몸통이라 큰 쪽을 셌다 — 11-14 운영 배: 94.8%)
        c["small_side_mm3"] = round(min(float(c["small_side_mm3"]), total * pitch ** 3 - float(c["small_side_mm3"])), 0)
    for c in sorted(found, key=lambda c: (c["ratio"], -c["small_side_mm3"])):
        if c["small_side_mm3"] < MIN_SIDE_SHARE * total * pitch ** 3:
            continue
        # 같은 종류 · 같은 축에서 거의 같은 자리만 하나로(종류가 다르면 단면이 다르다 — 갑판 갈래와 가운데 기둥 밑동)
        if any(k["axis"] == c["axis"] and k["kind"] == c["kind"] and np.linalg.norm(k["point"] - c["point"]) < 4 * pitch
               for k in keep):
            continue
        keep.append(c)
        if len(keep) >= MAX_CANDIDATES:
            break
    for i, c in enumerate(keep, start=1):
        c["id"] = i
        c["point"] = [round(float(v), 2) for v in c["point"]]
        c["normal"] = [float(v) for v in c["normal"]]
    return keep


# ── 그림 ─────────────────────────────────────────────────────────────
_PALETTE = [(214, 92, 72), (66, 133, 196), (98, 168, 92), (212, 163, 54), (150, 98, 190), (60, 170, 170),
            (200, 110, 160), (120, 120, 120), (180, 140, 90)]

#: 보는 쪽 이름 → (보는 축, 그림 가로 축, 그림 세로 축 · 위가 +)
VIEWS = {"front": (1, 0, 2), "side": (0, 1, 2), "top": (2, 0, 1)}


def _font():
    """한글이 되는 글꼴(윈도우 맑은 고딕 · 맥 애플 고딕) — 없으면 기본(숫자만 쓰니 괜찮다)."""
    from PIL import ImageFont

    for path in ("C:/Windows/Fonts/malgun.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                 "/System/Library/Fonts/Supplemental/AppleGothic.ttf"):
        try:
            return ImageFont.truetype(path, 18)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_views(labels: np.ndarray, origin: np.ndarray, pitch: float, out_dir: Path, stem: str,
               marks: list[dict[str, Any]] | None = None, side: int = 512) -> list[str]:
    """칸 격자(부품 번호 · 0 은 빈 칸)를 앞 · 옆 · 위에서 본 그림. marks = 자르기 후보(번호 · 점 · 방향)."""
    from PIL import Image, ImageDraw

    files = []
    font = _font()
    for name, (look, hx, vy) in VIEWS.items():
        lab = np.moveaxis(labels, (hx, vy, look), (0, 1, 2))
        hit = lab > 0
        any_hit = hit.any(axis=2)
        first = np.where(any_hit, hit.argmax(axis=2), 0)
        ii, jj = np.nonzero(any_hit)
        part = lab[ii, jj, first[ii, jj]]
        depth = first[ii, jj] / max(lab.shape[2], 1)
        w, h = lab.shape[0], lab.shape[1]
        scale = (side * 0.9) / max(w, h)
        img = Image.new("RGB", (side, side), (245, 245, 243))
        px = np.zeros((h, w, 3), dtype=np.uint8) + np.array([245, 245, 243], dtype=np.uint8)
        shade = (1.0 - 0.55 * depth)[:, None]
        cols = np.array([_PALETTE[(int(p) - 1) % len(_PALETTE)] if labels.max() > 1 else (190, 186, 178) for p in part])
        px[h - 1 - jj, ii] = np.clip(cols * shade, 0, 255).astype(np.uint8)
        small = Image.fromarray(px).resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.NEAREST)
        ox, oy = (side - small.width) // 2, (side - small.height) // 2
        img.paste(small, (ox, oy))
        draw = ImageDraw.Draw(img)

        def to_px(pt: np.ndarray) -> tuple[float, float]:
            u = (pt[hx] - origin[hx]) / pitch
            v = (pt[vy] - origin[vy]) / pitch
            return ox + u * scale, oy + (h - v) * scale

        for m in marks or []:
            p = np.asarray(m["point"], dtype=float)
            n = np.asarray(m["normal"], dtype=float)
            if abs(n[look]) > 0.9:
                continue  # 보는 방향과 같은 평면은 선이 아니라 면 — 이 그림엔 안 그림
            # 평면과 그림 평면이 만나는 선: 단면 넓이로 길이를 대략
            r = max(np.sqrt(float(m.get("section_mm2") or 50) / np.pi) * 1.4, 4.0)
            d = np.zeros(3)
            d[hx], d[vy] = -n[vy], n[hx]
            if np.linalg.norm(d) < 1e-9:
                continue
            d /= np.linalg.norm(d)
            a, b = to_px(p - d * r), to_px(p + d * r)
            draw.line([a, b], fill=(220, 30, 30), width=3)
            draw.text((b[0] + 4, b[1] - 8), str(m.get("id", "")), fill=(200, 20, 20), font=font)
        draw.text((6, 6), {"front": "앞", "side": "옆", "top": "위"}[name], fill=(60, 60, 60), font=font)
        target = out_dir / f"{stem}_{name}.png"
        img.save(target)
        files.append(str(target))
    return files


def refine(cands: list[dict[str, Any]], solid: np.ndarray, origin: np.ndarray, pitch: float, span_mm: float = 2.5
           ) -> list[dict[str, Any]]:
    """밑동 · 갈래 후보의 자르는 높이를 고운 격자로 다시 잡는다 — 단면이 확 바뀌는 바로 그 경계로.

    11-14 배: 거친 칸(1mm) 경계로 자르면 실제 갑판 면과 최대 1mm 어긋나 위 부품에 얇은 갑판 판이 딸려 가거나(핀 자리 없음),
    점이 빈 공중에 찍혔다. 사슬 쪽(몸통 · 가지)에서 바깥으로 한 장씩 나가며 그 점의 덩이 넓이가 확 줄거나(갈래)
    확 늘면(밑동) 그 앞 경계에서 자른다."""
    for c in cands:
        if c["kind"] not in ("밑동", "갈래"):
            continue
        ax = AXES.index(c["axis"])
        other = [a for a in range(3) if a != ax]
        pt = np.asarray(c["point"], dtype=float)
        edge = int(np.sign(c.get("_edge", 0)))
        if edge == 0:
            continue
        moved = np.moveaxis(solid, ax, 0)
        start = int(np.floor((pt[ax] - origin[ax]) / pitch - edge * 0.5 / pitch))  # 경계에서 사슬 쪽 반 mm
        steps = int(span_mm / pitch)
        uv = np.array([(pt[o] - origin[o]) / pitch - 0.5 for o in other])

        def area_at(k: int) -> tuple[int, np.ndarray | None]:
            if not 0 <= k < moved.shape[0] or not moved[k].any():
                return 0, None
            best, best_cells = None, None
            for cells in _slice_components(moved[k]):
                d = float(np.min(np.linalg.norm(cells - uv, axis=1)))
                if best is None or d < best:
                    best, best_cells = d, cells
            return (len(best_cells), best_cells) if best is not None and best < 3.0 / pitch else (0, None)

        k = start - edge * steps
        prev, prev_cells = area_at(k)
        last = None
        while abs(k - start) <= 2 * steps and prev:
            nxt, nxt_cells = area_at(k + edge)
            if c["kind"] == "갈래" and nxt < 0.6 * prev:
                last = (k, prev_cells)
                break
            if c["kind"] == "밑동" and nxt > 1.6 * prev:
                last = (k, prev_cells)
                break
            k, prev, prev_cells = k + edge, nxt, nxt_cells
        if last is None:
            continue
        k, cells = last
        new = pt.copy()
        new[ax] = origin[ax] + (k + 0.5 + 0.5 * edge) * pitch
        cen = cells.mean(axis=0)
        new[other[0]] = origin[other[0]] + (cen[0] + 0.5) * pitch
        new[other[1]] = origin[other[1]] + (cen[1] + 0.5) * pitch
        c["point"] = [round(float(v), 2) for v in new]
        c["refined"] = True
    for c in cands:
        c.pop("_edge", None)
    return cands
