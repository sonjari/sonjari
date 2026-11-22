"""따로 구운 부품 앉히기(홈 · 핀) — 일부러 깨 보는 시험 (2026-11-16 · 설계 `설계_조립부품나누기` §8-6).

- 상자 위에 원기둥: 홈 벽 지름 = 원기둥 + 틈(칸 0.4mm 에 안 묶임) · 홈 깊이 = depth_mm · 원기둥은 안 깎임 · 덩이 수 유지 · 핀 양쪽 구멍
- 반례: 얇은 판(남는 살 < 1.6mm) → 거절 · at 이 모형 밖 → 거절 · 두 부품에 걸침 → 거절 · 홈이 다리를 끊음 → 거절
- 앞에서 밀기(머리가 큰 인형용): 앞면에 옆 홈 · 핀이 수평 · auto 가 자리를 찾음
- 판: 앉힌 부품은 바탕과 다른 판
"""
from __future__ import annotations

import numpy as np
import pytest

from alture_jarvis.gen3d import attach as attach_mod
from alture_jarvis.gen3d.assembly import PIN_SIZES, Cut, cylinder_mesh, split_model
from alture_jarvis.gen3d.attach import Attach
from alture_jarvis.gen3d.glb import Mesh
from alture_jarvis.gen3d.printing import check_printable
from test_gen3d_print_1114 import _box, _merge

PITCH = 0.4
CLR = 0.2


def _closed(pos: np.ndarray, faces: np.ndarray) -> dict:
    c = check_printable(Mesh(pos, faces))
    assert c["watertight"] and c["boundary_edges"] == 0 and c["non_manifold_edges"] == 0 and c["flipped_edges"] == 0, c
    assert c["parts"] == 1, c
    return c


def _model(part: dict) -> np.ndarray:
    return (part["positions"] + part["shift"]) @ part["rotation"]


