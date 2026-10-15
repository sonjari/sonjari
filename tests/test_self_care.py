"""자비스가 **자기 몸을 살피고 정해진 것만 고친다.**

## 왜 (2026-08-20 밤 실측)

사용자님 음성이 세 시간 죽어 있었다. 자비스는 그 사실을 아는 채로 아무 말도 안
했다 — 장부에 `[WinError 10061]` 이 여섯 번 찍혔지만 화면 답은 멀쩡히 나갔다.
같은 밤 3090 이 빠져 젬마가 CPU 로 내려가 130 → 2.3 tok/s 가 됐을 때도 조용했다.

## 이 파일이 지키는 불변식 셋

**① 고장일 때만 고친다.** 멀쩡한 것을 재시작하면 그것이 곧 고장이다.
**② 고친 뒤 다시 읽는다.** "고쳤다"는 말은 증거가 아니다.
**③ 지어낼 자리가 없다.** 모델은 버튼 이름만 고른다 — 명령을 짜지 못한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.self_care import HEAL_LIMIT_PER_ORGAN, HEALERS, SelfCare


class _Tts:
    def __init__(self, ok: bool = True, enabled: bool = True) -> None:
        self.ok = ok
        self.enabled = enabled
        self.health_calls = 0

    def health(self) -> dict[str, Any]:
        self.health_calls += 1
        if not self.enabled:
            return {"ok": False, "enabled": False}
        if self.ok:
            return {"ok": True, "enabled": True, "voice": "F1"}
        return {"ok": False, "enabled": True, "error": "[WinError 10061] 연결 거부"}


class _Browser:
    def __init__(self, stuck: bool = False) -> None:
        self.stuck = stuck
        self.stopped = 0
        self.started = 0

    def status(self) -> dict[str, Any]:
        return {"enabled": True, "started": True, "stuck": self.stuck, "recoveries": 0}

    def stop(self) -> None:
        self.stopped += 1

    def start(self) -> dict[str, Any]:
        self.started += 1
        self.stuck = False
        return {"started": True}


def _care(tmp_path: Path, **organs: Any) -> SelfCare:
    """검사 대상 기관만 붙인 SelfCare.

    ★ 모델과 GPU 검사는 **진짜 올라마와 nvidia-smi 를 부른다.** 그게 이 도구의
    요점이지만(생존 검사는 실제 왕복으로), 단위 검사가 그것을 타면 검사 한 번에
    2분이 걸린다 — 실제로 그랬다. 여기서는 막아 두고, 진짜 왕복은 라이브에서
    한 번 확인한다.
    """
    config = JarvisConfig(runtime_root=tmp_path)
    care = SelfCare(
        config,
        EventBus(),
        tts=lambda: organs.get("tts"),
        browser=lambda: organs.get("browser"),
        google=lambda: organs.get("google"),
    )
    if "model" not in organs:
        care._check_model = lambda: SelfCare._organ("model", "ok", "(검사에서 막음)", {})  # type: ignore[method-assign]
    if "gpu" not in organs:
        care._check_gpu = lambda: SelfCare._organ("gpu", "ok", "(검사에서 막음)", {})  # type: ignore[method-assign]
    return care


# ── ③ 지어낼 자리가 없다 ────────────────────────────────────────────────────


def test_the_model_can_only_pick_a_button_never_write_a_command(tmp_path: Path) -> None:
    """★ 이 파일의 핵심. 자유로운 터미널을 주지 않는 이유다.

    `self_heal` 의 인자는 `action` 하나이고 그 값은 **enum** 이다. 명령을 짜서
    넣을 자리가 스키마에 없다.
    """
    care = _care(tmp_path)
    spec = next(
        item["function"] for item in care.ollama_tools if item["function"]["name"] == "self_heal"
    )
    props = spec["parameters"]["properties"]
    assert set(props) == {"action"}, "self_heal 이 action 말고 다른 것을 받는다"
    assert sorted(props["action"]["enum"]) == sorted(HEALERS)


def test_an_unknown_button_is_refused(tmp_path: Path) -> None:
    care = _care(tmp_path)
    with pytest.raises(ValueError, match="unknown_action"):
        care.heal({"action": "rm -rf /"})


def test_every_button_names_an_organ_that_can_actually_be_probed(tmp_path: Path) -> None:
    """버튼이 가리키는 기관에 검사가 없으면 「고장일 때만」 규칙이 무너진다."""
    for action, organ in HEALERS.items():
        assert organ in SelfCare._PROBES, f"{action} 이 검사 없는 기관({organ})을 가리킨다"
        assert hasattr(SelfCare, f"_{action}"), f"{action} 의 실제 동작이 없다"


# ── ① 고장일 때만 고친다 ────────────────────────────────────────────────────


def test_a_healthy_organ_is_left_alone(tmp_path: Path) -> None:
    """★ 멀쩡한 것을 재시작하면 그것이 곧 고장이다."""
    browser = _Browser(stuck=False)
    care = _care(tmp_path, browser=browser)
    out = care.heal({"action": "restart_browser"})
    assert out["ran"] is False
    assert "고장이 아닙니다" in out["why"]
    assert browser.stopped == 0, "멀쩡한 브라우저를 껐다"


def test_a_broken_organ_is_healed_and_rechecked(tmp_path: Path) -> None:
    """② 고친 뒤 다시 읽는다 — before/after 가 둘 다 있어야 한다."""
    browser = _Browser(stuck=True)
    care = _care(tmp_path, browser=browser)
    out = care.heal({"action": "restart_browser"})
    assert out["ran"] is True
    assert browser.stopped == 1 and browser.started == 1
    assert out["before"]["state"] == "down"
    assert out["after"]["state"] == "ok"
    assert out["fixed"] is True


def test_a_heal_that_did_not_help_says_so(tmp_path: Path) -> None:
    """★ 안 고쳐졌으면 「고쳤다」고 하면 안 된다."""

    class _StaysStuck(_Browser):
        def start(self) -> dict[str, Any]:
            self.started += 1
            return {"started": False}  # stuck 을 안 푼다

    browser = _StaysStuck(stuck=True)
    care = _care(tmp_path, browser=browser)
    out = care.heal({"action": "restart_browser"})
    assert out["ran"] is True
    assert out["fixed"] is False
    assert out["after"]["state"] == "down"


def test_the_same_organ_is_not_healed_over_and_over(tmp_path: Path) -> None:
    """안 고쳐지는 것을 계속 누르면 복구가 아니라 폭주다."""

    class _NeverFixed(_Browser):
        def start(self) -> dict[str, Any]:
            self.started += 1
            return {}

    browser = _NeverFixed(stuck=True)
    care = _care(tmp_path, browser=browser)
    for _ in range(HEAL_LIMIT_PER_ORGAN):
        assert care.heal({"action": "restart_browser"})["ran"] is True
    blocked = care.heal({"action": "restart_browser"})
    assert blocked["ran"] is False
    assert "사람이 봐야" in blocked["why"]
    assert browser.started == HEAL_LIMIT_PER_ORGAN


# ── 검사가 세 상태를 제대로 가르는가 ─────────────────────────────────────────


def test_a_dead_tts_server_is_down_and_names_its_button(tmp_path: Path) -> None:
    """오늘 밤 그 자리. 자비스가 이걸 말할 수 있어야 했다."""
    care = _care(tmp_path, tts=_Tts(ok=False))
    organ = care.check({"organ": "tts"})["organs"][0]
    assert organ["state"] == "down"
    assert organ["healer"] == "restart_tts"
    assert "10061" in organ["detail"]


def test_tts_turned_off_on_purpose_is_not_a_fault(tmp_path: Path) -> None:
    """설정으로 끈 것과 죽은 것은 다르다."""
    organ = _care(tmp_path, tts=_Tts(enabled=False)).check({"organ": "tts"})["organs"][0]
    assert organ["state"] == "ok"
    assert organ["healer"] == ""


def test_a_missing_module_is_unknown_not_ok(tmp_path: Path) -> None:
    """★ 「못 봤다」를 「정상」으로 세면 조용히 고장난다."""
    organ = _care(tmp_path).check({"organ": "tts"})["organs"][0]
    assert organ["state"] == "unknown", "안 본 것을 정상이라고 했다"


def test_a_probe_that_raises_becomes_unknown_not_ok(tmp_path: Path) -> None:
    class _Explodes:
        def status(self) -> dict[str, Any]:
            raise RuntimeError("boom")

    organ = _care(tmp_path, browser=_Explodes()).check({"organ": "browser"})["organs"][0]
    assert organ["state"] == "unknown"


def test_a_healer_is_only_offered_for_a_real_fault(tmp_path: Path) -> None:
    """멀쩡한 기관에 버튼이 달리면 모델이 그걸 누른다."""
    for organs, name in (({"tts": _Tts(ok=True)}, "tts"), ({"browser": _Browser()}, "browser")):
        organ = _care(tmp_path, **organs).check({"organ": name})["organs"][0]
        assert organ["state"] == "ok"
        assert organ["healer"] == ""


def test_the_summary_names_what_is_broken(tmp_path: Path) -> None:
    """★ 목록만 주면 모델이 「전부 정상입니다」로 뭉갠다 — 요약을 따로 준다."""
    care = _care(tmp_path, tts=_Tts(ok=False), browser=_Browser(stuck=True))
    out = care.check({})
    assert "tts" in out["down"] and "browser" in out["down"]
    assert out["healthy"] is False
    assert set(out["healable"]) >= {"restart_tts", "restart_browser"}
    # 「못 봤다」도 따로 센다. 분모에서 조용히 빠지면 안 된다.
    assert "google" in out["unknown"]


def test_an_unknown_organ_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown_organ"):
        _care(tmp_path).check({"organ": "간"})


def test_checking_changes_nothing(tmp_path: Path) -> None:
    """check 는 읽기만 한다 — 되돌릴 것이 없어야 마음껏 부를 수 있다."""
    browser = _Browser(stuck=True)
    _care(tmp_path, browser=browser).check({})
    assert browser.stopped == 0 and browser.started == 0


# ── 기준선은 재 보고 정한 값인가 ─────────────────────────────────────────────


def test_the_speed_floor_separates_the_two_measured_worlds(tmp_path: Path) -> None:
    """★ 2026-08-20 실측: 정상 117~136 tok/s · 3090 이 빠졌을 때 2.3.

    기준선이 그 사이에 있어야 한다. 2.3 밑이면 고장을 못 잡고, 117 위면 정상을
    고장이라 한다.
    """
    config = JarvisConfig(runtime_root=tmp_path)
    threshold = config.self_check_min_tokens_per_sec
    assert 2.3 < threshold < 117.0
    # ★ 2026-09-18 노트북: 정상이 15~20 tok/s. 바닥은 그 **좋은 표본**보다도 밑이어야 한다.
    assert threshold < 15.0, "느린 정상 PC 를 고장이라 부른다"
    # 평소 대비 비율도 두 세계를 가른다: 3090 사고 2.3/130 ≈ 0.02 · 노트북 흔들림 14.98/20 ≈ 0.75
    assert 2.3 / 130 < config.self_check_min_speed_ratio < 14.98 / 20


def test_google_is_probed_with_a_real_round_trip(tmp_path: Path) -> None:
    """★ 게이트는 **좋은 표본으로도** 역검증해야 한다.

    처음 이 검사를 붙였을 때 멀쩡한 구글 연결을 「끊어졌다」고 말했다.
    `status()` 를 `verify=True` 없이 부르면 `granted_scopes` 가 늘 비어 있는데,
    그 빈 값은 「끊겼다」가 아니라 **「안 물어봤다」**는 뜻이었다.

    실측(2026-08-21): verify 없이 granted 0·email '' / verify=True 로 granted 10.
    """
    seen: dict[str, Any] = {}

    class _Google:
        def status(self, verify: bool = False) -> dict[str, Any]:
            seen["verify"] = verify
            # 진짜 구글 모듈과 같은 모양 — 안 물어보면 빈손이 온다.
            if not verify:
                return {"enabled": True, "connected": True, "granted_scopes": [], "email": ""}
            return {
                "enabled": True, "connected": True, "email": "owner@example.com",
                "granted_scopes": ["a"] * 10, "scope_mismatch": False,
            }

    organ = _care(tmp_path, google=_Google()).check({"organ": "google"})["organs"][0]
    assert seen["verify"] is True, "실제 왕복 없이 물었다 — 빈손을 「끊김」으로 읽는다"
    assert organ["state"] == "ok", "멀쩡한 연결을 고장이라고 했다"


def test_a_genuinely_disconnected_google_is_still_caught(tmp_path: Path) -> None:
    """반대쪽 표본. 오탐을 고치다 진짜 고장을 놓치면 안 된다."""

    class _Gone:
        def status(self, verify: bool = False) -> dict[str, Any]:
            return {"enabled": True, "connected": False, "granted_scopes": [], "email": ""}

    organ = _care(tmp_path, google=_Gone()).check({"organ": "google"})["organs"][0]
    assert organ["state"] == "down"
