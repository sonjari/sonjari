from __future__ import annotations

import time

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.mimo_control import MimoController
from alture_jarvis.android_bridge import parse_ui_dump

LIVE_RUNNING_DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.TextView" resource-id="mimo.sz:id/live_stream_duration"
        content-desc="" text="00:00:43" clickable="false" enabled="true" bounds="[1400,630][1500,680]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/living_stream_title"
        content-desc="" text="라이브 진행 중..." clickable="false" enabled="true" bounds="[1400,760][1550,810]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/stop_live_stream"
        content-desc="" text="라이브 종료" clickable="true" enabled="true" bounds="[1400,1730][1550,1780]"/>
  <node class="android.widget.ImageView" resource-id="mimo.sz:id/fpv_shutter"
        content-desc="" text="" clickable="true" enabled="true" bounds="[2740,860][2860,980]"/>
</hierarchy>"""


class FakeBridge:
    def __init__(self, dump: str) -> None:
        self._dump = dump
        self.taps: list[tuple[int, int]] = []

    def ui_dump(self, **_: object):
        return parse_ui_dump(self._dump)

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def wake(self) -> None:
        pass

    def current_app(self) -> str:
        return "mimo.sz"

    def launch(self, package: str) -> None:
        pass

    def is_installed(self, package: str) -> bool:
        return True

    def screen_size(self) -> tuple[int, int]:
        return (1840, 2944)


def _config(tmp_path, **overrides) -> JarvisConfig:
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
        **overrides,
    )


def test_live_status_is_read_from_the_screen() -> None:
    controller = MimoController(FakeBridge(LIVE_RUNNING_DUMP), settle_sec=0.0)  # type: ignore[arg-type]
    status = controller.live_status()
    assert status["running"] is True
    assert status["duration"] == "00:00:43"


def test_stop_live_uses_the_stop_button_not_the_shutter() -> None:
    # During a live session the shutter toggles SD-card recording. Using it to
    # "stop the stream" leaves the stream up and quietly fills the card.
    bridge = FakeBridge(LIVE_RUNNING_DUMP)
    controller = MimoController(bridge, settle_sec=0.0)  # type: ignore[arg-type]
    controller.stop_live()
    assert bridge.taps == [(1475, 1755)]  # stop_live_stream, not fpv_shutter


def test_ensure_live_does_not_restart_a_healthy_stream() -> None:
    # The recovery loop calls this on a timer; walking the wizard again would
    # tear down a stream that was working fine.
    bridge = FakeBridge(LIVE_RUNNING_DUMP)
    controller = MimoController(bridge, settle_sec=0.0)  # type: ignore[arg-type]
    result = controller.ensure_live()
    assert result["action"] == "already_running"
    assert bridge.taps == []


CAMERA_VIEW_WHILE_LIVE = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.TextView" resource-id="mimo.sz:id/fpv_text"
        content-desc="" text="라이브" clickable="true" enabled="true" bounds="[2870,470][2940,520]"/>
</hierarchy>"""


class SwitchingBridge(FakeBridge):
    """Camera view first, live session screen once 라이브 is tapped."""

    def __init__(self) -> None:
        super().__init__(CAMERA_VIEW_WHILE_LIVE)

    def tap(self, x: int, y: int) -> None:
        super().tap(x, y)
        self._dump = LIVE_RUNNING_DUMP


def test_ensure_live_opens_the_live_view_before_judging() -> None:
    # A session can be streaming while the visible screen is the ordinary
    # camera view. Treating "the live screen is not showing" as "there is no
    # live" would run the wizard and tear the stream down.
    bridge = SwitchingBridge()
    controller = MimoController(bridge, settle_sec=0.0)  # type: ignore[arg-type]
    result = controller.ensure_live()
    assert result["action"] == "already_running_confirmed"
    # Only the mode tap; the wizard was never entered.
    assert bridge.taps == [(2905, 495)]


def test_recovery_waits_for_the_configured_silence(tmp_path) -> None:
    runtime = create_app(_config(tmp_path, camera_autorecover_after_sec=90.0), start_services=False).state.jarvis
    now = time.time()
    fresh = {"running": True, "source": "stream", "last_frame_at": now - 10}
    stale = {"running": True, "source": "stream", "last_frame_at": now - 200}

    assert runtime._camera_recovery_due(fresh, now) is False
    assert runtime._camera_recovery_due(stale, now) is True


def test_recovery_ignores_a_usb_camera(tmp_path) -> None:
    # Restarting a Mimo livestream would do nothing for a USB webcam, and would
    # walk the tablet through a wizard for no reason.
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    now = time.time()
    assert runtime._camera_recovery_due(
        {"running": True, "source": "usb", "last_frame_at": now - 9999}, now
    ) is False


def test_recovery_covers_the_screen_capture_source(tmp_path) -> None:
    # Screen capture goes silent for its own reasons -- the tablet sleeps, adb
    # drops -- and skipping it here would leave that source with no recovery at
    # all, which is how JARVIS ended up blind before.
    runtime = create_app(_config(tmp_path, camera_autorecover_after_sec=90.0), start_services=False).state.jarvis
    now = time.time()
    assert runtime._camera_recovery_due(
        {"running": True, "source": "tablet_screen", "last_frame_at": now - 200}, now
    ) is True
    assert runtime._camera_recovery_due(
        {"running": True, "source": "tablet_screen", "last_frame_at": now - 10}, now
    ) is False


def test_a_missing_tablet_is_not_treated_as_drift(tmp_path) -> None:
    # Out of hours the tablet is simply unreachable. Reading that as "Mimo
    # drifted off the camera view" would send the recovery loop after a device
    # that is not there, every 20 seconds.
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis

    def unreachable() -> bool:
        raise RuntimeError("adb_failed: device offline")

    runtime.camera_control.on_camera_view = unreachable  # type: ignore[method-assign]
    assert runtime._camera_view_drifted() is False


def test_drift_is_detected_when_mimo_leaves_the_camera_view(tmp_path) -> None:
    # The failure screen capture has that the stream never did: frames keep
    # arriving normally while they show a settings page, so no frame-age check
    # can catch it.
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    runtime.camera_control.on_camera_view = lambda **_: False  # type: ignore[method-assign]
    assert runtime._camera_view_drifted() is True


def test_recovery_handles_never_having_received_a_frame(tmp_path) -> None:
    # A relay that was empty from the moment JARVIS started has last_frame_at=0.
    # Treating that as "1970, so infinitely stale" would fire instantly on every
    # boot; ignoring it would mean it never recovers at all.
    runtime = create_app(_config(tmp_path, camera_autorecover_after_sec=90.0), start_services=False).state.jarvis
    runtime._started_at = time.time() - 10
    assert runtime._camera_recovery_due({"running": True, "source": "stream", "last_frame_at": 0}, time.time()) is False

    runtime._started_at = time.time() - 200
    assert runtime._camera_recovery_due({"running": True, "source": "stream", "last_frame_at": 0}, time.time()) is True
