# -*- coding: utf-8 -*-
"""애니메이터 팩 「시험 중」 셋 고침(2026-11-10) — 양방향 시험.

1. 뚫림 점검: 스킨 가중치로 몸 부피를 잰다 — 장식(치마 메시 · 포니테일 뼈)은 빼고, 뱃살 출렁 같은 몸 뼈는 남긴다.
"""
from __future__ import annotations

import json

import numpy as np

from alture_jarvis.animator import fitcheck
from test_animator_fitcheck_1106 import _body_verts, _dump


def _labels():
    """_body_verts() 순서 그대로 점마다 스킨 뼈: 배 400 · 가슴 400 · 머리 400 · 팔다리 30씩."""
    lab = ["Spine"] * 400 + ["Spine2"] * 400 + ["Head"] * 400
    for s in ("L", "R"):
        lab += [f"{s} UpperArm"] * 30 + [f"{s} Thigh"] * 30
    return lab


def _decorated(frames, *, weights=True, jiggle=False):
    """몸 + 장식 둘: 골반에 통째로 붙은 퍼진 치마(따로 된 메시) · 머리 아래 포니테일 뼈에 붙은 머리카락 다발(가슴 높이 양옆)."""
    d = _dump(frames)
    body = np.array(d["verts"])
    rng = np.random.default_rng(1)
    t = rng.uniform(0, 2 * np.pi, 240)
    skirt = np.c_[27 * np.cos(t), 20 * np.sin(t), rng.uniform(48, 64, 240)]          # 배 둘레보다 훨씬 넓게
    tails = np.vstack([np.c_[np.full(80, s * 24) + rng.normal(0, 1.5, 80), rng.normal(0, 3, 80),
                             np.linspace(66, 96, 80)] for s in (1, -1)])                # 가슴 양옆으로 늘어진 다발
    d["verts"] = np.vstack([body, skirt, tails]).round(3).tolist()
    if weights:
        lab = _labels()
        if jiggle:                                                                    # 배 점 절반은 뱃살 출렁 뼈(몸)
            lab[:200] = ["x:Bip001 Xtra_Belly"] * 200
        d["vbones"] = lab + ["Pelvis"] * len(skirt) + ["x:Bip001 Ponytail1"] * len(tails)
        d["vmesh"] = [0] * len(body) + [1] * len(skirt) + [0] * len(tails)
        d["meshes"] = ["Body", "Skirt"]
        d["xparent"] = {"Bip001 Ponytail1": "Head", "Bip001 Xtra_Belly": "Spine"}
    return d


def test_decorations_measured_as_body_flag_hands_that_are_outside_the_body() -> None:
    """눈금 확인: 가중치가 없으면(예전 방식) 치마 · 머리카락까지 몸으로 쳐서 몸 밖(x=18)의 손을 잡는다 — 이 시험 장면이 장식 문제를 재현한다."""
    out = fitcheck.check(_decorated([30, 18, 18, 30], weights=False))
    assert out["frames_with_any_hit"] >= 2


def test_skin_weights_drop_decorations_so_hands_outside_the_body_are_not_flagged() -> None:
    out = fitcheck.check(_decorated([30, 18, 18, 30]))
    assert out["frames_with_any_hit"] == 0, out["table"]
    how = out["body_from"]
    assert how["skin_weights"] is True
    gone = {x.get("bone") or x.get("mesh") for x in how["decoration"]}
    assert gone == {"Bip001 Ponytail1", "Skirt"}
    assert "calibration_failed" not in out


def test_skin_weights_still_catch_hands_inside_the_belly() -> None:
    out = fitcheck.check(_decorated([30, 2, 1, 2, 30]))
    belly = [r for r in out["table"] if r["where"].endswith("→ 배")]
    assert out["frames_with_any_hit"] == 3 and belly and belly[0]["ranges"] == ["1~3"]


def test_a_body_jiggle_bone_stays_body_and_its_belly_still_catches() -> None:
    out = fitcheck.check(_decorated([30, 2, 1, 2, 30], jiggle=True))
    kept = out["body_from"]["kept_extra_bones"]
    assert [k["bone"] for k in kept] == ["Bip001 Xtra_Belly"] and kept[0]["as"] == "배"
    assert out["frames_with_any_hit"] == 3
    assert fitcheck.check(_decorated([30, 18, 18, 30], jiggle=True))["frames_with_any_hit"] == 0


