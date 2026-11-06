"""맥(애플 칩) 메모리 예산 → 모델 추천 (2026-11-03 · 대표 지시 「16GB 에 묶지 마라 · 표는 한 벌」).

맥은 그래픽카드 메모리가 따로 없어, 통합 메모리를 「모델에 남는 몫」으로 센 카드 한 장(`apple_memory_card`)을 만들고
윈도우와 같은 추천 함수(`recommend`) · 같은 사다리 표가 고른다. 여기서는 메모리 값을 가짜로 넣어 등급마다 무엇을 고르는지 본다.
GPU 상한은 맥미니 16GB 에서 잰 10.67GB(=2/3)만 실측이고, 다른 크기의 상한은 짐작 입력이다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.setup_profile import SONJARI_SELF_GB, apple_memory_card, recommend


def _rec(total: float, *, free: float | None = 84.0, limit: float | None = None, loaded: float = 0.0) -> tuple[dict, dict]:
    card = apple_memory_card(chip="Apple M", total_gb=total, gpu_limit_gb=limit if limit is not None
                             else round(total * (2 / 3 if total <= 36 else 3 / 4), 2),
                             free_percent=free, ollama_loaded_gb=loaded)
    return card, recommend({"gpus": [card], "ollama": {"installed": []}, "ram_gb": total, "disk_free_gb": 200})


def test_eight_gb_mac_is_told_it_is_too_small() -> None:
    card, rec = _rec(8)
    assert rec["mode"] == "too_small"


@pytest.mark.parametrize("total", [16, 24, 32, 36, 48, 64, 96, 128])
def test_every_bigger_mac_gets_a_local_model_that_fits_its_share(total: float) -> None:
    card, rec = _rec(total)
    assert rec["mode"] == "local"
    need = rec["picks"][0]["vram_gb"]
    assert need <= card["model_share_gb"]
    assert "모델에 남는 몫" in rec["reasons"][0]


def test_sixteen_gb_uses_the_measured_gpu_limit() -> None:
    card, rec = _rec(16, limit=10.67)
    assert card["memory"]["limit_source"] == "metal" and card["model_share_gb"] == 10.67
    assert rec["model_key"] == "qwen3.5-9b-q3"


def test_twenty_four_gb_gets_the_27b_and_big_macs_the_full_window() -> None:
    assert _rec(24)[1]["model_key"] == "qwen3.8-27b-swift-iq3xxs"
    for total in (36, 64, 128):
        rec = _rec(total)[1]
        assert (rec["model_key"], rec["num_ctx"]) == ("qwen3.8-27b-swift", 131072)


def test_budget_grows_with_memory_and_shrinks_with_other_apps() -> None:
    shares = [_rec(t)[0]["model_share_gb"] for t in (8, 16, 24, 32, 48, 96)]
    assert shares == sorted(shares)
    busy, _ = _rec(16, free=40.0)
    idle, _ = _rec(16, free=90.0)
    assert busy["model_share_gb"] < idle["model_share_gb"]


def test_sonjari_own_share_is_subtracted() -> None:
    card, _ = _rec(16, free=100.0, limit=100.0)
    assert card["model_share_gb"] == pytest.approx(16 - SONJARI_SELF_GB)


def test_a_model_already_loaded_in_our_ollama_is_not_counted_as_other_apps() -> None:
    plain, _ = _rec(16, free=50.0)
    loaded, _ = _rec(16, free=50.0, loaded=6.0)
    assert loaded["memory"]["others_gb"] == pytest.approx(plain["memory"]["others_gb"] - 6.0)


def test_unknown_limit_and_pressure_are_said_so() -> None:
    card = apple_memory_card(chip="Apple M", total_gb=24, gpu_limit_gb=None, free_percent=None)
    assert card["memory"]["limit_source"] == "guess_two_thirds"
    assert card["memory"]["others_source"] == "unknown"


def test_mac_card_reading_drives_the_same_spill_rule() -> None:
    """맥의 「카드 가득」은 메모리 여유로 본다 · 큰 맥(GPU 상한 16.5GB 넘음)은 넘기지 않고 알리기만(11-02 규칙 그대로)."""
    from alture_jarvis.gpu_pressure import card_is_full, read_card_mac
    from alture_jarvis.heavy_apps import SMALL_CARD_GB

    busy = read_card_mac(limit_gb=lambda: 10.67, total_gb=lambda: 16.0, free_percent=lambda: 2.0)
    idle = read_card_mac(limit_gb=lambda: 10.67, total_gb=lambda: 16.0, free_percent=lambda: 80.0)
    assert card_is_full(busy) is True and card_is_full(idle) is False
    assert busy["total_gb"] <= SMALL_CARD_GB              # 16GB 맥은 「작은 카드」 — 넘길 수 있다
    big = read_card_mac(limit_gb=lambda: 48.0, total_gb=lambda: 64.0, free_percent=lambda: 1.0)
    assert big["total_gb"] > SMALL_CARD_GB                # 64GB 맥은 알리기만
    assert read_card_mac(limit_gb=lambda: None, total_gb=lambda: 16.0, free_percent=lambda: 50.0) is None


def test_mac_blurb_only_on_apple_profile():
    """맥에는 맥에서 잰 설명이, 윈도우에는 원래 설명이 나간다(2026-11-03 대표: 「8GB 카드에서…」가 맥에 그대로 나왔다)."""
    from alture_jarvis.setup_profile import apple_memory_card, catalog_view

    card = apple_memory_card(chip="Apple M4", total_gb=16, gpu_limit_gb=10.67, free_percent=80)
    mac = {row["key"]: row for row in catalog_view({"gpus": [card], "ollama": {}})}
    win = {row["key"]: row for row in catalog_view({"gpus": [{"vendor": "nvidia", "vram_total_gb": 8, "usable_gb": 7.5}], "ollama": {}})}
    assert mac["qwen3.5-9b-q3"]["blurb"].startswith("16GB 맥")
    assert win["qwen3.5-9b-q3"]["blurb"].startswith("8GB 카드")
