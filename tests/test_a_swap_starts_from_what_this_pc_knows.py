"""교체는 이 PC 가 이미 아는 것부터 (2026-09-30).

3.8 → 3.6 교체가 10분 가까이 걸렸다: 128K(샘) → 64K(샌다고 어제 잰 값) → 32K 로 모델을 세 번 새로 올렸고
(한 번 42~80초), 대표는 그 뒤 쓰려던 64K 를 다시 골랐다. 대표: 「직전에 쓰던 컨텍스트를 넣어 주면 된다」.
"""
from pathlib import Path

from alture_jarvis.model_setup import read_ceilings, read_selection, remember_context_choice, _remember_ceiling

from test_a_spilling_context_steps_down import Rig, _service, _tried

TAG = "qwen3.6:35b-a3b"
MEASURED = {
    "model": TAG, "ceiling": 36864,
    "steps": [
        {"num_ctx": 32768, "passed": True, "gpu_share": 1.0, "tokens_per_sec": 100.0},
        {"num_ctx": 65536, "passed": False, "gpu_share": 0.966, "tokens_per_sec": 60.0},
        {"num_ctx": 36864, "passed": True, "gpu_share": 1.0, "tokens_per_sec": 98.0},
    ],
}


def test_a_remembered_choice_loads_once_even_if_it_spills(tmp_path: Path) -> None:
    rig = Rig({131072: 0.9, 65536: 0.966})
    setup, _ = _service(tmp_path, rig)
    _remember_ceiling(setup.config.data_dir, MEASURED)
    remember_context_choice(setup.config.data_dir, TAG, 65536)

    result = setup.select(TAG, "chat", 131072)  # 고르개에서 **모델을** 바꾸는 길 — 넘어오는 크기는 표의 기본값이다

    assert result["ok"], result
    assert _tried(rig) == [(TAG, 65536)]
    assert read_selection(setup.config.data_dir)["num_ctx"] == 65536
    assert any("지난번에 고른 64K" in w for w in result["warnings"]), result["warnings"]


def test_without_a_choice_it_starts_at_the_measured_ceiling(tmp_path: Path) -> None:
    rig = Rig({131072: 0.9, 65536: 0.966})
    setup, _ = _service(tmp_path, rig)
    _remember_ceiling(setup.config.data_dir, MEASURED)

    assert setup.apply_tag(TAG, 131072)["ok"]
    assert _tried(rig) == [(TAG, 36864)]


def test_a_rung_measured_as_failing_is_not_tried_again(tmp_path: Path) -> None:
    rig = Rig({131072: 0.9, 65536: 0.966, 32768: 1.0})
    setup, _ = _service(tmp_path, rig)
    _remember_ceiling(setup.config.data_dir, {"model": TAG, "steps": MEASURED["steps"]})  # 상한 없이 칸만

    assert setup.apply_tag(TAG, 131072)["ok"]
    assert (TAG, 65536) not in _tried(rig)


def test_the_choice_survives_a_new_measurement(tmp_path: Path) -> None:
    rig = Rig({})
    setup, _ = _service(tmp_path, rig)
    remember_context_choice(setup.config.data_dir, TAG, 65536)
    _remember_ceiling(setup.config.data_dir, MEASURED)
    assert read_ceilings(setup.config.data_dir)[TAG]["chosen"] == 65536


# ── 사람이 지금 고른 칸이 기억보다 먼저다 (2026-10-05) ─────────────────────────────────────────────
#
# 9B 를 시험하다 봤다(가짜 홈): 모델 카드에서 64K·128K 를 골라 적용했는데 「성공」이라면서 예전에 쓰던 32K 로 올라왔다.
# 기억은 모델만 바꿀 때 쓰는 것이다 — 카드에서 칸을 고른 요청까지 덮으면 눌러도 안 바뀌는 단추가 된다.


def test_a_rung_picked_on_the_model_card_beats_the_remembered_one(tmp_path: Path) -> None:
    rig = Rig({131072: 1.0, 65536: 1.0, 32768: 1.0})
    setup, _ = _service(tmp_path, rig)
    remember_context_choice(setup.config.data_dir, TAG, 32768)

    result = setup.apply_tag(TAG, 65536)  # 카드에서 고른 칸(마법사·설정의 「적용」)

    assert result["ok"], result
    assert _tried(rig) == [(TAG, 65536)]
    assert read_selection(setup.config.data_dir)["num_ctx"] == 65536
    assert read_ceilings(setup.config.data_dir)[TAG]["chosen"] == 65536, "새로 고른 칸이 다음 기억이 된다"


def test_picking_the_same_rung_again_still_loads_it_once(tmp_path: Path) -> None:
    rig = Rig({65536: 0.966})
    setup, _ = _service(tmp_path, rig)
    remember_context_choice(setup.config.data_dir, TAG, 65536)

    result = setup.apply_tag(TAG, 65536)

    assert result["ok"], result
    assert _tried(rig) == [(TAG, 65536)], "알고 고른 칸은 새도 줄이지 않는다"