def _cyl(d: float = 16.0, h: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    return cylinder_mesh(d, h, chamfer=0.4, segments=96)


def _att(**kw) -> Attach:
    pos, faces = kw.pop("mesh", None) or _cyl()
    base = dict(name="통", pos=pos, faces=faces, approach="top", at=(0.0, 0.0), depth_mm=2.0)
    base.update(kw)
    return Attach(**base)


@pytest.fixture(scope="module")
def box_seat() -> dict:
    pos, faces = _box((-20, -20, 0), (20, 20, 20))
    return split_model(pos, faces, [], pitch=PITCH, clearance=CLR, attach=[_att()])


def test_box_and_cylinder_closed_one_piece_each(box_seat: dict) -> None:
    out = box_seat
    assert len(out["parts"]) == 1 and len(out["attached"]) == 1
    _closed(out["parts"][0]["positions"], out["parts"][0]["faces"])  # 홈을 파도 한 덩이 · 닫힘
    att = out["attached"][0]
    _closed(att["part"]["positions"], att["part"]["faces"])
    assert att["pin_mesh"] is not None
    _closed(*att["pin_mesh"])
    assert att["seat_part"] == 1 and att["auto"] is False
    assert att["depth_mm"] == pytest.approx(2.0, abs=1e-9)
    assert att["direction"] == [0, 0, -1]
    assert att["floor_min_mm"] >= 15.0  # 20mm 상자에 2mm 홈


def test_socket_wall_is_cylinder_plus_clearance(box_seat: dict) -> None:
    """홈 벽은 원기둥 겉을 틈만큼 밀어낸 면에 붙는다 — 칸(0.4) 이 아니라 틈(0.2)으로 맞는다."""
    out = box_seat
    att = out["attached"][0]
    shift = np.array(att["shift_mm"])
    seated_bottom = float(shift[2])  # 원기둥 바닥(z=0)이 앉은 높이
    # 윗면 20 에서 정확히 2mm — 칸끼리 닿음은 겉을 한 칸씩 부풀려 0.4mm 얕았다(11-16) · 원래 메시로 틈을 재 고침
    assert seated_bottom == pytest.approx(18.0, abs=0.05)
    base = _model(out["parts"][0])
    r = np.linalg.norm(base[:, :2] - shift[:2], axis=1)
    wall = base[(base[:, 2] > seated_bottom + 0.8) & (base[:, 2] < 19.6) & (r < 12)]
    assert len(wall) > 50
    rw = np.linalg.norm(wall[:, :2] - shift[:2], axis=1)
    assert np.median(rw) == pytest.approx(8.0 + CLR, abs=0.03), np.percentile(rw, [5, 50, 95])
    # 겹침 0: 붙지 못한 꼭짓점도 원기둥(8.0) 안으로 들어오면 안 된다(11-16 첫 판: 7% 가 7.8 에 남아 끼울 때 걸릴 뻔)
    assert rw.min() >= 8.0 + 0.1, np.sort(rw)[:5]
    assert float(np.mean(np.abs(rw - 8.2) < 0.06)) >= 0.8, np.percentile(rw, [5, 50, 80, 95])
    # 홈 바닥: 원기둥 바닥 - 틈
    floor = base[(r < 5) & (base[:, 2] < 19.9) & (base[:, 2] > 10)]
    floor = floor[np.abs(np.linalg.norm(floor[:, :2] - shift[:2], axis=1)) > 4.6]  # 핀 구멍 둘레 밖
    assert np.median(floor[:, 2]) == pytest.approx(seated_bottom - CLR, abs=0.05)


def test_cylinder_is_not_carved_and_pin_holes_line_up(box_seat: dict) -> None:
    att = box_seat["attached"][0]
    cyl = _model(att["part"])  # 원기둥 자기 자리
    mid = cyl[(cyl[:, 2] > 2) & (cyl[:, 2] < 8)]
    rr = np.linalg.norm(mid[:, :2], axis=1)
    outer = rr[rr > 6]
    assert np.median(outer) == pytest.approx(8.0, abs=0.03)  # 겉은 그대로(홈 쪽이 비켜 줌)
    pin = att["pin"]
    assert pin["d_mm"] in PIN_SIZES
    assert pin["axis"] == [0.0, 0.0, -1.0]
    depth_base, depth_part = pin["hole_depth_mm"]["바탕"], pin["hole_depth_mm"]["붙인 부품"]
    assert depth_part - 0.4 >= pin["d_mm"] - 1e-6 and depth_base - 0.4 >= pin["d_mm"] - 1e-6
    assert pin["length_mm"] == pytest.approx(depth_base + depth_part - 0.8, abs=0.02)
    # 붙인 부품 쪽 구멍: 바닥 가운데에서 위로(자기 자리) — 구멍 벽 지름
    hole = cyl[(cyl[:, 2] > 1.5) & (cyl[:, 2] < depth_part - 1.0)]
    hr = np.linalg.norm(hole[:, :2] - np.array(pin["at_mm"][:2]) + np.array(att["shift_mm"][:2]), axis=1)
    hr = hr[hr < 6]
    assert np.median(hr) == pytest.approx(pin["hole_d_mm"] / 2, abs=0.03)


def test_thin_plate_is_refused() -> None:
    pos, faces = _box((-20, -20, 0), (20, 20, 3))
    with pytest.raises(ValueError, match="얇거나 뚫린다"):
        split_model(pos, faces, [], pitch=PITCH, clearance=CLR, attach=[_att()])


def test_at_outside_the_model_is_refused() -> None:
    pos, faces = _box((-20, -20, 0), (20, 20, 20))
    with pytest.raises(ValueError, match="모형 밖"):
        split_model(pos, faces, [], pitch=PITCH, clearance=CLR, attach=[_att(at=(60.0, 0.0))])


def test_seat_across_two_parts_is_refused() -> None:
    """한가운데를 세로로 자른 상자 위에 앉히면 두 부품에 걸친다 — 조립 순서가 꼬이니 거절."""
    pos, faces = _box((-20, -20, 0), (20, 20, 20))
    with pytest.raises(ValueError, match="에도 박힌다"):
        split_model(pos, faces, [Cut(np.array([0, 0, 10.0]), np.array([1.0, 0, 0]), "가운데")], pitch=PITCH,
                    clearance=CLR, attach=[_att(pin=False)])


def _bridge() -> tuple[np.ndarray, np.ndarray]:
    """두 기둥을 윗부분의 얇은 다리(2mm)로 이은 바탕 — 홈이 다리를 끊으면 두 덩이가 된다."""
    return _merge(_box((-20, -10, 0), (-6, 10, 20)), _box((6, -10, 0), (20, 10, 20)), _box((-7, -4, 18), (7, 4, 20)))


def test_seat_that_splits_the_base_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    pos, faces = _bridge()
    # 얇음 검사를 꺼도(가장자리 비율 문턱 1.0) 덩이 검사가 따로 잡는지
    monkeypatch.setattr(attach_mod, "THIN_SHARE_MAX", 1.0)
    with pytest.raises(ValueError, match="갈라진다"):
        split_model(pos, faces, [], pitch=PITCH, clearance=CLR,
                    attach=[_att(mesh=_cyl(12.0, 6.0), pin=False)])


def test_front_approach_carves_a_side_groove_with_a_level_pin() -> None:
    """머리가 몸보다 큰 인형은 위에서 내리면 머리에 닿는다 — 앞(-y)에서 밀어 앞면에 홈."""
    pos, faces = _box((-20, -20, 0), (20, 20, 30))
    out = split_model(pos, faces, [], pitch=PITCH, clearance=CLR,
                      attach=[_att(approach="front", at=(0.0, 5.0), mesh=_cyl(16.0, 12.0))])
    att = out["attached"][0]
    _closed(out["parts"][0]["positions"], out["parts"][0]["faces"])
    assert att["direction"] == [0, 1, 0]
    shift = np.array(att["shift_mm"])
    assert shift[2] == pytest.approx(5.0, abs=PITCH)          # 바닥 높이 = at 의 둘째 값
    # 원기둥 옆(y 가장 큰 곳 = 가운데 + 8)이 앞면(-20)보다 2mm 안으로
    assert shift[1] + 8.0 == pytest.approx(-18.0, abs=0.05)
    assert att["pin"] is not None and att["pin"]["axis"] == [0.0, 1.0, 0.0]
    # 구멍은 지름 × 1.5 + 여유 + 입구(틈 · 둥근 겉) 1mm 안 — 11-16: 입구 허용을 깊이 상한에 더해 바탕 구멍이 16.2mm(필요 12.4)였다
    # 깊이 상한은 입구 「뒤부터」 센다 — 입구 허용(붙인 부품 max(1, d/2) · 바탕은 + 틈 + 두 칸)을 끝까지 더해 파지 않는다
    d = att["pin"]["d_mm"]
    core = d * 1.5 + 0.4
    assert att["pin"]["hole_depth_mm"]["붙인 부품"] < core + max(1.0, d / 2) - 0.3, att["pin"]
    assert att["pin"]["hole_depth_mm"]["바탕"] < core + max(1.0, d / 2) + CLR + 2 * PITCH - 0.3, att["pin"]
    assert att["socket_mm2"] > 50


def test_auto_finds_a_seat_on_the_front_half() -> None:
    pos, faces = _box((-20, -20, 0), (20, 20, 20))
    out = split_model(pos, faces, [], pitch=PITCH, clearance=CLR, attach=[_att(at=None, pin=False)])
    att = out["attached"][0]
    assert att["auto"] is True
    assert att["at_mm"][1] <= 0.5  # 앞(-y) 절반
    assert any("auto" in n for n in out["notes"])


def test_attach_plates_are_separate(tmp_path) -> None:
    from alture_jarvis.gen3d.assembly import prepare_assembly

    pos, faces = _box((-20, -20, 0), (20, 20, 20))
    # prepare_assembly 는 glTF(y 위) 메시를 받는다 — 프린트 자리 (x, y, z) ← glTF (x, z, -y)
    gl = np.stack([pos[:, 0], pos[:, 2], -pos[:, 1]], axis=1)
    out = prepare_assembly(Mesh(gl, faces), tmp_path, "box", 40.0, [], pitch=PITCH, slice_it=False, attach=[_att()])
    groups = [p["group"] for p in out["plates"]]
    assert groups[0] == "바탕" and "붙임1" in groups
    plate_of = {name: p["group"] for p in out["plates"] for name in p["objects"]}
    assert plate_of["attach1"] == "붙임1" and plate_of["attach1_pin"] == "붙임1" and plate_of["part1"] == "바탕"
    assert out["attached"][0]["socket_mm2"] > 100
    assert any("seated" in f for f in out["files"]["pictures"])
    assert out["files"]["seat_maps"]