def test_no_weights_or_wrong_length_falls_back_to_nearest_bone() -> None:
    d = _decorated([30, 30], weights=True)
    d["vbones"] = d["vbones"][:-5]                       # 점 수가 안 맞으면(위상 바뀐 메시) 가중치를 믿지 않는다
    assert fitcheck.check(d)["body_from"]["skin_weights"] is False


def test_max_read_script_reads_skin_weights_without_touching_undo_or_selection(tmp_path) -> None:
    s = fitcheck.read_script(tmp_path / "d.json", 0, 10, 0)
    for need in ("skinOps.GetVertexWeight", "skinOps.GetBoneName", '\\"vbones\\"', '\\"xparent\\"', "with undo off",
                 "select oldSel", "setCommandPanelTaskMode oldMode"):
        assert need in s, need
    for verb in ("deleteKeys", "addNewKey", "setTransform", "saveMaxFile", "skinOps.SetVertexWeights", "skinOps.ReplaceVertexWeights"):
        assert verb not in s


def test_blender_read_labels_points_by_weight_and_turns_off_outline_modifiers() -> None:
    from alture_jarvis.animator import blender_bridge as bb

    s = bb.READ_PY
    assert '"vbones": vbones' in s and '"xparent": xparent' in s
    assert 'md.type != "ARMATURE"' in s and "show_viewport = True" in s     # 외곽선을 껐다가 되돌린다
    assert "save_as_mainfile" not in s


