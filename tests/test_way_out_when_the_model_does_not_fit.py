"""고른 모델을 그래픽카드에 다 못 올렸을 때 사람이 고를 두 길을 준다 (2026-10-10 대표).

전에는 빨간 글 한 줄이었다 — 「다른 GPU 앱을 종료한 뒤 다시 시도해 주세요」. 무엇을 닫아야 하는지도, 닫으면 되는지도,
안 닫고 가는 길도 없었다. 재료는 백엔드가 준다: 닫을 수 있는 프로그램과 「다 닫으면 들어가는가」, 지금 들어가는 작은 모델.
닫는 것은 사람이 한다 — 우리는 남의 프로그램을 끄지 않는다.
"""
from __future__ import annotations

from alture_jarvis.model_catalog import by_key
from alture_jarvis.model_setup import way_out
from alture_jarvis.setup_profile import smaller_that_fits

BIG = "qwen3.8-27b-swift"
MID = "qwen3.5-9b"


def _card(total: float, used: float, apps: list[str]) -> dict:
    return {"gpus": [{"total_gb": total, "used_gb": used, "apps": apps}]}


def test_it_says_what_to_close_and_what_fits_right_now() -> None:
    out = way_out(BIG, installed={"qwen3.5:9b"}, snapshot=_card(16.0, 2.6, ["dwm", "explorer", "chrome", "Photoshop"]))
    assert out["model_key"] == BIG
    assert out["needs_gb"] == min(by_key(BIG).vram_gb.values())
    assert out["card"] == {"total_gb": 16.0, "used_gb": 2.6, "free_gb": 13.4}
    assert out["close"]["apps"] == ["chrome", "Photoshop"], "윈도우 기본 프로그램은 닫으라고 하지 않는다"
    assert out["close"]["would_fit"] is True
    smaller = out["smaller"]
    assert smaller["model_key"] == MID and smaller["installed"] is True
    assert smaller["needs_gb"] < out["needs_gb"]
    assert smaller["needs_gb"] <= out["card"]["free_gb"], "지금 빈 자리에 들어가는 것만 권한다"
    assert smaller["weak_at"], "작은 모델로 가면 무엇이 약해지는지 같이 준다"


def test_a_card_too_small_for_the_model_is_not_told_to_close_things() -> None:
    """다 닫아도 안 들어가는 카드에 「닫으세요」는 헛걸음이다 — 화면이 그 말을 안 하게 알려 준다."""
    out = way_out(BIG, snapshot=_card(12.0, 1.0, ["chrome"]))
    assert out["close"]["would_fit"] is False
    assert out["smaller"] and out["smaller"]["model_key"] != BIG


def test_nothing_smaller_fits_means_no_smaller_offer() -> None:
    out = way_out(MID, snapshot=_card(8.0, 7.6, ["game"]))
    assert out["smaller"] is None
    assert out["close"]["apps"] == ["game"]


def test_unknown_card_makes_no_claims() -> None:
    out = way_out(MID, snapshot={})
    assert out["card"] == {"total_gb": None, "used_gb": None, "free_gb": None}
    assert out["close"] == {"apps": [], "would_fit": None}
    assert out["smaller"] is None, "빈 메모리를 모르면 「들어갑니다」를 말하지 않는다"


def test_an_unknown_model_gives_nothing() -> None:
    assert way_out("no-such-model", snapshot=_card(24.0, 1.0, [])) == {}


def test_smaller_is_never_the_same_model_in_a_smaller_window() -> None:
    """같은 모델의 작은 창은 적용할 때 이미 한 칸씩 줄여 재 봤다 — 다시 권하지 않는다."""
    for free in (6.0, 9.0, 12.0, 15.0, 20.0):
        pick = smaller_that_fits(free, BIG)
        if pick is not None:
            model, ctx, need = pick
            assert model.key != BIG
            assert need < min(by_key(BIG).vram_gb.values())
            assert ctx in model.vram_gb and model.status == "verified"
    assert smaller_that_fits(None, BIG) is None
    assert smaller_that_fits(0.5, BIG) is None


def test_the_installed_mark_ignores_the_latest_suffix() -> None:
    # 빈 자리 12.8GB — 27B 작은 판(13.5GB + 여유)은 안 들어가고 9B 가 들어가는 자리(2026-10-10 부터 작은 판도 사다리에 있다).
    card = _card(16.0, 3.2, [])
    assert way_out(BIG, installed={"qwen3.5:9b:latest"}, snapshot=card)["smaller"]["installed"] in (True, False)
    assert way_out(BIG, installed=set(), snapshot=card)["smaller"]["installed"] is False
    tag = by_key(MID).ollama_tag
    assert way_out(BIG, installed={tag}, snapshot=card)["smaller"]["installed"] is True


def test_the_failed_apply_carries_the_way_out() -> None:
    """배선: 못 올린 두 끝(메모리 모자람 · 다 안 올라감)이 둘 다 이 재료를 싣는다."""
    import inspect

    from alture_jarvis import model_setup

    source = inspect.getsource(model_setup.ModelSetup._measure_and_save) if hasattr(model_setup, "ModelSetup") else inspect.getsource(model_setup)
    assert source.count("self._way_out(catalog_key)") == 2
