# -*- coding: utf-8 -*-
"""anim_fit_check 계산(2026-11-06) — 가짜 바이페드 · 가짜 몸 메시로 양방향(뚫림 잡기 · 안 뚫림 안 잡기)."""
from __future__ import annotations

import numpy as np
import pytest

from alture_jarvis.animator import fitcheck


def _m(pos, x=(1, 0, 0), y=(0, 1, 0), z=(0, 0, 1)):
    return list(x) + list(y) + list(z) + list(pos)


def _pose(arm_x: float):
    """서 있는 몸(Z 위). 아래팔 · 손을 arm_x 자리에 앞으로 내민다(배 높이). arm_x 가 작으면 배 안이다."""
    up = (0, 0, 1)
    b = {
        "Pelvis": _m((0, 0, 50), x=up, y=(0, 1, 0), z=(-1, 0, 0)),
        "Spine": _m((0, 0, 55), x=up, y=(0, 1, 0), z=(-1, 0, 0)),
        "Spine1": _m((0, 0, 65), x=up, y=(0, 1, 0), z=(-1, 0, 0)),
        "Spine2": _m((0, 0, 75), x=up, y=(0, 1, 0), z=(-1, 0, 0)),
        "Neck": _m((0, 0, 88), x=up, y=(0, 1, 0), z=(-1, 0, 0)),
        "Head": _m((0, 0, 92), x=up, y=(0, 1, 0), z=(-1, 0, 0)),
    }
    for s, sx in (("L", 1), ("R", -1)):
        b[f"{s} UpperArm"] = _m((sx * 14, 0, 84), x=(0, 0, -1))
        b[f"{s} Forearm"] = _m((sx * 14, 0, 70), x=(0, -1, 0))
        b[f"{s} Hand"] = _m((sx * arm_x, -14, 62), x=(0, -1, 0))
        b[f"{s} Thigh"] = _m((sx * 7, 0, 50), x=(0, 0, -1))
        b[f"{s} Calf"] = _m((sx * 7, 0, 28), x=(0, 0, -1))
        b[f"{s} Foot"] = _m((sx * 7, 0, 6), x=(0, -1, 0))
    # 아래팔이 손 쪽으로 가게: 아래팔 자리를 손과 같은 x 로
    for s, sx in (("L", 1), ("R", -1)):
        b[f"{s} Forearm"] = _m((sx * arm_x, 0, 66), x=(0, -1, 0))
    return b


def _body_verts():
    rng = np.random.default_rng(0)
    pts = []
    for cz, rx, ry, rz in ((60, 11, 9, 10), (76, 12, 8, 9), (100, 8, 8, 9)):   # 배 · 가슴 · 머리
        u = rng.normal(size=(400, 3))
        u /= np.linalg.norm(u, axis=1, keepdims=True)
        pts.append(u * [rx, ry, rz] + [0, 0, cz])
    for s in (1, -1):                                                             # 팔다리 점(몸 부피를 더럽히지 않게)
        pts.append(np.c_[np.full(30, s * 14), np.zeros(30), np.linspace(70, 84, 30)] + [2, 0, 0])
        pts.append(np.c_[np.full(30, s * 7), np.zeros(30), np.linspace(10, 48, 30)] + [2.5, 0, 0])
    return np.vstack(pts).round(3).tolist()


def _dump(frames: list[float], ref: int = 0):
    names = list(_pose(30).keys())
    rows = [[i] + [_pose(x)[n] for n in names] for i, x in enumerate(frames)]
    return {"ok": True, "bones": names, "start": 0, "end": len(frames) - 1, "ref": ref, "frames": rows, "verts": _body_verts()}


def test_arms_far_from_the_body_are_not_flagged() -> None:
    out = fitcheck.check(_dump([30, 30, 28, 32]))
    assert out["frames_with_any_hit"] == 0 and out["table"] == []
    assert "calibration_failed" not in out
    assert set(out["body_measured"]) == {"머리", "가슴", "배"}


def test_hands_inside_the_belly_are_counted_by_frame_and_range() -> None:
    out = fitcheck.check(_dump([30, 30, 2, 1, 2, 30]))
    assert out["frames_with_any_hit"] == 3
    belly = [r for r in out["table"] if r["where"].endswith("→ 배")]
    assert belly and belly[0]["frames"] == 3 and belly[0]["ranges"] == ["2~4"]


def test_a_reference_frame_that_already_overlaps_says_do_not_trust_it() -> None:
    out = fitcheck.check(_dump([2, 30, 30], ref=0))
    assert "calibration_failed" in out


def test_no_skinned_mesh_is_an_error_not_an_empty_table() -> None:
    d = _dump([30, 30])
    d["verts"] = []
    with pytest.raises(ValueError, match="메시"):
        fitcheck.check(d)


def test_read_script_only_reads_and_strips_quotes_from_the_prefix(tmp_path) -> None:
    s = fitcheck.read_script(tmp_path / "d.json", 0, 10, 0, prefix='Bip"001')
    assert '"Bip001"' in s and "createFile" in s
    for verb in ("delete $", "deleteKeys", "addNewKey", "setTransform", "saveMaxFile"):
        assert verb not in s


def test_the_tool_gives_a_read_only_line_then_reads_the_newest_dump(tmp_path) -> None:
    import json
    from test_animator_v1_1103 import _tools

    t = _tools(tmp_path)
    first = t.fit_check({})
    assert first["status"] == "시험 중" and first["run_line"].startswith("execute")
    script = open(first["run_line"].split('@"')[1].rstrip('")'), encoding="utf-8-sig").read()
    assert "animationRange.start" in script                      # 구간을 안 주면 장면 구간
    with open(first["read_file"], "w", encoding="utf-8") as fh:
        json.dump(_dump([30, 2, 30]), fh)
    out = t.fit_check({"check": True})
    assert out["frames_with_any_hit"] == 1 and "믿게 하지 말고" in out["note"]


def test_fix_plans_only_hit_frames_within_the_limit_and_writes_one_undo_with_a_hold(tmp_path) -> None:
    d = _dump([30, 30, 2, 1, 2, 30, 30, 30, 30, 30, 30, 30, 30, 30])
    d["keys"] = {"L": [3, 13], "R": [3, 13]}
    plan = fitcheck.plan_fix(d, max_deg=45)
    assert plan["frames_hit"]["왼"] == 3
    keyed = {f for f, _d, _deg in plan["keys"]["L"]}
    assert keyed == {3}            # 키 자리 중 뚫린 곳 근처만 · 먼 키(13 · 부드럽게 잇는 범위 약 8프레임 밖)는 안 건드림
    assert all(0 < deg <= 45 for _f, _d, deg in plan["keys"]["L"])
    s = fitcheck.write_fix_script(plan)
    assert "holdMaxFile()" in s and s.count('undo "Sonjari fit fix" on') == 1 and "sjAlign" in s


def test_fix_with_nothing_to_fix_sends_no_script(tmp_path) -> None:
    import json
    from test_animator_v1_1103 import _tools

    t = _tools(tmp_path)
    first = t.fit_check({})
    with open(first["read_file"], "w", encoding="utf-8") as fh:
        json.dump(_dump([30, 30, 30]), fh)
    out = t.fit_fix({})
    assert out["keys"] == 0 and "run_line" not in out