# ── 2. 영상 → 블로킹 「방향 애매」 ─────────────────────────────────────────────
# 11-05 밤 블렌더 엄마 블로킹(refs/20261105_203656 · lifted_blender.json) 6장면의 3D 관절 · 확신도 그대로. 2번이 좌우 뒤집힘(작업일지 19).
_MOM_POSES = [
    {"no": 1, "joints": [[131.0, 153.0, -81.5], [126.5, 152.5, -80.0], [141.0, 152.5, -81.0], [116.5, 145.0, -82.0], [139.5, 147.0, -85.0], [102.5, 145.0, -103.0], [146.0, 144.5, -100.0], [86.5, 165.5, -142.0], [171.0, 145.0, -100.5], [90.0, 165.5, -170.5], [186.0, 153.5, -130.5], [113.5, 146.5, -165.0], [151.0, 143.5, -162.0], [121.0, 164.5, -188.5], [141.0, 165.0, -208.5], [104.5, 153.0, -242.0], [135.5, 151.5, -268.0]],
     "score": [0.52, 0.43, 0.49, 0.59, 0.58, 0.59, 0.55, 0.48, 0.64, 0.36, 0.63, 0.58, 0.57, 0.7, 0.7, 0.69, 0.75]},
    {"no": 2, "joints": [[210.0, 144.5, -115.0], [211.0, 145.0, -114.0], [208.5, 144.5, -114.0], [171.0, 144.5, -112.0], [207.5, 145.5, -111.5], [160.5, 146.5, -114.0], [202.5, 145.0, -117.5], [161.0, 166.0, -115.0], [201.0, 135.0, -166.5], [174.5, 167.0, -161.5], [176.5, 167.0, -162.0], [160.5, 145.5, -155.5], [172.5, 145.0, -163.0], [117.0, 135.0, -177.0], [153.5, 146.0, -208.5], [80.5, 146.0, -205.5], [154.5, 144.5, -252.0]],
     "score": [0.27, 0.25, 0.3, 0.31, 0.32, 0.34, 0.37, 0.31, 0.36, 0.26, 0.29, 0.5, 0.5, 0.59, 0.61, 0.6, 0.54]},
    {"no": 3, "joints": [[92.5, 152.0, -99.0], [92.5, 151.5, -95.5], [89.5, 144.5, -93.5], [100.5, 147.5, -92.5], [98.5, 145.0, -87.5], [125.0, 148.0, -114.5], [129.5, 134.5, -116.5], [135.5, 165.5, -151.5], [159.5, 135.0, -166.5], [100.5, 166.0, -165.0], [175.0, 165.5, -171.5], [131.5, 147.5, -166.0], [130.5, 136.5, -168.0], [97.5, 132.5, -212.0], [117.5, 137.0, -213.0], [94.5, 144.0, -275.0], [132.0, 141.5, -258.0]],
     "score": [0.44, 0.48, 0.45, 0.41, 0.31, 0.52, 0.42, 0.49, 0.4, 0.42, 0.45, 0.55, 0.47, 0.69, 0.7, 0.71, 0.67]},
    {"no": 4, "joints": [[98.5, 152.5, -89.0], [96.5, 152.0, -84.0], [98.5, 152.0, -85.5], [106.0, 151.5, -82.0], [101.5, 146.5, -83.5], [133.0, 146.5, -96.0], [96.0, 138.0, -103.0], [163.0, 165.0, -116.0], [97.0, 135.5, -123.5], [182.0, 166.0, -139.5], [96.5, 167.0, -146.5], [131.5, 147.5, -171.5], [112.5, 138.0, -168.5], [107.0, 154.0, -216.0], [111.5, 137.0, -212.5], [144.5, 166.5, -272.0], [126.5, 141.0, -245.5]],
     "score": [0.6, 0.59, 0.62, 0.54, 0.52, 0.63, 0.6, 0.62, 0.47, 0.63, 0.45, 0.61, 0.59, 0.73, 0.66, 0.72, 0.66]},
    {"no": 5, "joints": [[93.0, 145.0, -129.5], [92.5, 145.5, -126.5], [91.0, 143.0, -125.5], [102.5, 144.0, -124.0], [107.0, 134.5, -125.0], [117.0, 152.0, -130.0], [116.5, 133.0, -139.0], [113.5, 165.0, -147.5], [128.5, 153.5, -158.5], [90.5, 166.0, -162.5], [134.0, 165.5, -170.5], [164.0, 135.0, -179.5], [142.0, 135.0, -183.0], [145.0, 154.0, -220.5], [117.0, 137.0, -226.5], [144.0, 166.5, -274.0], [119.5, 145.5, -249.5]],
     "score": [0.69, 0.66, 0.66, 0.56, 0.51, 0.69, 0.59, 0.75, 0.43, 0.68, 0.34, 0.64, 0.64, 0.75, 0.75, 0.7, 0.62]},
    {"no": 6, "joints": [[120.5, 118.5, -134.5], [122.5, 124.0, -129.0], [117.0, 123.0, -132.0], [132.0, 133.0, -127.0], [116.0, 132.5, -135.5], [154.0, 133.5, -134.5], [118.5, 130.5, -162.0], [182.5, 134.0, -120.0], [97.5, 135.5, -186.0], [206.5, 137.0, -105.0], [74.0, 135.0, -206.5], [163.0, 144.5, -189.5], [139.5, 145.0, -195.0], [175.5, 151.0, -230.5], [149.5, 147.5, -232.5], [143.0, 165.5, -254.5], [147.0, 166.5, -264.0]],
     "score": [0.6, 0.54, 0.55, 0.48, 0.51, 0.59, 0.58, 0.62, 0.61, 0.63, 0.6, 0.65, 0.64, 0.63, 0.71, 0.51, 0.66]},
]


def test_the_flipped_scene_2_is_marked_unsure_and_front_facing_scenes_are_not() -> None:
    from alture_jarvis.animator import refpose

    marked = {p["no"]: refpose.facing_doubt(p) for p in _MOM_POSES}
    assert marked[2]["unsure"] and "흐리게" in " ".join(marked[2]["why"])       # 옆모습 규칙(0.91)만으로는 못 잡던 장면
    assert marked[2]["sure"] > refpose.FACING_SIDE
    assert not any(marked[n]["unsure"] for n in (1, 4, 6))
    rep = refpose.facing_report(_MOM_POSES)
    assert 2 in rep["poses"] and set(rep["poses"]) <= {2, 3, 5}


