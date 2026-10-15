"""켤 때 본 「엔진 꺼짐」은 화면이 물을 때 다시 본다 (2026-09-29 밤, AWS 첫 실행).

새 PC 에선 켤 때 점검(21:58)이 엔진 설치 **전**에 돌아 「Ollama 가 꺼져 있습니다」가 저장됐다. 마법사가
엔진을 깔고 켠 뒤(21:59:21)에도 점검 줄은 22:07 까지 그대로였다 — 화면이 받는 건 저장된 옛 결과뿐이었다.
"""
from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis.runtime import JarvisRuntime


class FakeCare:
    def __init__(self, engine_now: str) -> None:
        self.last_boot = {"down": ["engine"], "organs": [{"organ": "engine", "state": "down"}], "healthy": False}
        self.engine_now = engine_now
        self.boot_checks: list[bool] = []

    def _safe_probe(self, name: str) -> dict:
        return {"organ": name, "state": self.engine_now}

    def boot_check(self, *, include_model: bool = True, wait: bool = True) -> dict:
        assert wait is False, "화면이 묻는 길은 도는 검사를 기다리지 않는다(15초마다 묻는다)"
        self.boot_checks.append(include_model)
        self.last_boot = {"down": [], "organs": [{"organ": "engine", "state": "ok"}], "healthy": True}
        return self.last_boot


def _runtime(care: FakeCare) -> SimpleNamespace:
    fake = SimpleNamespace(self_care=care)
    fake._setup_completed = lambda: False
    return fake


def test_an_engine_that_came_up_later_clears_the_banner() -> None:
    care = FakeCare(engine_now="ok")
    result = JarvisRuntime.self_check_latest(_runtime(care))
    assert result["healthy"] is True and result["down"] == []
    assert care.boot_checks == [False], "첫 설정 전이면 모델은 안 본다(겁주지 않는다)"


def test_an_engine_still_down_keeps_the_banner_without_a_full_check() -> None:
    care = FakeCare(engine_now="down")
    result = JarvisRuntime.self_check_latest(_runtime(care))
    assert result["down"] == ["engine"]
    assert care.boot_checks == []


def test_a_healthy_result_is_returned_as_is() -> None:
    care = FakeCare(engine_now="ok")
    care.last_boot = {"down": [], "healthy": True}
    assert JarvisRuntime.self_check_latest(_runtime(care)) == {"down": [], "healthy": True}
    assert care.boot_checks == []
