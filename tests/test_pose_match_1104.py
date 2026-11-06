"""포즈로 찾기 — 같은 눈금(9마디 방향) · 바라보는 방향 빼기 · 좌우 반전 · 순위 (2026-11-04)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from alture_jarvis.animator import pose_match as pm

# COCO 17점(맥스 좌표 X 오른쪽 · Y 깊이 · Z 위). 사람이 +Y 를 보고 선 자세 — 왼쪽은 -X.
STAND = np.zeros((17, 3))
STAND[[5, 6]] = [[-20, 0, 150], [20, 0, 150]]      # 어깨 L R
STAND[[7, 8]] = [[-25, 0, 120], [25, 0, 120]]      # 팔꿈치(팔 내림)
STAND[[9, 10]] = [[-25, 0, 95], [25, 0, 95]]       # 손목
STAND[[11, 12]] = [[-10, 0, 100], [10, 0, 100]]    # 골반
STAND[[13, 14]] = [[-10, 0, 55], [10, 0, 55]]      # 무릎
STAND[[15, 16]] = [[-10, 0, 10], [10, 0, 10]]      # 발목


def _rotz(points: np.ndarray, deg: float) -> np.ndarray:
    a = np.radians(deg)
    R = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    return points @ R.T


def _raise_right_arm(points: np.ndarray) -> np.ndarray:
    p = points.copy()
    p[8] = [25, 0, 180]
    p[10] = [25, 0, 210]
    return p


def test_facing_direction_and_body_size_do_not_matter() -> None:
    a = pm.from_joints(STAND)
    b = pm.from_joints(_rotz(STAND * 1.7, 73))  # 더 크고, 73도 돌아선 같은 자세
    assert float(pm.distance(a, b[None])[0]) < 1e-6


def test_a_raised_arm_is_farther_than_the_same_pose() -> None:
    stand, raised = pm.from_joints(STAND), pm.from_joints(_raise_right_arm(STAND))
    assert float(pm.distance(stand, raised[None])[0]) > 0.1


def test_mirror_swaps_left_and_right() -> None:
    right_up = pm.from_joints(_raise_right_arm(STAND))
    left = _raise_right_arm(STAND)
    left[[5, 7, 9, 11, 13, 15, 6, 8, 10, 12, 14, 16]] = left[[6, 8, 10, 12, 14, 16, 5, 7, 9, 11, 13, 15]]
    left[:, 0] *= -1
    left_up = pm.from_joints(left)
    assert float(pm.distance(right_up, left_up[None])[0]) > 0.1
    assert float(pm.distance(pm.mirror(right_up), left_up[None])[0]) < 1e-6
    assert np.allclose(pm.mirror(pm.mirror(right_up)), right_up)


def _rows(feats: np.ndarray, side: np.ndarray) -> list[list[float]]:
    return [[2 * i, *f.ravel().tolist(), *side.tolist()] for i, f in enumerate(feats)]


def test_search_ranks_the_motion_that_contains_the_pose_first(tmp_path: Path) -> None:
    side = np.array([1.0, 0, 0])
    stand, raised = pm.from_joints(STAND), pm.from_joints(_raise_right_arm(STAND))
    entries = []
    for name, frames in (("idle", [stand, stand]), ("attack", [stand, raised, stand]), ("nofeat", None)):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "motion.bip").write_bytes(b"")
        if frames is not None:
            (folder / pm.FEATURE_FILE).write_text(json.dumps({"rows": _rows(np.array(frames), side)}), encoding="utf-8")
        entries.append({"id": name, "bip": str(folder / "motion.bip"), "kind": "motion"})
    entries.append({"id": "mesh", "bip": str(tmp_path / "x"), "kind": "model"})  # 모델 파일은 안 본다
    out = pm.search(entries, raised, k=3)
    assert [r["id"] for r in out["found"]][:2] == ["attack", "idle"]
    assert out["found"][0]["frame"] == 2 and out["found"][0]["distance"] < 1e-3
    assert out["compared"] == 2 and out["no_features"] == 1


def test_batch_script_cleans_up_its_temporary_biped(tmp_path: Path) -> None:
    script = pm.features_batch_script([(tmp_path / "a", 0, 30)], tmp_path / "log.txt")
    assert "biped.createNew" in script and "findItem before o == 0" in script
    assert script.count("loadBipFile") == 1 and "#matchFileStruct" in script
