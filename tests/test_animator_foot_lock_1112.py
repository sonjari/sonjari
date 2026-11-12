"""애니메이터 팩 입히기 — 발 고정(2026-11-12 · 현업 판정: 발 뜸 · 미끄러짐 21→49 · 원본도 41 밀림).

맥스 재현(공개 CMU 02_01 걷기 → 다리 짧은 바이페드 · bench/animator_feet): 붙은 구간 밀림
고치기 전 기본 1.35 → 0.07 · 보폭 0.5 9.5 → 0.00. 맥스 없이 여기서는 만든 스크립트의 **순서와 기본값**을 묶는다.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.animator import library
from alture_jarvis.animator.specs import *  # noqa: F401,F403 — 인자 정의가 있는지만 본다

BIP = Path("C:/x/walk.bip")


def _order(script: str, *marks: str) -> list[int]:
    return [script.index(m) for m in marks]


def test_foot_lock_is_on_by_default_and_runs_last() -> None:
    s = library.apply_script(BIP, "", "t", (0, 84), stride=0.5, arm_spread=35.0, bookend=True)
    spans, fit, book, lock = _order(s, "local footSpans = sjFootSpans", "sjBodyFit com (anim", "(sjBookend com cap", "(sjFootLock com footSpans")
    assert spans < fit < book < lock, "붙은 구간은 보정 전에 찾고, 고정은 보정 · 첫끝 덮기 뒤에"
    assert "sjFootLock com footSpans footP0 0.500" in s, "보폭을 줄였으면 고정 자리도 같은 배율로"


def test_blend_comes_before_span_detection() -> None:
    s = library.apply_script(BIP, "", "t", (0, 84), blend_bip=Path("C:/x/b.bip"), blend=0.5)
    assert s.index("local blendNote = sjBlend") < s.index("local footSpans = sjFootSpans"), "섞은 동작의 발을 지킨다"


def test_foot_lock_can_be_turned_off() -> None:
    s = library.apply_script(BIP, "", "t", (0, 84), foot_lock=False)
    assert "sjFootLock" not in s and "sjFootSpans" not in s


def test_no_biped_planted_key_command() -> None:
    """11-12 맥스 실측: setPlantedKey 가 발을 다시 옮겨 고정 뒤 밀림 0.07 → 3.57 · 뜸 2.3 → 5.7. 다시 넣지 않게."""
    s = library.apply_script(BIP, "", "t", (0, 84))
    assert "biped.setPlantedKey" not in s.replace("「심은 키(setPlantedKey)」", "")


def test_stride_is_off_by_default_but_arm_spread_stays() -> None:
    assert library.PREFS_DEFAULT["body_fit"]["stride"] == 1.0, "11-12 대표 결정: 보폭 보정은 기본에서 끈다"
    assert library.PREFS_DEFAULT["body_fit"]["arm_spread"] == 35.0


def test_tool_schema_has_foot_lock() -> None:
    import alture_jarvis.animator.specs as specs

    text = Path(specs.__file__).read_text(encoding="utf-8")
    assert '"foot_lock": {"type": "boolean"' in text
