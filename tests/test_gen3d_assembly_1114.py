"""조립 부품 나누기 · 끼움 시험 조각 — 일부러 깨 보는 시험 (2026-11-14 · 설계 `설계_조립부품나누기` §5).

- 눈사람을 자르면: 두 부품 다 닫힘 · 한 덩이 · 구멍 지름이 지정 ± 0.02mm(칸 0.2mm 에 안 묶임) · 두 구멍이 같은 축 · 핀 닫힘
- 반례: 고리(끊어도 안 나뉨) → 거절 · 모델을 안 지나는 평면 → 거절 · 평면이 다른 기둥을 지나가도 고른 기둥만 자름 ·
  좁은 목 → 핀 대신 「접착」으로 물러남 · 판보다 큰 부품 → 거절
- 끼움 시험 조각: 닫힘 · 구멍 다섯의 지름이 틈대로 · 핀 길이
"""
from __future__ import annotations

import numpy as np
import pytest

from alture_jarvis.gen3d.assembly import (
    Cut,
    FIT_CLEARANCES,
    cylinder_mesh,
    fit_coupon,
    load_fit,
    pack_plates,
    rotation_to,
    save_fit,
    split_model,
)
from alture_jarvis.gen3d.glb import Mesh
from alture_jarvis.gen3d.printing import check_printable
from test_gen3d_print_1114 import _box, _merge
from test_gen3d_snap_1114 import _sphere


def _closed(pos: np.ndarray, faces: np.ndarray) -> dict:
    c = check_printable(Mesh(pos, faces))
    assert c["watertight"] and c["boundary_edges"] == 0 and c["non_manifold_edges"] == 0 and c["flipped_edges"] == 0, c
    assert c["parts"] == 1, c
    return c


def _snowman() -> tuple[np.ndarray, np.ndarray]:
    body = _sphere(10)  # 가운데 (12,12,12)
    hv, hf = _sphere(7)  # 가운데 (9,9,9) → (12,12,26)
    return _merge(body, (hv + np.array([3.0, 3.0, 17.0]), hf))


def _back_to_model(part: dict) -> np.ndarray:
    return (part["positions"] + part["shift"]) @ part["rotation"]


@pytest.fixture(scope="module")
def snowman_split() -> dict:
    pos, faces = _snowman()
    return split_model(pos, faces, [Cut(np.array([12, 12, 15.0]), np.array([0, 0, 1.0]), "허리")], pitch=0.2,
                       clearance=0.2)


def test_snowman_splits_into_two_closed_parts_with_a_pin(snowman_split: dict) -> None:
    out = snowman_split
    assert len(out["parts"]) == 2
    for p in out["parts"]:
        _closed(p["positions"], p["faces"])
        assert float(p["positions"][:, 2].min()) == pytest.approx(0.0, abs=1e-6)  # 판 위
    assert len(out["pins"]) >= 1
    for pin in out["pins"]:
        _closed(pin["positions"], pin["faces"])
        assert pin["hole_d_mm"] == pytest.approx(pin["d_mm"] + 0.4)
        assert pin["length_mm"] == pytest.approx(sum(pin["hole_depth_mm"]) - 0.8, abs=0.02)
        assert min(pin["hole_depth_mm"]) - 0.4 >= pin["d_mm"]  # 한쪽에 지름만큼은 들어간다
    # 잘린 면을 판에 붙이면 아래 몸통의 받침이 세운 채보다 확 준다(둥근 바닥 → 평평한 단면)
    lower = max(out["parts"], key=lambda p: p["volume_mm3"])
    assert lower["overhang_mm2"] < 0.5 * lower["overhang_if_upright_mm2"]


def test_hole_walls_are_exactly_the_hole_radius_and_coaxial(snowman_split: dict) -> None:
    """칸은 0.2mm 인데 구멍 벽은 붙이기로 정확한 원기둥 — 틈 0.2mm 를 지키는 근거."""
    out = snowman_split
    pin = out["cuts"][0]["pins"][0]
    centre = np.array(pin["at_mm"])
    r = pin["hole_d_mm"] / 2
    axis = np.array([0, 0, 1.0])
    for part, sign, depth in zip(sorted(out["parts"], key=lambda p: p["id"]), (1, -1), pin["hole_depth_mm"]):
        v = _back_to_model(part)
        rel = v - centre
        t = rel @ (axis * sign)
        radial = np.linalg.norm(rel - np.outer(rel @ axis, axis), axis=1)
        wall = (t > 0.5) & (t < depth - 0.5) & (np.abs(radial - r) < 0.15)
        assert wall.sum() > 50
        assert np.abs(radial[wall] - r).max() < 0.02  # 두 부품 다 같은 축 · 같은 반지름


