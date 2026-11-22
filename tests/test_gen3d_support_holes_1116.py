"""핀 구멍 안 지지대 막기 — 일부러 깨 보는 시험 (2026-11-16).

11-16 대표 출력(내부 시험 캐릭터 머리 · 사진은 저장소 밖): 자른 면을 판에 대니 핀 구멍이 아래로 열려 평평한 천장(53.6mm²)이
허공에 떴고, 뱀부가 구멍 안을 바닥부터 천장까지 지지대 60층으로 채웠다. 고침 둘:
1. 모양 — 구멍 끝을 45° 고깔로(벽 1.6mm 가 남을 때만 · 핀이 들어가는 원기둥 깊이는 지킴 · 안 되면 평평 + 메모)
2. 출력 파일 — 구멍마다 뱀부 「지지대 금지」 부피를 3MF 에 싣는다(명령줄 썰기로 지키는 것 확인)
시험 자료는 상자 도형뿐이다.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import numpy as np
import pytest

from alture_jarvis.gen3d import assembly
from alture_jarvis.gen3d.assembly import GAP_MM, MIN_ENGAGE, WALL_MM, Cut, roof_h, split_model
from alture_jarvis.gen3d.print_plan import _overhang_area
from alture_jarvis.gen3d.printing import write_3mf_multi
from alture_jarvis.gen3d.snap import Cone
from test_gen3d_print_1114 import _box


def _split_box(height: float) -> dict:
    pos, faces = _box((0, 0, 0), (20, 20, height))
    return split_model(pos, faces, [Cut(np.array([10, 10, height / 2]), np.array([0, 0, 1.0]), "허리")],
                       pitch=0.2, clearance=0.2, pin_d=8.0)


@pytest.fixture(scope="module")
def tall() -> dict:
    """반쪽 높이 22mm — 원기둥 12.2 + 고깔 4.2 + 벽 1.6 이 들어간다."""
    return _split_box(44.0)


@pytest.fixture(scope="module")
def short() -> dict:
    """반쪽 높이 12mm — 평평한 구멍(10.4)은 되지만 고깔(최소 8.4 + 4.2 + 1.6)은 안 들어간다."""
    return _split_box(24.0)


def _hole_xy(part: dict) -> np.ndarray:
    """상자 가운데에 핀 하나 — 판에 놓은 부품의 가로 · 세로 가운데."""
    pos = part["positions"]
    return (pos.min(axis=0) + pos.max(axis=0))[:2] / 2


def _ceiling_mm2(part: dict, radius: float = 6.0) -> float:
    """구멍 둘레(가운데에서 radius 안)의 「바닥 띠 위 · 30° 보다 눕은 아랫면」 넓이 = 뱀부가 구멍 안에 지지대를 세울 곳
    (print_plan 과 같은 기준). 상자 바깥 모서리의 칸 자국은 구멍과 상관없어 뺀다."""
    pos, faces = part["positions"], part["faces"]
    tri = pos[faces]
    near = np.hypot(*(tri.mean(axis=1)[:, :2] - _hole_xy(part)).T) < radius
    return _overhang_area(pos, faces[near])[0] if near.any() else 0.0


def _flip(mesh: tuple[np.ndarray, np.ndarray], top: float) -> tuple[np.ndarray, np.ndarray]:
    """x 축으로 180° 뒤집어 판 위에(구멍이 위로 열린 부품 → 아래로 열린 부품)."""
    pos, faces = mesh
    return pos * np.array([1.0, -1.0, -1.0]) + np.array([0, 0, top]), faces


# ── 1. 모양 ─────────────────────────────────────────────────────────────
def test_cone_target_snaps_onto_the_45_degree_surface() -> None:
    cone = Cone(np.zeros(3), np.array([0, 0, 1.0]), 4.0, 4.0, 1.0)
    q, d = cone.closest(np.array([[2.5, 0, 2.5], [0.0, 3.0, 0.5], [9.0, 0, 0]]))
    assert d[0] == pytest.approx(1 / np.sqrt(2), abs=1e-6)  # (s 2.5, t 2.5) 에서 선 s + t = 4 까지
    assert q[0, 0] + q[0, 2] == pytest.approx(4.0)       # 겉 위: s + t = r(=h)
    assert q[1, 1] + q[1, 2] == pytest.approx(4.0)
    assert np.isinf(d[2])                                 # 붙임 반경 밖


def test_holes_open_to_the_plate_get_a_cone_roof_and_no_flat_ceiling(tall: dict) -> None:
    pins = tall["pins"]
    assert pins and all(p["hole_end"] == ["고깔", "고깔"] for p in pins)
    for part in tall["parts"]:
        assert "자른 면" in part["lay"]                    # 상자 반쪽은 자른 면을 판에 → 구멍이 아래로 열린다
        assert _ceiling_mm2(part) < 2.0, part["lay"]       # 고침 전: 평평한 천장 ≈ 55mm²(11-16 곰 머리 53.6)
    assert not any("고깔로 못 팠다" in n for n in tall["notes"])


def test_cone_keeps_the_pin_depth_and_length(tall: dict) -> None:
    for p in tall["pins"]:
        dp, dm = p["hole_depth_mm"]
        assert min(dp, dm) - GAP_MM >= p["d_mm"] * MIN_ENGAGE - 1e-6
        assert p["length_mm"] == pytest.approx(dp + dm - 2 * GAP_MM, abs=0.01)
        # 고깔이 있어도 원기둥(핀 자리)은 지름 × 1.5 + 틈까지 그대로 판다(이 상자는 살이 넉넉하다)
        assert min(dp, dm) >= p["d_mm"] * assembly.MAX_ENGAGE + GAP_MM - 0.25


def test_cone_tip_leaves_the_wall(tall: dict) -> None:
    """고깔 꼭짓점 너머로도 벽 1.6mm — 부품 높이 22 안에 원기둥 + 고깔 + 벽이 들어가야 한다."""
    for p in tall["pins"]:
        hole_r = p["hole_d_mm"] / 2
        for depth in p["hole_depth_mm"]:
            assert depth + roof_h(hole_r) + WALL_MM <= 22.0 + 1e-6


def test_no_room_for_a_cone_falls_back_to_a_flat_end_with_a_note(short: dict) -> None:
    pins = short["pins"]
    assert pins and all(p["hole_end"] == ["평평", "평평"] for p in pins)
    assert any("고깔로 못 팠다" in n for n in short["notes"])
    for p in pins:  # 물러나도 핀은 지금처럼 들어간다
        assert min(p["hole_depth_mm"]) - GAP_MM >= p["d_mm"] * MIN_ENGAGE - 1e-6


def test_roof_shortens_the_cylinder_only_down_to_the_minimum_engagement() -> None:
    """반쪽 높이 16: 깊이 12.2 로는 고깔 + 벽이 안 들어가지만 원기둥을 줄이면(≥ 8.4) 들어간다."""
    out = _split_box(32.0)
    p = out["pins"][0]
    assert p["hole_end"] == ["고깔", "고깔"]
    for depth in p["hole_depth_mm"]:  # 위 상한은 칸(0.2mm) 하나 너그럽게 — 살 재기가 칸 격자 위라서
        assert 8.0 + GAP_MM - 1e-6 <= depth <= 16.0 - roof_h(p["hole_d_mm"] / 2) - WALL_MM + 0.2 + 1e-6
        assert depth < 12.0  # 줄이지 않았으면 12.17(지름 × 1.5 + 틈)


# ── 2. 지지대 금지 부피 ───────────────────────────────────────────────────
def test_every_hole_gets_a_blocker_that_wraps_it(tall: dict, short: dict) -> None:
    for out in (tall, short):
        for part in out["parts"]:
            bl = part["blockers"]
            assert len(bl) == len(out["pins"])
            for bp, _ in bl:
                hole_r = out["pins"][0]["hole_d_mm"] / 2
                assert np.ptp(bp[:, 0]) == pytest.approx(2 * (hole_r + assembly.BLOCKER_MARGIN_MM), abs=0.05)
                roof = roof_h(hole_r) if out is tall else 0.0
                depth = max(out["pins"][0]["hole_depth_mm"])
                assert np.ptp(bp[:, 2]) >= 0.6 + depth + roof + 0.3 - 0.25  # 입구 앞부터 구멍 끝(고깔 꼭짓점) 너머까지
                top = float(part["positions"][:, 2].max())
                assert bp[:, 2].min() < 0.0 or bp[:, 2].max() > top  # 한쪽 끝이 자른 면 밖으로 나간다(입구)
                # 금지 부피 축 = 구멍 축 — 부품 발자국 가운데(상자 가운데 핀)
                foot = part["positions"][part["positions"][:, 2] < 0.05]
                centre = (foot.min(axis=0) + foot.max(axis=0)) / 2
                assert np.allclose((bp.min(axis=0) + bp.max(axis=0))[:2] / 2, centre[:2], atol=0.6)


def test_3mf_carries_blockers_as_bambu_support_blocker_parts(tmp_path: Path, tall: dict) -> None:
    part = tall["parts"][0]
    path = tmp_path / "plate.3mf"
    write_3mf_multi(path, [("part1", part["positions"], part["faces"])], blockers={"part1": part["blockers"]})
    with zipfile.ZipFile(path) as z:
        cfg = z.read("Metadata/model_settings.config").decode("utf-8")
        model = z.read("3D/3dmodel.model").decode("utf-8")
    assert cfg.count('subtype="support_blocker"') == len(part["blockers"]) and 'subtype="normal_part"' in cfg
    assert model.count("<component ") == 1 + len(part["blockers"])


def test_3mf_without_blockers_stays_the_plain_form(tmp_path: Path, tall: dict) -> None:
    part = tall["parts"][0]
    path = tmp_path / "plain.3mf"
    write_3mf_multi(path, [("part1", part["positions"], part["faces"])])
    with zipfile.ZipFile(path) as z:
        assert "Metadata/model_settings.config" not in z.namelist()
        assert "<component " not in z.read("3D/3dmodel.model").decode("utf-8")


# ── 3. 뱀부로 실제 썰어 본다(이 PC 에 뱀부가 있을 때만) ──────────────────
def _support_in_hole(gcode: Path, part: dict, hole_r: float, top: float) -> int:
    """구멍 안(첫 층으로 맞춘 자리 · 반지름 안 · 천장 아래) 지지대 압출이 있는 층 수."""
    feat, z, x, y = "", 0.0, 0.0, 0.0
    num = re.compile(r"([XYZE])(-?[\d.]+)")
    sup, first = [], []
    for line in gcode.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("; FEATURE:"):
            feat = line[10:].strip()
            continue
        if not line.startswith(("G1 ", "G2 ", "G3 ")):
            continue
        v = dict((k, float(n)) for k, n in num.findall(line.split(";")[0]))
        nx, ny = v.get("X", x), v.get("Y", y)
        z = v.get("Z", z)
        if v.get("E", 0) > 0 and (abs(nx - x) > 1e-3 or abs(ny - y) > 1e-3):  # 제자리 밀어 넣기(되감기 풀기)는 지지대가 아니다
            if "Support" in feat:
                sup.append((z, (x + nx) / 2, (y + ny) / 2))
            elif feat in ("Outer wall", "Inner wall"):
                first.append((z, nx, ny))
        x, y = nx, ny
    z0 = min(p[0] for p in first)
    first = [p for p in first if abs(p[0] - z0) < 1e-3]
    fx, fy = np.array([p[1] for p in first]), np.array([p[2] for p in first])
    foot = part["positions"][part["positions"][:, 2] < 0.05]
    shift = np.array([(fx.max() + fx.min()) / 2, (fy.max() + fy.min()) / 2]) - (foot.min(axis=0) + foot.max(axis=0))[:2] / 2
    centre = (foot.min(axis=0) + foot.max(axis=0))[:2] / 2 + shift
    layers = {round(zz, 2) for zz, sx, sy in sup if zz <= top + 0.05 and np.hypot(sx - centre[0], sy - centre[1]) <= hole_r + 0.3}
    return len(layers)


def _slice(tmp_path: Path, name: str, part: dict, blockers: list | None) -> Path:
    from alture_jarvis.gen3d.print_plan import plan_print
    from alture_jarvis.gen3d.slicer import slice_3mf

    path = tmp_path / f"{name}.3mf"
    write_3mf_multi(path, [("p", part["positions"], part["faces"])], blockers={"p": blockers} if blockers else None)
    plan = plan_print(part["positions"], part["faces"], 40.0)  # 받침은 아래에서 켠다(구멍 말고 다른 아랫면이 없을 수 있다)
    out = slice_3mf(path, tmp_path / name, process="0.20mm Standard",
                    overrides={**plan.overrides(), "enable_support": "1", "support_type": "tree(auto)"})
    assert out["ok"], out
    return Path(out["gcode"])


bambu = pytest.mark.skipif(__import__("alture_jarvis.gen3d.slicer", fromlist=["find_bambu"]).find_bambu() is None,
                           reason="뱀부 스튜디오 없음")


@bambu
def test_bambu_puts_no_support_inside_a_cone_roofed_hole(tmp_path: Path, tall: dict) -> None:
    part = tall["parts"][0]
    p = tall["pins"][0]
    top = max(p["hole_depth_mm"]) + roof_h(p["hole_d_mm"] / 2)
    assert _support_in_hole(_slice(tmp_path, "cone", part, None), part, p["hole_d_mm"] / 2, top) == 0


@bambu
def test_bambu_honours_the_blocker_in_a_flat_hole(tmp_path: Path, short: dict) -> None:
    """고깔을 못 판 평평한 구멍: 금지 부피 없이는 지지대가 차고(대조), 우리 3MF 의 금지 부피를 넣으면 0층."""
    part = dict(short["parts"][0])
    p = short["pins"][0]
    # 낮은 상자는 평평한 천장 탓에 자른 면을 위로 놓는다(그러면 원래 지지대가 안 선다) — 일부러 뒤집어 구멍을 아래로
    height = float(part["positions"][:, 2].max())
    if part["blockers"][0][0][:, 2].max() > height:
        part["positions"] = _flip((part["positions"], part["faces"]), height)[0]
        part["blockers"] = [_flip(b, height) for b in part["blockers"]]
    assert part["blockers"][0][0][:, 2].min() < 0.0
    top = max(p["hole_depth_mm"])
    without = _support_in_hole(_slice(tmp_path, "flat", part, None), part, p["hole_d_mm"] / 2, top)
    with_bl = _support_in_hole(_slice(tmp_path, "flat_bl", part, part["blockers"]), part, p["hole_d_mm"] / 2, top)
    assert without >= 10, without   # 대조: 고침 없는 평평한 구멍엔 지지대가 선다(이 시험이 무엇을 잡는지)
    assert with_bl == 0, with_bl