def test_max_report_marks_a_scene_by_low_torso_score_even_when_shoulders_look_wide(tmp_path) -> None:
    from alture_jarvis.animator import refpose

    s = refpose.biped_fit_script(_MOM_POSES[:2], "Bip001", 0, 10, tmp_path / "r.json", [0, 10])
    assert '\\"torso_score\\":0.34' in s
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps([{"pose": 1, "frame": 0, "facing": 0.99, "facing_sure": 0.70, "torso_score": 0.55},
                               {"pose": 2, "frame": 10, "facing": 0.99, "facing_sure": 0.91, "torso_score": 0.34},
                               {"pose": 2, "frame": 10, "bone": "Bip001 Spine", "dot": 0.99, "deg2d": 3.0}]), encoding="utf-8")
    assert refpose.read_fit_report(rep)["facing_unsure"]["poses"] == [2]


# ── 3. 자동 수정 — 다리(무릎 · 정강이 → 배 · 가슴) ─────────────────────────────────────

def _kick_dump(kicks, *, planted_both=False, keys=True):
    """서 있는 몸. kicks[i] 가 참이면 그 프레임에 왼 무릎을 배 안으로 올린다(발은 뜸). planted_both 면 두 발은 바닥 그대로(쪼그림)."""
    from test_animator_fitcheck_1106 import _m, _pose

    names = list(_pose(30).keys())
    rows = []
    for i, k in enumerate(kicks):
        b = _pose(30)
        if k:
            b["L Thigh"] = _m((7, 0, 50), x=(0, -0.45, 0.89))          # 허벅지를 앞 위로 → 무릎이 배 안(7, -6, 62)
            b["L Calf"] = _m((7, -6, 62), x=(0, -0.3, -0.95))
            b["L Foot"] = _m((7, -6 if planted_both else -12, 6 if planted_both else 42), x=(0, -1, 0))
        rows.append([i] + [b[n] for n in names])
    d = {"ok": True, "bones": names, "start": 0, "end": len(kicks) - 1, "ref": 0, "frames": rows, "verts": _body_verts()}
    if keys:
        d["keys"] = {"L": [0], "R": [0], "L Thigh": list(range(len(kicks))), "R Thigh": [0], "Spine": list(range(len(kicks)))}
    return d


def _lateral(d):
    return float(np.dot(fitcheck._unit(np.array(d)), np.array([-1.0, 0, 0])))   # 몸 좌우 축(오른 허벅지 → 왼 허벅지 반대) 성분