def test_a_ring_cannot_be_split_by_one_cut() -> None:
    """고리: 한 군데를 끊어도 반대쪽으로 이어져 있다 — 나뉜 척하지 않고 거절한다."""
    outer = _box((0, 0, 0), (30, 30, 6))
    # 가운데를 판 고리: 네 변을 따로 붙인다
    ring = _merge(_box((0, 0, 0), (30, 6, 6)), _box((0, 24, 0), (30, 30, 6)),
                  _box((0, 6, 0), (6, 24, 6)), _box((24, 6, 0), (30, 24, 6)))
    del outer
    with pytest.raises(ValueError, match="고리"):
        split_model(*ring, [Cut(np.array([3.0, 15, 3]), np.array([0, 1.0, 0]))], pitch=0.4)


def test_a_cut_that_misses_the_model_is_refused() -> None:
    with pytest.raises(ValueError, match="지나지 않는다"):
        split_model(*_box((0, 0, 0), (10, 10, 10)), [Cut(np.array([5.0, 5, 40]), np.array([0, 0, 1.0]))], pitch=0.4)


def test_only_the_chosen_pillar_is_cut_even_if_the_plane_crosses_another() -> None:
    """같은 높이 평면이 두 기둥을 다 지나도 점을 찍은 기둥만 자른다 — 곰의 목을 자를 때 든 팔까지 잘리면 안 된다."""
    base = _box((0, 0, 0), (40, 16, 5))
    left = _box((4, 4, 5), (12, 12, 30))
    right = _box((28, 4, 5), (36, 12, 30))
    out = split_model(*_merge(base, left, right), [Cut(np.array([8.0, 8, 20]), np.array([0, 0, 1.0]))],
                      pitch=0.4, simplify=False)
    assert len(out["parts"]) == 2
    vols = sorted(p["volume_mm3"] for p in out["parts"])
    # 작은 쪽 = 왼 기둥 윗부분(8×8×10 = 640mm³ 에서 핀 구멍만큼 뺀 것) · 오른 기둥은 큰 쪽에 통째로
    assert 450 < vols[0] < 660
    assert vols[1] > 40 * 16 * 5


def test_a_deck_cut_that_frees_several_pieces_makes_a_part_each() -> None:
    """11-14 배: 갑판을 자르면 위쪽이 갑판으로만 이어진 여러 조각(돛 · 선실 · 밧줄 끝)이 된다 — 한 부품으로 묶으면
    부품 하나에 덩이가 여럿(떨어진 조각)이라 판 위에서 흩어진다. 조각마다 따로 부품이고, 몇 조각인지 메모에 적는다."""
    from alture_jarvis.gen3d.remesh import remesh
    from alture_jarvis.gen3d.split_plan import candidates, coarse, refine

    base = _box((0, 0, 0), (60, 30, 12))
    posts = [_box((8 + 18 * i, 9, 12), (20 + 18 * i, 21, 30)) for i in range(3)]
    model = _merge(base, *posts)
    # 실제 흐름 그대로: 후보 찾기 → 고운 격자로 다시 잡기 → 그 자리로 자르기
    # (손으로 z=12 를 주면 칸으로 부푼 받침 윗면 한 겹이 위로 딸려 가 기둥 셋을 잇는다 — 다시 잡기가 그 경계를 찾는다)
    rm = remesh(*model, pitch=0.4, smooth_rounds=0, thicken_to_mm=0, keep_grid=True)
    solid, origin, _ = rm.cells
    cands = refine(candidates(*coarse(solid, origin, rm.pitch)), solid, origin, rm.pitch)
    deck = next(c for c in cands if c["kind"] == "갈래" and c["axis"] == "z")
    assert deck.get("refined") and deck["pieces"] == 3
    out = split_model(*model, [Cut.parse({**deck, "name": "갑판"}, 0)], pitch=0.4, simplify=False, thicken_to_mm=0)
    assert len(out["parts"]) == 4
    for p in out["parts"]:
        _closed(p["positions"], p["faces"])  # 부품마다 한 덩이
    assert any("3조각" in n for n in out["notes"])
    cut = out["cuts"][0]
    assert len(cut["plus_parts"]) == 3 and len(cut["minus_parts"]) == 1
    # 기둥(12mm 각)마다 핀이 들어갈 수 있다 — 핀은 기둥 조각과 받침판을 잇는다
    assert out["pins"], out["notes"]


def test_a_thin_tall_part_is_laid_flat_not_stood_up() -> None:
    """11-14 배: 밧줄 삼각형(2.5mm 두께 · 61mm 높이)을 세워 놓았다 — 받침 넓이만 보면 세운 것도 0 이라서.
    쓰러질 위험(높이 ÷ 바닥 짧은 폭 > 3)이 있으면 눕힌다."""
    base = _box((0, 0, 0), (40, 20, 6))
    wall = _box((5, 9, 6), (35, 11.5, 46))  # 2.5mm 두께 · 40mm 높이 벽
    out = split_model(*_merge(base, wall), [Cut(np.array([20.0, 10.25, 6.4]), np.array([0, 0, 1.0]), "벽 밑")],
                      pitch=0.25, simplify=False, thicken_to_mm=0)
    wall_part = min(out["parts"], key=lambda p: p["volume_mm3"])
    assert wall_part["size_mm"][2] < 5.0, wall_part  # 눕혀서 높이가 두께 정도


