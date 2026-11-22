"""나눌 자리 후보 — 일부러 깨 보는 시험 (2026-11-14 · 설계 `설계_조립부품나누기` §4-5).

- 눈사람(공 둘): 목 하나만 — 공 옆을 지나는 엉뚱한 「밑동」 · 「갈래」(11-14 처음 판에 넷씩 잡힘)가 없다
- 받침판 위 기둥 둘(배 갑판 꼴): 「갈래」가 판 윗면에서 잡힌다
- 공 머리 위 작은 공 둘(곰 귀 꼴): 「밑동」 둘이 귀 자리에서 잡힌다
- 그냥 상자: 후보 없음(지어내지 않는다)
- 그림 셋이 만들어지고 후보 선이 그어진다
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from alture_jarvis.gen3d.remesh import remesh
from alture_jarvis.gen3d.split_plan import candidates, coarse, draw_views
from test_gen3d_print_1114 import _box, _merge
from test_gen3d_snap_1114 import _sphere


def _cands(pos: np.ndarray, faces: np.ndarray, pitch: float = 0.25) -> list[dict]:
    rm = remesh(pos, faces, pitch=pitch, smooth_rounds=0, thicken_to_mm=0, keep_grid=True)
    return candidates(*coarse(*rm.cells[:2], rm.pitch))


def test_snowman_gives_only_its_neck() -> None:
    hv, hf = _sphere(7)
    cs = _cands(*_merge(_sphere(10), (hv + np.array([3.0, 3.0, 17.0]), hf)))
    assert [c["kind"] for c in cs] == ["목"]
    assert cs[0]["axis"] == "z" and 19 <= cs[0]["point"][2] <= 24


def test_a_plate_with_posts_gives_a_branch_cut_at_the_deck() -> None:
    base = _box((0, 0, 0), (60, 30, 12))
    posts = [_box((10 + 18 * i, 12, 12), (16 + 18 * i, 18, 40)) for i in range(3)]
    cs = _cands(*_merge(base, *posts), pitch=0.4)
    deck = [c for c in cs if c["kind"] == "갈래" and c["axis"] == "z"]
    assert deck and abs(deck[0]["point"][2] - 12) <= 2.0
    # 기둥마다 따로 자르는 「밑동」도 나온다(셋) — 둘 다 진짜 후보라 고르는 건 클로드
    feet = [c for c in cs if c["kind"] == "밑동" and c["axis"] == "z"]
    assert sorted(round(c["point"][0]) for c in feet) == [13, 31, 49]


def test_ears_on_a_head_give_two_base_cuts() -> None:
    head = _sphere(12)  # 가운데 (14,14,14)
    ev, ef = _sphere(3.5)  # 가운데 (5.5,5.5,5.5)
    ears = [(ev + np.array([dx, 8.5, 21.0]), ef) for dx in (0.5, 16.5)]  # (6,14,26.5) · (22,14,26.5) — 머리 위로 4mm 남짓 나옴
    cs = _cands(*_merge(head, *ears))
    base = [c for c in cs if c["kind"] == "밑동" and c["axis"] == "z"]
    xs = sorted(round(c["point"][0]) for c in base)
    assert len(base) == 2 and xs[0] < 12 < xs[1]


def test_a_plain_box_gives_nothing() -> None:
    assert _cands(*_box((0, 0, 0), (30, 20, 10)), pitch=0.5) == []


def test_views_are_drawn_with_marks(tmp_path: Path) -> None:
    hv, hf = _sphere(7)
    rm = remesh(*_merge(_sphere(10), (hv + np.array([3.0, 3.0, 17.0]), hf)), pitch=0.25, smooth_rounds=0,
                thicken_to_mm=0, keep_grid=True)
    cs, co, cp = coarse(*rm.cells[:2], rm.pitch)
    marks = candidates(cs, co, cp)
    files = draw_views(cs.astype(np.int16), co, cp, tmp_path, "snow", marks)
    assert len(files) == 3 and all(Path(f).stat().st_size > 1000 for f in files)
    from PIL import Image

    front = np.asarray(Image.open(files[0]).convert("RGB")).astype(int)
    red = (front[:, :, 0] > 190) & (front[:, :, 1] < 80) & (front[:, :, 2] < 80)
    assert red.sum() > 50  # 목 선이 앞 그림에 그어졌다
