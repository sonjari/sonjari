"""두 번 굽기 흐름 보강 — 일부러 깨 보는 시험 (2026-11-15 · 설계 `설계_3D두번굽기_분업`).

- 카드 고르기: 3090 은 Strata 가 꽉 · 3060 은 빔 → 3060(1번) · 고른 까닭이 영수증에 · 사람이 번호를 주면 그대로 · 카드 없으면 기본
- 바닥 자르기 제안: 공이 판에 점으로 닿으면 「몇 mm 자르면 넓이 얼마」 · 평평한 상자는 제안 없음 · 인자로 자르면 바닥이 평평
- 단계 기록: 다시 뜨기 · 면 줄이기 · 받침 고르기(· 썰기)가 순서대로 · 초 · 한 줄 · 알림
- 판단거리: 바닥이 점처럼 닿음 · 느린 단계
- 취소 틈: 대기열에서 막 빠져 시작하는 판을 취소해도 오류 없이 True
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from alture_jarvis.gen3d.glb import Mesh
from alture_jarvis.gen3d.memory import pick_gpu
from alture_jarvis.gen3d.printing import needs_decision, prepare_print, suggest_floor_cut
from alture_jarvis.gen3d.remesh import remesh
from test_gen3d_print_1114 import _box
from test_gen3d_snap_1114 import _sphere

CARDS = [{"index": 0, "name": "NVIDIA GeForce RTX 3090", "free_mib": 2891, "total_mib": 24576},
         {"index": 1, "name": "NVIDIA GeForce RTX 3060", "free_mib": 11170, "total_mib": 12288}]


def test_pick_gpu_takes_the_card_with_most_free_memory() -> None:
    assert pick_gpu(CARDS)["index"] == 1
    assert pick_gpu([]) is None


def test_runner_uses_the_picked_card_and_says_why(tmp_path: Path) -> None:
    from test_gen3d_1114 import _runner, _wait

    calls: list = []
    runner = _runner(tmp_path, calls=calls)
    runner._pick_gpu = lambda: CARDS[1]
    image = tmp_path / "a.png"
    image.write_bytes(b"png")
    done = _wait(runner, runner.submit(image))
    assert done["state"] == "done"
    env = calls[0][1]["env"]
    assert env["CUDA_VISIBLE_DEVICES"] == "1" and env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    measured = done["receipt"]["measured"]
    assert measured.get("gpu_pick", {}).get("name", "").endswith("3060") or "gpu_pick" in str(done["receipt"])
    # 사람이 번호를 주면 고르지 않는다
    calls.clear()
    runner._pick_gpu = lambda: (_ for _ in ()).throw(AssertionError("고르면 안 됨"))
    _wait(runner, runner.submit(image, gpu=0))
    assert calls[0][1]["env"]["CUDA_VISIBLE_DEVICES"] == "0"


def test_cancel_in_the_start_gap_does_not_crash(tmp_path: Path) -> None:
    from alture_jarvis.gen3d.runner import Job
    from test_gen3d_1114 import _runner

    runner = _runner(tmp_path)
    job = Job("g3_20261115_000000_abcdef", tmp_path, tmp_path / "x.png", 512, "trellis", None, None, ["glb"], 80.0)
    runner._jobs[job.job_id] = job  # 대기열에는 없고 상태는 아직 queued — 막 시작하는 중
    assert runner.cancel(job.job_id) is True and job.cancel_requested


def _ball_on_floor() -> tuple[np.ndarray, np.ndarray]:
    v, f = _sphere(10)  # 가운데 (12,12,12) · 바닥 z=2 에 점으로 닿음
    return v, f


def test_floor_cut_is_suggested_for_a_ball_and_not_for_a_box() -> None:
    rm = remesh(*_ball_on_floor(), pitch=0.25, smooth_rounds=0, keep_grid=True, thicken_to_mm=0)
    hint = suggest_floor_cut(rm)
    assert hint and 0 < hint["cut_mm"] <= 3.0 and hint["contact_after_mm2"] > 5 * hint["contact_now_mm2"]
    box = remesh(*_box((0, 0, 0), (20, 20, 10)), pitch=0.5, smooth_rounds=0, keep_grid=True, thicken_to_mm=0)
    assert suggest_floor_cut(box) is None


def test_prepare_print_records_steps_and_flags_a_point_contact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_GEN3D_SLICE", "0")
    seen: list[dict[str, Any]] = []
    v, f = _ball_on_floor()
    out = prepare_print(Mesh(v, f), tmp_path, "ball", ["stl"], 20.0, pitch=0.25, on_stage=seen.append)
    rep = out["report"]
    names = [s["name"] for s in rep["steps"]]
    assert names == ["다시 뜨기", "면 줄이기", "받침 고르기"]
    assert all(s["sec"] is not None and s["info"] for s in rep["steps"])
    assert [e["phase"] for e in seen][:2] == ["start", "done"]
    assert rep.get("floor_suggestion") and any("점처럼" in n for n in rep["needs_decision"])
    # 제안대로 자르면 바닥이 평평 · 판단거리에서 「점처럼」이 사라진다
    cut = rep["floor_suggestion"]["cut_mm"]
    (tmp_path / "b").mkdir()
    out2 = prepare_print(Mesh(v, f), tmp_path / "b", "ball", ["stl"], 20.0, pitch=0.25, floor_cut_mm=cut + 1.0)
    assert out2["report"]["remesh"]["floor_cut_mm"] > 0 and "floor_suggestion" not in out2["report"]
    assert not any("점처럼" in n for n in out2["report"]["needs_decision"])


def test_slow_steps_and_leaks_become_decisions() -> None:
    class R:
        leaked = True
        thin_share = 0.0

    rep = {"plan": {"measured": {"base_area_mm2": 500.0}}, "slice": {"ok": False, "error": "timeout"}}
    out = needs_decision(R(), rep, [{"name": "다시 뜨기", "sec": 400.0}], None)
    assert any("속 빈" in n for n in out) and any("썰기 실패" in n for n in out) and any("400초" in n for n in out)
    assert not any("점처럼" in n for n in out)


def test_floor_cut_argument_is_checked(tmp_path: Path) -> None:
    from alture_jarvis.gen3d.runner import _floor

    assert _floor(None) is None and _floor("") is None and _floor(2) == 2.0
    for bad in (-1, 31):
        with pytest.raises(ValueError):
            _floor(bad)
    del tmp_path
