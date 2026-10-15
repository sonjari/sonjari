from __future__ import annotations

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.mimo_control import MimoTools
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway


class FakeController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.foregrounded = 0

    def ensure_foreground(self, **_: object) -> dict:
        self.foregrounded += 1
        return {"ok": True}

    def pan(self, direction: str, *, seconds: float = 1.0, deflection: float = 0.8) -> dict:
        self.calls.append(("pan", {"direction": direction, "seconds": seconds}))
        return {"ok": True, "direction": direction, "seconds": seconds}

    def recenter(self) -> dict:
        self.calls.append(("recenter", {}))
        return {"ok": True, "control": "gimbal_recenter"}

    def start_live(self) -> dict:
        self.calls.append(("start_live", {}))
        return {"ok": True}

    def stop_live(self) -> dict:
        self.calls.append(("stop_live", {}))
        return {"ok": True}


def _tools(enabled: bool = True) -> tuple[MimoTools, FakeController]:
    controller = FakeController()
    config = JarvisConfig(camera_control_enabled=enabled)
    return MimoTools(config, controller), controller  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "spoken,expected",
    [("왼쪽", "left"), ("오른쪽", "right"), ("위", "up"), ("아래", "down"), ("LEFT", "left")],
)
def test_korean_direction_words_reach_the_gimbal(spoken: str, expected: str) -> None:
    # The model is prompted in Korean, so "왼쪽 봐줘" has to land on pan("left")
    # without the model needing to translate first.
    tools, controller = _tools()
    tools.look({"direction": spoken})
    assert controller.calls == [("pan", {"direction": expected, "seconds": 1.0})]


def test_look_wakes_the_tablet_before_moving() -> None:
    tools, controller = _tools()
    tools.look({"direction": "왼쪽"})
    assert controller.foregrounded == 1


def test_unknown_direction_is_rejected_rather_than_guessed() -> None:
    tools, controller = _tools()
    with pytest.raises(ValueError, match="unknown_direction"):
        tools.look({"direction": "대각선"})
    assert controller.calls == []


def test_seconds_is_passed_through() -> None:
    tools, controller = _tools()
    tools.look({"direction": "right", "seconds": 2.5})
    assert controller.calls[0][1]["seconds"] == 2.5


def test_tools_are_hidden_from_the_model_when_disabled() -> None:
    # A tool the model can see but that cannot run produces confident answers
    # about actions that never happened.
    enabled, _ = _tools(enabled=True)
    disabled, _ = _tools(enabled=False)
    assert "camera_look" in enabled.names
    assert disabled.names == set()
    assert disabled.ollama_tools == []


def test_registration_risk_levels(tmp_path) -> None:
    gateway = ToolGateway(JobStore(tmp_path / "jobs.db"), EventBus())
    tools, _ = _tools()
    tools.register(gateway)
    by_name = {row["name"]: row for row in gateway.list_tools()}

    # Moving a camera in our own office is undone by recentering, so it runs
    # directly. An approval popup on every "왼쪽 봐줘" would defeat asking by
    # voice at all.
    assert by_name["camera_look"]["risk_level"] == RiskLevel.L1.label()
    assert by_name["camera_status"]["risk_level"] == RiskLevel.L0.label()
    assert by_name["camera_start_live"]["risk_level"] == RiskLevel.L1.label()


def test_disabled_tools_register_but_do_not_execute(tmp_path) -> None:
    gateway = ToolGateway(JobStore(tmp_path / "jobs.db"), EventBus())
    tools, controller = _tools(enabled=False)
    tools.register(gateway)

    result = gateway.execute("camera_look", {"direction": "왼쪽"})
    assert result.ok is False
    assert result.status == "disabled"
    assert controller.calls == []


def test_execute_through_the_gateway_moves_the_gimbal(tmp_path) -> None:
    gateway = ToolGateway(JobStore(tmp_path / "jobs.db"), EventBus())
    tools, controller = _tools()
    tools.register(gateway)

    result = gateway.execute("camera_look", {"direction": "아래", "seconds": 0.5})
    assert result.ok is True
    assert controller.calls == [("pan", {"direction": "down", "seconds": 0.5})]


def test_status_names_which_half_is_missing() -> None:
    class OfflineBridge:
        def status(self) -> dict:
            return {"ok": True, "connected": False, "devices": []}

    tools, controller = _tools()
    controller.bridge = OfflineBridge()  # type: ignore[attr-defined]
    report = tools.status({})
    # "카메라를 못 찾음" when the tablet is simply offline sends the next person
    # to the wrong device.
    assert report["tablet"]["connected"] is False
    assert report["mimo"] is None


def _screen_capture_tools() -> tuple[MimoTools, FakeController]:
    controller = FakeController()
    config = JarvisConfig(camera_control_enabled=True, camera_screen_capture_enabled=True)
    return MimoTools(config, controller), controller  # type: ignore[arg-type]


def test_starting_live_is_refused_while_watching_the_screen() -> None:
    # Starting a stream is how JARVIS goes blind now: Mimo swaps the camera view
    # for a status page, and the capture carries on cropping timers and
    # reporting an empty room. Nothing about that looks like a failure, so it
    # must not be reachable by asking for it.
    tools, controller = _screen_capture_tools()
    with pytest.raises(ValueError, match="live_would_blind_vision"):
        tools.start_live({})
    assert controller.calls == []


def test_stopping_live_stays_available() -> None:
    # The reverse is harmless and occasionally needed -- a stream left running
    # from before the switch is exactly what should be stoppable.
    tools, controller = _screen_capture_tools()
    tools.stop_live({})
    assert controller.calls == [("stop_live", {})]


def test_starting_live_still_works_on_the_rtmp_path() -> None:
    tools, controller = _tools()
    tools.start_live({})
    assert controller.calls == [("start_live", {})]
