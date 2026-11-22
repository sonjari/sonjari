"""3D 프린트 — 메시를 재서 슬라이서 설정을 고른다 (2026-11-14 · 설계 `설계_3D프린트갈래` §4).

숫자만 잰다. 고른 까닭은 잰 숫자와 함께 영수증(`print.decisions`)에 남긴다. 모델 말은 넣지 않는다.
처음 값은 뱀부 X2D 기본 설정(서포트 기준각 30° · tree(auto) · 브림 5mm)이고, 문턱(브림 · 층 높이)은 **짐작에서 시작해
실제로 뽑아 보며 고친다** — 각 규칙 옆에 근거를 적었다.

11-14 실측: 다시 뜬 배를 서포트 없이 썰자 뱀부가 「공중에 뜬 부분이 있다 · 서포트를 켜라」 경고를 냈다 → 아랫면 재기가 필요한 근거.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: 뱀부 X2D 0.20mm Standard 의 서포트 기준각(공정 설정 `support_threshold_angle`).
SUPPORT_ANGLE_DEG = 30.0
#: 바닥으로 칠 높이(mm) — 이 아래의 아랫면은 판 위에 놓이므로 서포트가 필요 없다.
FLOOR_BAND_MM = 0.3
#: 서포트를 켤 아랫면 넓이(mm²) — 이보다 작으면 다리 놓기(브리지)로 버틴다고 본다. [짐작 · 출력으로 고칠 것]
SUPPORT_MIN_AREA_MM2 = 4.0
#: 브림: 바닥 닿는 넓이가 이보다 작거나 높이 ÷ 바닥 짧은 폭이 이보다 크면. [짐작]
BRIM_MAX_BASE_MM2 = 400.0
BRIM_TALL_RATIO = 3.0


@dataclass
class PrintPlan:
    support: bool
    support_type: str
    brim: bool
    layer_height: float
    process: str
    measured: dict[str, float]
    decisions: list[dict[str, str]] = field(default_factory=list)

    def overrides(self) -> dict[str, str]:
        """공정 설정에 써 넣을 값. ★ 11-14: 위키는 명령줄 `--키=값` 이 된다지만 이 판(02.08)에서는 그것만 넣으면 썰기가
        즉시 실패했다(A/B 로 갈라 확인) → 합친 공정 설정 파일 안에 직접 써 넣는다(`slicer.write_presets`)."""
        out = {"enable_support": "1" if self.support else "0", "brim_type": "outer_only" if self.brim else "no_brim",
               # ★ 2026-11-20 하트사탕곰 첫 실물: 뱀부 기본(aligned)이 층마다 솔기를 얼굴에 세로로 쌓아 이마 → 코 옆에 선이 났다.
               #   우리 판은 모델 앞이 판 앞(-Y)을 본다(하트사탕곰 STL 실측: 하트 y -16 · 꼬리 쪽 +27.5) — 솔기를 판 뒤(+Y)로.
               "seam_position": "back"}
        if self.support:
            out["support_type"] = self.support_type
        return out

    def receipt(self) -> dict[str, Any]:
        return {"process": self.process, "layer_height": self.layer_height, "support": self.support,
                "support_type": self.support_type if self.support else None, "brim": self.brim,
                "measured": self.measured, "decisions": self.decisions}


def _layer_choice(size_mm: float, detail: str) -> tuple[float, str]:
    """층 높이 — 뱀부 X2D 공정 이름 그대로. detail: auto | fine | fast."""
    if detail == "fast":
        return 0.20, "0.20mm Standard"
    if detail == "fine" or size_mm < 40:
        return (0.08, "0.08mm High Quality") if size_mm < 40 else (0.12, "0.12mm High Quality")
    return 0.20, "0.20mm Standard"


#: 놓는 방향 후보 — (이름, 회전 행렬). 지금 방향(위가 위)을 포함한 축 방향 여섯.
_ORIENTS = (
    ("지금 그대로", np.eye(3)),
    ("거꾸로", np.diag([1.0, -1.0, -1.0])),
    ("앞으로 눕힘", np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])),
    ("뒤로 눕힘", np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])),
    ("왼쪽으로 눕힘", np.array([[0, 0, 1.0], [0, 1.0, 0], [-1.0, 0, 0]])),
    ("오른쪽으로 눕힘", np.array([[0, 0, -1.0], [0, 1.0, 0], [1.0, 0, 0]])),
)


ORIENTATIONS = tuple(name for name, _ in _ORIENTS)


def orient(pos: np.ndarray, name: str) -> np.ndarray:
    """방향 제안(`orientation_options`)의 이름대로 돌리고 다시 판 위(바닥 z=0 · 가운데 x=y=0)에 놓는다."""
    rot = dict(_ORIENTS).get(name)
    if rot is None:
        raise ValueError(f"orientation 은 {list(ORIENTATIONS)} 가운데 하나")
    out = np.asarray(pos, dtype=np.float64) @ rot.T
    lo, hi = out.min(axis=0), out.max(axis=0)
    return out - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])


def _overhang_area(pos: np.ndarray, faces: np.ndarray) -> tuple[float, float]:
    tri = pos[faces]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    double_area = np.linalg.norm(normal, axis=1)
    unit = normal / np.maximum(double_area, 1e-12)[:, None]
    centre_z = tri[:, :, 2].mean(axis=1)
    zmin = float(pos[:, 2].min())
    over = (-unit[:, 2] > float(np.cos(np.radians(SUPPORT_ANGLE_DEG)))) & (centre_z > zmin + FLOOR_BAND_MM)
    return float((double_area[over] * 0.5).sum()), float(np.ptp(pos[:, 2]))


def orientation_options(pos: np.ndarray, faces: np.ndarray) -> list[dict[str, Any]]:
    """축 방향 여섯으로 돌렸을 때 서포트가 필요한 아랫면 넓이 · 높이. 돌리지는 않는다 — 고르는 건 사람(모양 · 보이는 면이 바뀐다)."""
    out = []
    for name, rot in _ORIENTS:
        area, height = _overhang_area(pos @ rot.T, faces)
        out.append({"orientation": name, "overhang_area_mm2": round(area, 1), "height_mm": round(height, 1)})
    return out


def plan_print(pos: np.ndarray, faces: np.ndarray, size_mm: float, detail: str = "auto") -> PrintPlan:
    """밀리미터 · z 위 · 바닥 z=0 인 닫힌 메시(다시 뜬 것)를 재서 설정을 고른다."""
    tri = pos[faces]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    double_area = np.linalg.norm(normal, axis=1)
    area = double_area * 0.5
    unit = normal / np.maximum(double_area, 1e-12)[:, None]
    centre_z = tri[:, :, 2].mean(axis=1)
    zmin = float(pos[:, 2].min())
    height = float(pos[:, 2].max() - zmin)

    # 아랫면 중 기준각보다 눕은 것(수평에 가까운 천장): 법선의 아래 성분이 cos(기준각) 보다 크면.
    # 뱀부 기준각은 「수평면에서 잰 각」 — 법선이 아래로 (90-기준각)도 안이면 서포트가 필요하다.
    down = -unit[:, 2]
    limit = float(np.cos(np.radians(SUPPORT_ANGLE_DEG)))
    overhang = (down > limit) & (centre_z > zmin + FLOOR_BAND_MM)
    overhang_area = float(area[overhang].sum())
    total_area = float(area.sum()) or 1.0

    # 바닥: z 가 바닥 띠 안이고 아래를 보는 면.
    base = (down > 0.9) & (centre_z <= zmin + FLOOR_BAND_MM)
    base_area = float(area[base].sum())
    if base.any():
        bp = tri[base].reshape(-1, 3)
        base_short = float(min(np.ptp(bp[:, 0]), np.ptp(bp[:, 1])))
    else:
        base_short = 0.0
    tall_ratio = height / base_short if base_short > 0 else float("inf")

    support = overhang_area >= SUPPORT_MIN_AREA_MM2
    brim = base_area < BRIM_MAX_BASE_MM2 or tall_ratio > BRIM_TALL_RATIO
    layer, process = _layer_choice(size_mm, detail)

    measured = {
        "overhang_area_mm2": round(overhang_area, 1), "overhang_share": round(overhang_area / total_area, 4),
        "base_area_mm2": round(base_area, 1), "base_short_side_mm": round(base_short, 1),
        "height_mm": round(height, 2), "tall_ratio": round(tall_ratio, 2) if np.isfinite(tall_ratio) else None,
    }
    decisions = [
        {"what": "support", "value": "tree(auto)" if support else "off",
         "why": f"{SUPPORT_ANGLE_DEG:g}°보다 눕은 아랫면 {overhang_area:.0f}mm² (전체 겉넓이의 {overhang_area / total_area:.1%})"
                + (" — 받침 필요" if support else f" — {SUPPORT_MIN_AREA_MM2:g}mm² 미만이라 없이")},
        {"what": "brim", "value": "on" if brim else "off",
         "why": f"바닥 닿는 넓이 {base_area:.0f}mm² · 높이 ÷ 바닥 짧은 폭 {measured['tall_ratio']}"
                + (" — 좁거나 키가 커서 넘어짐 · 들뜸 막기" if brim else " — 바닥이 넉넉")},
        {"what": "layer", "value": f"{layer:g}mm ({process})",
         "why": "작은 물체(40mm 미만)라 곱게" if size_mm < 40 else ("곱게를 골라서" if detail == "fine" else "기본(소품) · 속도는 층 설정이 같이 가져온다")},
    ]
    options = orientation_options(pos, faces)
    best = min(options, key=lambda o: (o["overhang_area_mm2"], o["height_mm"]))
    measured["orientations"] = options
    if best["orientation"] != "지금 그대로" and best["overhang_area_mm2"] < overhang_area * 0.6:
        decisions.append({"what": "orientation", "value": "지금 그대로(제안만)",
                          "why": f"「{best['orientation']}」으로 놓으면 받침이 필요한 아랫면이 {overhang_area:.0f} → {best['overhang_area_mm2']:.0f}mm² — "
                                 "보이는 면 · 결이 바뀌니 사람이 정한다(뱀부 「놓는 면 고르기」로)"})
    return PrintPlan(support=support, support_type="tree(auto)", brim=brim, layer_height=layer, process=process,
                     measured=measured, decisions=decisions)
