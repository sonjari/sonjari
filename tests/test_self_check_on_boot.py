"""켤 때 스스로 점검한다 — 엔진(Ollama 설치)과 모델 (2026-09-18).

노트북 온텔릭은 서버는 켜지고 목록도 답하는데 모델을 하나도 못 올렸다. 점검 도구(self_care)는 있었지만 사람이
「너 괜찮아?」라고 물을 때만 돌았고, 모델 검사는 Ollama 가 보낸 이유(`llama-server binary not found`)를 버리고
「토큰이 안 나왔다」만 말했다. 그 말을 믿고 누를 버튼은 「모델 다시 올리기」였는데, 그건 헛수고였다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.self_care import HEALERS, SelfCare


class _Installer:
    def __init__(self, **status: Any) -> None:
        self.state = {"running": True, "version": "0.34.1", "install_root": "C:/Users/u/Ontelic/engine/ollama",
                      "runner_missing": False, "bundled": "x", "install": {"phase": "idle"}, **status}
        self.repaired = 0

    def status(self) -> dict[str, Any]:
        return dict(self.state)

    def repair(self) -> dict[str, Any]:
        self.repaired += 1
        self.state.update(runner_missing=False, running=True, install={"phase": "ready"})
        return {"ok": True, "phase": "starting", "stopped": 1}


def _care(tmp_path: Path, installer: _Installer | None) -> SelfCare:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    return SelfCare(config, EventBus(), installer=(lambda: installer) if installer else None)


def test_a_half_installed_engine_is_down_and_names_the_right_button(tmp_path: Path) -> None:
    care = _care(tmp_path, _Installer(runner_missing=True))
    organ = care._check_engine()
    assert organ["state"] == "down" and organ["healer"] == "repair_ollama"
    assert "설치가 덜" in organ["detail"]


def test_a_healthy_engine_is_ok(tmp_path: Path) -> None:
    assert _care(tmp_path, _Installer())._check_engine()["state"] == "ok"


def test_no_installer_means_unknown_not_ok(tmp_path: Path) -> None:
    """「못 봤다」를 「정상」으로 읽지 않는다."""
    assert _care(tmp_path, None)._check_engine()["state"] == "unknown"


def test_inside_a_package_a_folder_in_the_app_private_store_is_a_fault(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_FAKE_PACKAGE_FULL_NAME", "RoboMetaFit.OntelicMsixTest_0.4.0.0_x64__abc")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    care = _care(tmp_path, _Installer())
    care.config.ollama_install_dir = tmp_path / "AppData" / "Local" / "Ontelic" / "data" / "ollama"
    organ = care._check_engine()
    assert organ["state"] == "down" and "ollama_install_dir" in organ["evidence"]["inside_app_private_store"]
    assert organ["healer"] == "", "우리 설정 버그다 — 사람에게 누를 버튼을 주지 않는다"


def test_the_model_check_keeps_ollamas_reason_and_points_at_the_engine(tmp_path: Path, monkeypatch) -> None:
    """★ 노트북 그대로 — 500 과 함께 온 이유를 버리지 않고, 다시 올리기가 아니라 엔진 고치기를 가리킨다."""
    import httpx

    class _Reply:
        content = b"x"

        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data

        def json(self) -> dict[str, Any]:
            return self._data

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def get(self, url: str) -> _Reply:
            return _Reply({"models": []})

        def post(self, url: str, json: dict[str, Any]) -> _Reply:
            return _Reply({"error": "error starting llama-server: llama-server binary not found (checked: ...)"})

    monkeypatch.setattr(httpx, "Client", _Client)
    organ = _care(tmp_path, _Installer())._check_model()
    assert organ["state"] == "down" and organ["healer"] == "repair_ollama"
    assert "llama-server" in organ["evidence"]["error"]


def test_boot_check_records_the_result_and_skips_the_model_before_setup(tmp_path: Path) -> None:
    care = _care(tmp_path, _Installer(runner_missing=True))
    result = care.boot_check(include_model=False)
    assert [organ["organ"] for organ in result["organs"]] == ["engine"], "설정 전에는 모델을 안 본다(겁주지 않게)"
    assert result["down"] == ["engine"] and result["healable"] == ["repair_ollama"]
    assert care.last_boot is result


def test_the_engine_button_repairs_and_then_reads_again(tmp_path: Path) -> None:
    installer = _Installer(runner_missing=True)
    care = _care(tmp_path, installer)
    result = care.heal({"action": "repair_ollama"})
    assert installer.repaired == 1 and result["fixed"] is True and result["after"]["state"] == "ok"


def test_the_engine_button_does_nothing_when_the_engine_is_fine(tmp_path: Path) -> None:
    installer = _Installer()
    result = _care(tmp_path, installer).heal({"action": "repair_ollama"})
    assert result["ran"] is False and installer.repaired == 0, "멀쩡한 것을 고치면 그것이 곧 고장이다"


def test_only_known_buttons_exist() -> None:
    assert HEALERS["repair_ollama"] == "engine"
    with pytest.raises(ValueError):
        SelfCare(JarvisConfig(), EventBus()).heal({"action": "rm_rf"})


def test_the_runtime_runs_it_on_boot_and_the_screen_can_read_it() -> None:
    import inspect

    from alture_jarvis import api, runtime

    source = inspect.getsource(runtime.JarvisRuntime.start)
    assert "_boot_self_check" in source
    api_source = inspect.getsource(api)
    assert '"/v1/self-check"' in api_source and '"/v1/self-check/heal"' in api_source
    ui = (Path(__file__).resolve().parents[1] / "ui" / "src" / "WorkspaceApp.tsx").read_text(encoding="utf-8")
    assert "<HealthBar" in ui


# ── 속도는 그 PC 의 평소와 견준다 (2026-09-18 오후) ──────────────────────────
#
# 노트북(RTX 5050 Laptop)에서 9B 가 15~20 tok/s 인 것은 그 하드웨어의 정상인데, 절대 기준 30 으로 재서
# 「너무 느립니다」 빨간 줄이 떴고 다시 올려도 안 사라졌다. 고장 표본(3090 사고 2.3)만 보고 기준을 정한 탓이다.
# 그래서 여기서는 **좋은 표본과 나쁜 표본을 둘 다** 넣는다.


def _speed_care(tmp_path: Path, monkeypatch, *, now_tps: float, usual_tps: float | None,
                selected_model: str | None = None, vram: int = 5 * 1024**3) -> dict[str, Any]:
    import httpx

    from alture_jarvis.model_setup import write_selection

    care = _care(tmp_path, _Installer())
    model = care.config.ollama_model
    if usual_tps is not None:
        write_selection(care.config.data_dir, {
            "chat_model": selected_model or model, "num_ctx": care.config.ollama_num_ctx,
            "verified": {"tokens_per_sec": usual_tps},
        })
    seen: dict[str, Any] = {}

    class _Reply:
        content = b"x"

        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data

        def json(self) -> dict[str, Any]:
            return self._data

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def get(self, url: str) -> _Reply:
            return _Reply({"models": [{"size_vram": vram, "context_length": 32768}]})

        def post(self, url: str, json: dict[str, Any]) -> _Reply:
            seen["body"] = json
            return _Reply({"response": "1, 2, 3", "eval_count": 64, "eval_duration": int(64 / now_tps * 1e9)})

    monkeypatch.setattr(httpx, "Client", _Client)
    organ = care._check_model()
    organ["_body"] = seen.get("body")
    return organ


def test_a_slow_but_normal_laptop_is_ok(tmp_path: Path, monkeypatch) -> None:
    """★ 좋은 표본 — 노트북 그대로. 평소 20, 지금 18 이면 정상이다."""
    organ = _speed_care(tmp_path, monkeypatch, now_tps=18.0, usual_tps=20.0)
    assert organ["state"] == "ok", organ["detail"]


def test_the_3090_accident_is_still_caught_against_the_usual_speed(tmp_path: Path, monkeypatch) -> None:
    """나쁜 표본 — 2026-08-20 그대로. 평소 130 에서 2.3 이면 고장이고 다시 올리기를 가리킨다."""
    organ = _speed_care(tmp_path, monkeypatch, now_tps=2.3, usual_tps=130.0)
    assert organ["state"] == "down" and organ["healer"] == "reload_model"
    assert "평소" in organ["detail"] and "기준" not in organ["detail"], "사람에게 절대 기준 숫자를 보이지 않는다"


def test_a_laptop_speed_on_a_3090_pc_is_a_fault(tmp_path: Path, monkeypatch) -> None:
    """평소 130 인 PC 가 18 로 떨어지면 — 노트북에서는 정상인 숫자라도 **이 PC 에서는** 고장이다."""
    assert _speed_care(tmp_path, monkeypatch, now_tps=18.0, usual_tps=130.0)["state"] == "down"


def test_without_a_usual_speed_only_the_unusable_floor_applies(tmp_path: Path, monkeypatch) -> None:
    assert _speed_care(tmp_path / "a", monkeypatch, now_tps=18.0, usual_tps=None)["state"] == "ok"
    down = _speed_care(tmp_path / "b", monkeypatch, now_tps=3.0, usual_tps=None)
    assert down["state"] == "down" and "쓸 수 없을 만큼" in down["detail"]


def test_a_usual_speed_of_another_model_is_not_used(tmp_path: Path, monkeypatch) -> None:
    """다른 모델의 평소로 지금을 재면 그것이 곧 오탐이다 — 바닥만 본다."""
    organ = _speed_care(tmp_path, monkeypatch, now_tps=18.0, usual_tps=130.0, selected_model="some-other-model")
    assert organ["state"] == "ok" and organ["evidence"]["usual_tok_per_sec"] is None


def test_the_check_measures_the_same_way_as_applying_a_model(tmp_path: Path, monkeypatch) -> None:
    """평소 값(적용 때 micro_bench)과 견주려면 **같은 방법**으로 재야 한다 — 두 벌이면 갈린다."""
    body = _speed_care(tmp_path, monkeypatch, now_tps=20.0, usual_tps=20.0)["_body"]
    assert body["options"]["num_predict"] == 64 and "30까지" in body["prompt"]


def test_cpu_fallback_is_still_down_even_when_fast_enough(tmp_path: Path, monkeypatch) -> None:
    organ = _speed_care(tmp_path, monkeypatch, now_tps=20.0, usual_tps=20.0, vram=0)
    assert organ["state"] == "down" and "GPU" in organ["detail"]


def test_bars_above_the_header_get_their_own_grid_row() -> None:
    """점검 줄이 머리(70px) 행을 차지해 아래가 한 칸씩 밀리고 두 줄 안내가 잘렸다(2026-09-18). 파일럿 줄만 규칙이 있었다."""
    css = (Path(__file__).resolve().parents[1] / "ui" / "src" / "workspace.css").read_text(encoding="utf-8")
    assert ".workspace-main:has(> :is(.update-bar, .pilot-auth-bar))" in css