def test_a_knee_in_the_belly_is_found_and_fixed_by_lean_or_thigh_only_in_the_body_plane() -> None:
    d = _kick_dump([0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    out = fitcheck.check(d)
    assert any(r["where"] == "왼 다리 → 배" for r in out["table"])
    plan = fitcheck.plan_fix_legs(d)
    assert plan["frames_hit"]["왼 다리"] == 3 and not plan["unsolved"]
    assert plan["legs"], plan
    names = d["bones"]
    for bone, rows in plan["legs"].items():
        assert bone in ("Spine", "L Thigh")                                 # 디딘 오른 다리는 안 건드림
        k = names.index(bone) + 1
        for f, dvec, deg in rows:
            assert f in d["keys"][bone]                                     # 원래 키 자리에서만
            assert 0 < deg <= fitcheck.LEG_MAX_DEG
            orig = d["frames"][f][k][:3]
            assert abs(_lateral(dvec) - _lateral(orig)) < 1e-3              # 좌우 축 성분 그대로 = 옆으로 안 벌림
    s = fitcheck.write_fix_script(plan)
    assert s.count('undo "Sonjari fit fix" on') == 1 and "holdMaxFile()" in s
    assert s.index('#("Spine"') < s.index('#("L Thigh"') if "Spine" in plan["legs"] and "L Thigh" in plan["legs"] else True


def test_with_both_feet_planted_the_thigh_is_left_alone_and_lean_stays_under_15() -> None:
    d = _kick_dump([0, 0, 1, 1, 1, 0, 0, 0], planted_both=True)
    plan = fitcheck.plan_fix_legs(d)
    assert "L Thigh" not in plan["legs"] and "R Thigh" not in plan["legs"]
    assert all(deg <= fitcheck.LEAN_PLANTED_DEG for _f, _d, deg in plan["legs"].get("Spine", []))


def test_bones_without_keys_get_no_new_keys() -> None:
    d = _kick_dump([0, 0, 1, 1, 1, 0, 0, 0], keys=False)
    plan = fitcheck.plan_fix_legs(d)
    assert plan["legs"] == {} and plan["no_keys"]


def test_repeated_passes_do_not_stack_past_the_limit_against_the_original() -> None:
    d = _kick_dump([0, 0, 1, 1, 1, 0, 0, 0, 0, 0])
    first = fitcheck.plan_fix_legs(d)
    # 원본 대비 이미 상한까지 돌린 척: 같은 덤프를 base 로 주고, 척추를 30도 돌려 둔 판을 다시 계획
    k = d["bones"].index("Spine") + 1
    turned = json.loads(json.dumps(d))
    R = fitcheck._rot(np.array([1.0, 0, 0]), 30)
    for r in turned["frames"]:
        m = np.array(r[k], float).reshape(4, 3)
        m[:3] = m[:3] @ R.T
        r[k] = m.ravel().tolist()
    again = fitcheck.plan_fix_legs(turned, base=d)
    assert first["legs"]
    assert "Spine" not in again["legs"]                                     # 남은 상한 0 → 척추는 더 안 돌린다


def test_blender_fix_writes_items_for_any_bone_and_reads_thigh_spine_keys() -> None:
    from alture_jarvis.animator import blender_bridge as bb

    assert 'A["items"]' in bb.WRITE_FIX_PY and 'bmap[bone]' in bb.WRITE_FIX_PY
    assert '("L Thigh", "R Thigh", "Spine")' in bb.READ_PY


# ── 11-10 밤 맥스 실측에서 나온 셋(바이페드 + 스킨 시험 장면 · 회사 자료 없음) ─────────────────────────────

def _max_kneehigh():
    """맥스에서 읽은 실제 덤프(30~52프레임 · 몸 점 1/10): 상체를 숙인 채 왼무릎을 가슴보다 높이 든다."""
    from pathlib import Path

    return json.loads((Path(__file__).parent / "fixtures" / "max_kneehigh_lean_1110.json").read_text(encoding="utf-8"))


def _back_moves(d, plan):
    k = d["bones"].index("Spine") + 1
    out = []
    for f, dvec, _deg in plan["legs"].get("Spine", []):
        r = next(x for x in d["frames"] if x[0] == f)
        m = {n: fitcheck._mats(x) for n, x in zip(d["bones"], r[1:])}
        ax = fitcheck._unit(m["R Thigh"][3, :3] - m["L Thigh"][3, :3])
        back = fitcheck._unit(np.cross(ax, fitcheck._unit(m["Spine"][0, :3])))
        out.append(float((np.array(dvec) - fitcheck._mats(r[k])[0, :3]) @ back))
    return out


def test_lean_never_folds_the_body_forward_when_the_knee_is_above_a_leaned_chest() -> None:
    d = _max_kneehigh()
    assert any(" 다리 " in r["where"] for r in fitcheck.check(d)["table"])
    for kw in ({}, {"max_thigh": 0}):                                    # 기본 · 허벅지를 못 쓸 때(젖힘만)
        plan = fitcheck.plan_fix_legs(d, **kw)
        assert all(v >= 0 for v in _back_moves(d, plan)), (kw, _back_moves(d, plan))   # 옛 판: 네 키 모두 「더 숙임」


def test_max_read_keeps_figure_mode_off_the_undo_list() -> None:
    # 「고침 → 다시 점검 → Ctrl+Z」에서 Ctrl+Z 가 고침 대신 피겨 모드를 켜 동작이 사라진 것처럼 보였다(11-10 맥스)
    sets = [ln for ln in fitcheck.READ_SCRIPT.splitlines() if "figureMode =" in ln]
    assert len(sets) == 2 and all("with undo off" in ln for ln in sets), sets


def test_max_align_does_not_accept_a_wrong_way_turn_for_small_fixes() -> None:
    # 문턱 0.99(약 8도) → 4도보다 작은 고침은 반대로 돌고도 통과했다(맥스 실측: 2도 → 목표와 4도 · 팔 8칸 → 17칸)
    from alture_jarvis.animator.refpose import _ALIGN_FN, _FACING_FN

    for fn in (_ALIGN_FN, _FACING_FN):
        assert "> 0.99 do return" not in fn and "> 0.99999 do return" in fn
        assert "bestRot" in fn                                           # 둘 다 덜 맞으면 가장 나았던 쪽(처음 자세로 버리지 않음)
