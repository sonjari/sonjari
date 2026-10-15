"""그림을 켠 채로는 빠듯한 카드에서 설정 화면이 「가능」이라 해 놓고 못 올리던 것 (2026-10-15).

사무실 6GB 노트북(RTX 3050 Laptop 6GB · 쓸 수 있는 메모리 5.0GB): 설정 → 모델에서 「Qwen 3.5 4B (3비트) · 48K · 4.9GB — 가능」을
눌렀더니 48K 는 카드에 70.7% · 32K 는 83.6% 만 올라가 적용되지 않았다.

- 「가능」은 그림을 켠 값(4.9GB)으로 셌는데, 그 값은 **잰 것이 아니라** 글만 읽기 4.21 + 그림 부속 0.67 로 어림한 것이었다.
  Ollama 0.35 는 그림 부속이 붙은 모델을 올릴 때 「부속 무게 + 1GiB」를 따로 비워 둔다(10-13 확인) — 그 1GiB 가 어림에 없었다.
- 설정 화면의 「이걸로 바꾸기」는 그림 읽기를 말하지 않고(`eyes=None`) 불러 그림을 단 채 올렸다.
  마법사는 같은 카드에서 이 모델을 글만 읽기로 올린다(`_TEXT_ONLY_RUNGS`) — 설정 화면만 달랐다.

지키는 약속:
- 그림을 켠 값이 빠듯하고(남는 자리 < `TIGHT_FIT_SPARE_GB`) 글만 읽기는 들어가면, 목록은 「글만 읽기」 칸으로 보이고(`text_only`)
  적용도 말하지 않았을 때(`eyes=None`) 글만 읽기로 올린다.
- 큰 카드(그림을 켜도 넉넉)는 지금 그대로 그림을 읽는다. 사람이 그림을 켜라고 하면(`eyes=True`) 그대로 따른다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_catalog import by_key
from alture_jarvis.model_setup import SetupService
from alture_jarvis.setup_profile import catalog_view, pictures_too_tight

SIX = {"gpus": [{"name": "NVIDIA GeForce RTX 3050 6GB Laptop GPU", "vram_total_gb": 6.0, "display_active": True}]}
TWENTY_FOUR = {"gpus": [{"name": "NVIDIA GeForce RTX 3090", "vram_total_gb": 24.0, "display_active": True}]}


def _row(profile: dict, key: str) -> dict:
    return next(row for row in catalog_view(profile) if row["key"] == key)


def test_on_six_gb_the_four_b_three_bit_is_listed_as_text_only_at_48k() -> None:
    row = _row(SIX, "qwen3.5-4b-q3")
    assert row["fits"] is True
    assert row["text_only"] is True
    assert row["largest_fitting_ctx"] == 49152
    assert row["text_only_need_gb"] == 4.21


def test_on_a_big_card_the_same_model_keeps_reading_pictures() -> None:
    row = _row(TWENTY_FOUR, "qwen3.5-4b-q3")
    assert row["text_only"] is False
    assert pictures_too_tight(by_key("qwen3.5-4b-q3"), 49152, TWENTY_FOUR) is False


def test_a_model_without_a_text_only_size_is_unchanged() -> None:
    row = _row(SIX, "qwen3.5-2b")
    assert row["text_only"] is False


def _service(tmp_path: Path, profile: dict) -> tuple[SetupService, list[dict]]:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    service = SetupService(config, post=lambda *a, **k: {}, get=lambda url: {"models": []}, stream=lambda url, body: iter(()))
    service.profile = lambda *a, **k: profile
    made: list[str] = []
    service.text_only_tag = lambda tag, name: made.append(name) or {"ok": True, "tag": f"sonjari-text-{name}"}
    service.eyes_of = lambda tag: {"vision": True, "separable": True, "eyes_gb": 0.67}
    seen: list[dict] = []
    service._try_and_save = lambda tag, ctx, previous, **more: seen.append({"tag": tag, "ctx": ctx, **more}) or {"ok": True}
    return service, seen


def test_applying_without_saying_on_six_gb_goes_text_only(tmp_path: Path) -> None:
    service, seen = _service(tmp_path, SIX)
    assert service.apply("qwen3.5-4b-q3", 49152)["ok"]
    assert seen[-1]["vision"] is False
    assert seen[-1]["tag"].startswith("sonjari-text-")


def test_saying_pictures_on_is_followed(tmp_path: Path) -> None:
    service, seen = _service(tmp_path, SIX)
    service.apply("qwen3.5-4b-q3", 49152, eyes=True)
    assert seen[-1]["vision"] is True


def test_applying_without_saying_on_a_big_card_keeps_pictures(tmp_path: Path) -> None:
    service, seen = _service(tmp_path, TWENTY_FOUR)
    service.apply("qwen3.5-4b-q3", 49152)
    assert seen[-1]["vision"] is True