def test_a_narrow_neck_falls_back_to_glue() -> None:
    base = _box((0, 0, 0), (20, 20, 5))
    neck = _box((8.5, 8.5, 5), (11.5, 11.5, 15))  # 3mm 목 — 핀 3mm + 벽 1.6mm 가 안 들어간다
    out = split_model(*_merge(base, neck), [Cut(np.array([10.0, 10, 10]), np.array([0, 0, 1.0]))],
                      pitch=0.2, simplify=False, thicken_to_mm=0)
    assert out["pins"] == []
    assert any("접착제" in n for n in out["notes"])
    for p in out["parts"]:
        _closed(p["positions"], p["faces"])


def test_fit_coupon_holes_follow_the_clearances() -> None:
    cp = fit_coupon(pin_d=5.0, pitch=0.1)
    pos, faces = cp["block"]
    _closed(pos, faces)
    _closed(*cp["pin"])
    assert cp["clearances"] == list(FIT_CLEARANCES)
    top = float(pos[:, 2].max())
    radii = []
    xs = sorted(set(np.round(pos[(pos[:, 2] < top - 2) & (pos[:, 2] > top - 6)][:, 0], 0)))
    del xs
    # 구멍 벽 꼭짓점: 위 2~6mm 깊이, 막대 가운데 줄 근처
    yc = (pos[:, 1].min() + pos[:, 1].max()) / 2
    band = pos[(pos[:, 2] < top - 2) & (pos[:, 2] > top - 6)]
    for i, c in enumerate(FIT_CLEARANCES):
        want = 2.5 + c
        rel = band[:, :2] - np.array([band[:, 0], np.full(len(band), yc)]).T * [0, 1]
        del rel
        # 구멍 가운데 x 는 쌓은 간격대로
        spacing = 5.0 + 2 * max(FIT_CLEARANCES) + 5.0
        cx = pos[:, 0].min() + 2.0 + spacing * (i + 0.5)
        d = np.hypot(band[:, 0] - cx, band[:, 1] - yc)
        wall = np.abs(d - want) < 0.08
        assert wall.sum() > 50, c
        radii.append(float(np.median(d[wall])))
        assert np.abs(d[wall] - want).max() < 0.02, c
    assert radii == sorted(radii)  # 왼쪽부터 커진다
    assert float(np.ptp(cp["pin"][0][:, 0])) == pytest.approx(5.0, abs=1e-6)


def test_fit_is_saved_and_read_back(tmp_path) -> None:
    assert load_fit(tmp_path) is None
    save_fit(tmp_path, 0.15, "Bambu Lab X2D", "Bambu PLA Basic")
    assert load_fit(tmp_path)["clearance_mm"] == 0.15
    with pytest.raises(ValueError):
        save_fit(tmp_path, 2.0, "x", "y")


def test_plates_pack_and_overflow() -> None:
    v, f = cylinder_mesh(10, 10)
    items = [(f"p{i}", v.copy(), f) for i in range(40)]  # 지름 10 + 간격 6 → 한 줄 15개 → 판 하나에 다 든다
    plates = pack_plates(items, plate=250)
    placed = [p for plate in plates for p in plate]
    assert len(placed) == 40
    for plate in plates:
        boxes = [(p[1][:, 0].min(), p[1][:, 0].max(), p[1][:, 1].min(), p[1][:, 1].max()) for p in plate]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                assert a[1] <= b[0] or b[1] <= a[0] or a[3] <= b[2] or b[3] <= a[2]  # 겹치지 않는다
            assert -125 <= boxes[i][0] and boxes[i][1] <= 125 and -125 <= boxes[i][2] and boxes[i][3] <= 125
    big = _box((0, 0, 0), (300, 10, 10))
    with pytest.raises(ValueError, match="판"):
        pack_plates([("big", big[0], big[1])])
    many = [(f"q{i}", *_box((0, 0, 0), (100, 100, 10))) for i in range(5)]
    assert len(pack_plates(many, plate=250)) == 2  # 판 하나에 넷(2×2) · 다섯째는 둘째 판


def test_rotation_to_maps_vectors() -> None:
    for a in ([0, 0, 1], [1, 0, 0], [0.3, -0.5, 0.8], [0, 0, -1]):
        r = rotation_to(np.array(a, float), np.array([0, 0, -1.0]))
        assert np.allclose(r @ (np.array(a) / np.linalg.norm(a)), [0, 0, -1])
        assert np.allclose(r @ r.T, np.eye(3))
