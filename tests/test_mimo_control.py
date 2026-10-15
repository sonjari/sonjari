from __future__ import annotations

import json

import pytest

from alture_jarvis.android_bridge import AdbError, parse_ui_dump
from alture_jarvis.mimo_control import MimoController

# Trimmed from the dump taken off the real tablet (mimo.sz on a Lenovo Idea Tab
# Pro, landscape 2944x1840). The mode strip really is a stack of fpv_text nodes
# told apart only by their label.
REAL_DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.ImageView" resource-id="mimo.sz:id/fpv_gimbal_center"
        content-desc="" text="" clickable="true" enabled="true" bounds="[2750,428][2850,528]"/>
  <node class="android.widget.ImageView" resource-id="mimo.sz:id/dji_homebar_gimbal_setting"
        content-desc="" text="" clickable="true" enabled="true" bounds="[2750,1313][2850,1413]"/>
  <node class="android.widget.ImageView" resource-id="mimo.sz:id/fpv_shutter"
        content-desc="" text="" clickable="true" enabled="true" bounds="[2740,860][2860,980]"/>
  <node class="android.widget.ImageView" resource-id="mimo.sz:id/fpv_gimbal_selfie"
        content-desc="" text="" clickable="true" enabled="true" bounds="[2760,20][2840,82]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/fpv_text"
        content-desc="" text="라이브" clickable="true" enabled="true" bounds="[2870,470][2940,520]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/fpv_text"
        content-desc="" text="동영상" clickable="true" enabled="true" bounds="[2870,890][2940,940]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/fpv_text"
        content-desc="" text="타임랩스" clickable="true" enabled="true" bounds="[2870,1352][2940,1402]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/fpv_text"
        content-desc="" text="하이퍼랩스" clickable="true" enabled="true" bounds="[2870,1528][2940,1578]"/>
  <node class="android.widget.ImageView" resource-id="mimo.sz:id/fpv_playback"
        content-desc="" text="" clickable="true" enabled="false" bounds="[2750,1739][2850,1839]"/>
  <node class="android.widget.FrameLayout" resource-id="mimo.sz:id/right_stick"
        content-desc="" text="" clickable="false" enabled="true" bounds="[2481,1528][2691,1738]"/>
  <node class="android.widget.ImageView" resource-id="mimo.sz:id/btn_stick"
        content-desc="" text="" clickable="false" enabled="true" bounds="[2541,1588][2630,1677]"/>
</hierarchy>"""


class FakeBridge:
    """Records what would have been sent, so intent can be asserted offline."""

    def __init__(self, dump: str = REAL_DUMP, size: tuple[int, int] = (1840, 2944)) -> None:
        self._dump = dump
        self._size = size
        self.taps: list[tuple[int, int]] = []
        self.swipes: list[tuple[int, int, int, int, int]] = []
        self.holds: list[tuple[int, int, int, int, float]] = []
        self.launched: list[str] = []
        self.keys: list[str] = []
        self.dumps = 0
        self.woke = 0
        self.foreground = "mimo.sz"

    def ui_dump(self, **_: object):
        self.dumps += 1
        return parse_ui_dump(self._dump)

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipes.append((x1, y1, x2, y2, duration_ms))

    def hold_drag(self, x1: int, y1: int, x2: int, y2: int, seconds: float) -> None:
        self.holds.append((x1, y1, x2, y2, seconds))

    def screen_size(self) -> tuple[int, int]:
        return self._size

    def wake(self) -> None:
        self.woke += 1

    def current_app(self) -> str:
        return self.foreground

    def launch(self, package: str) -> None:
        self.launched.append(package)
        self.foreground = package

    def is_installed(self, package: str) -> bool:
        return package == "mimo.sz"

    def key(self, keycode: str) -> None:
        self.keys.append(keycode)


def _controller(bridge: FakeBridge | None = None) -> tuple[MimoController, FakeBridge]:
    bridge = bridge or FakeBridge()
    return MimoController(bridge, settle_sec=0.0), bridge  # type: ignore[arg-type]


def test_recenter_taps_the_real_gimbal_button() -> None:
    controller, bridge = _controller()
    result = controller.recenter()
    assert result["control"] == "gimbal_recenter"
    assert bridge.taps == [(2800, 478)]


def test_selectors_get_the_package_prefix() -> None:
    controller, _ = _controller()
    assert controller._selector("shutter")["resource_id"] == "mimo.sz:id/fpv_shutter"


def test_mode_is_matched_on_the_exact_label() -> None:
    # "타임랩스" and "하이퍼랩스" both end in "랩스"; substring matching would
    # make one of them silently select the other.
    controller, bridge = _controller()
    controller.select_mode("timelapse")
    assert bridge.taps == [(2905, 1377)]
    bridge.taps.clear()
    controller.select_mode("hyperlapse")
    assert bridge.taps == [(2905, 1553)]


def test_live_mode_is_found() -> None:
    controller, bridge = _controller()
    assert controller.select_mode("live")["label"] == "라이브"
    assert bridge.taps == [(2905, 495)]


def test_available_modes_reflects_the_screen() -> None:
    controller, _ = _controller()
    assert set(controller.available_modes()) == {"live", "video", "timelapse", "hyperlapse"}


def test_unknown_mode_and_direction_are_rejected() -> None:
    controller, _ = _controller()
    with pytest.raises(AdbError):
        controller.select_mode("portrait")
    with pytest.raises(AdbError):
        controller.pan("diagonally")


def test_disabled_control_raises_instead_of_tapping() -> None:
    # A tap on a disabled control succeeds and does nothing, which then reads as
    # "the camera ignored us" and sends the next person down the wrong path.
    controller, bridge = _controller()
    with pytest.raises(AdbError, match="control_disabled"):
        controller._tap_control("playback")
    assert bridge.taps == []


def test_missing_control_raises() -> None:
    controller, bridge = _controller(FakeBridge(dump="<?xml version='1.0'?><hierarchy/>"))
    with pytest.raises(AdbError, match="control_not_on_screen"):
        controller.recenter()
    assert bridge.taps == []


def test_joystick_geometry_is_read_from_the_dump_not_pinned() -> None:
    # The recenter button moved 51px between two dumps on the same tablet, so
    # anything pinned to numbers seen once presses empty screen later.
    controller, _ = _controller()
    assert controller.joystick_geometry() == (2586, 1633, 105)


def test_pan_holds_the_stick_rather_than_flicking_it() -> None:
    controller, bridge = _controller()
    controller.pan("left", seconds=1.5, deflection=0.8)
    assert bridge.swipes == []  # a swipe would only flick it
    assert len(bridge.holds) == 1
    x1, y1, x2, y2, seconds = bridge.holds[0]
    assert (x1, y1) == (2586, 1633)
    assert x2 == 2586 - 84 and y2 == 1633
    assert seconds == 1.5


def test_pan_directions_go_the_right_way() -> None:
    controller, bridge = _controller()
    for direction, axis, check in (
        ("right", 0, lambda a, b: b > a),
        ("left", 0, lambda a, b: b < a),
        ("down", 1, lambda a, b: b > a),
        ("up", 1, lambda a, b: b < a),
    ):
        bridge.holds.clear()
        controller.pan(direction)
        x1, y1, x2, y2, _ = bridge.holds[0]
        start, end = (x1, x2) if axis == 0 else (y1, y2)
        assert check(start, end), direction


def test_pan_clamps_deflection_inside_the_stick() -> None:
    controller, bridge = _controller()
    controller.pan("right", deflection=99.0)
    _, _, x2, _, _ = bridge.holds[0]
    # Never past the stick's own radius, or the gesture leaves the control.
    assert x2 <= 2586 + 105


def test_pan_clamps_duration() -> None:
    controller, bridge = _controller()
    controller.pan("up", seconds=900.0)
    assert bridge.holds[0][4] == 5.0


def test_pan_without_the_camera_says_so() -> None:
    # The joystick only exists while the camera is attached, so this is the
    # difference between "Mimo is open" and "the camera is actually there".
    controller, _ = _controller(FakeBridge(dump="<?xml version='1.0'?><hierarchy/>"))
    with pytest.raises(AdbError, match="joystick_not_on_screen"):
        controller.pan("left")


def test_ensure_foreground_wakes_the_tablet_first() -> None:
    # Taps sent to a blank screen all succeed and do nothing.
    bridge = FakeBridge()
    bridge.foreground = "com.android.launcher"
    controller, _ = _controller(bridge)
    controller.ensure_foreground()
    assert bridge.woke == 1
    assert bridge.launched == ["mimo.sz"]


def test_status_distinguishes_app_running_from_camera_attached() -> None:
    controller, _ = _controller()
    status = controller.status().to_dict()
    assert status["installed"] is True
    assert status["foreground"] is True
    assert status["camera_ready"] is True
    assert "playback" not in status["controls_found"]  # disabled

    bare = MimoController(FakeBridge(dump="<?xml version='1.0'?><hierarchy/>"), settle_sec=0.0)  # type: ignore[arg-type]
    assert bare.status().to_dict()["camera_ready"] is False


def test_backgrounded_mimo_is_reported_as_unreadable_not_as_a_dead_camera() -> None:
    # Mimo keeps streaming after it goes to the background, which it does every
    # time the tablet screen locks. Reporting camera_ready=false there sends
    # whoever is debugging after the camera while frames are arriving fine.
    bridge = FakeBridge()
    bridge.foreground = "com.android.launcher"
    controller = MimoController(bridge, settle_sec=0.0)  # type: ignore[arg-type]
    status = controller.status().to_dict()

    assert status["ui_readable"] is False
    assert status["camera_ready"] is None  # unknown, not false
    assert "backgrounded" in status["note"]


LIVE_SETUP_DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.TextView" resource-id="mimo.sz:id/network_description"
        content-desc="" text="{network}" clickable="false" enabled="true" bounds="[800,250][1000,300]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/rtmp_description"
        content-desc="" text="{rtmp}" clickable="true" enabled="true" bounds="[800,510][2100,570]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/start_live_setting"
        content-desc="" text="라이브 시작" clickable="true" enabled="true" bounds="[1400,1730][1550,1780]"/>
</hierarchy>"""


def _live(network: str, rtmp: str) -> tuple[MimoController, FakeBridge]:
    bridge = FakeBridge(dump=LIVE_SETUP_DUMP.format(network=network, rtmp=rtmp))
    return MimoController(bridge, settle_sec=0.0), bridge  # type: ignore[arg-type]


def test_live_setup_spots_the_untouched_rtmp_placeholder() -> None:
    # Mimo leaves example text in the row when nothing is configured, so an
    # empty field looks filled unless the placeholder is recognised.
    controller, _ = _live("네트워크 선택", "예: rtmp://your streaming.service")
    state = controller.live_setup_state()
    assert state["ready"] is False
    assert set(state["missing"]) == {"camera_network", "rtmp_url"}


def test_live_setup_ready_when_both_are_filled() -> None:
    controller, _ = _live("KT_GiGA_5G_856B", "rtmp://192.168.0.91:1935/live/pocket3")
    assert controller.live_setup_state()["ready"] is True


def test_start_live_refuses_and_names_what_is_missing() -> None:
    # Tapping 라이브 시작 with an empty RTMP field succeeds as a tap and
    # produces no stream, which reads as a broken relay rather than a blank
    # settings page.
    controller, bridge = _live("네트워크 선택", "예: rtmp://your streaming.service")
    with pytest.raises(AdbError, match="live_setup_incomplete"):
        controller.start_live()
    assert bridge.taps == []


def test_start_live_taps_only_when_ready() -> None:
    controller, bridge = _live("KT_GiGA_5G_856B", "rtmp://192.168.0.91:1935/live/pocket3")
    result = controller.start_live()
    assert result["started"]["control"] == "live_start"
    assert (1475, 1755) in bridge.taps


def test_start_live_works_when_the_wizard_is_already_open() -> None:
    # The mode strip only exists on the camera screen. Calling this twice, or
    # after a failed attempt left us on the page, must not blow up.
    controller, _ = _live("KT_GiGA_5G_856B", "rtmp://192.168.0.91:1935/live/pocket3")
    assert controller.open_live_setup()["mode"] == "already_open"


GIMBAL_PANEL = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" resource-id="mimo.sz:id/quick_gimbal_mode_layout"
        content-desc="" text="" clickable="true" enabled="true" bounds="[2490,1330][2590,1400]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/quick_gimbal_mode_content"
        content-desc="" text="{mode}" clickable="false" enabled="true" bounds="[2490,1380][2590,1410]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/gimbal_quick_set_config_content"
        content-desc="" text="느리게" clickable="false" enabled="true" bounds="[2350,1380][2450,1410]"/>
</hierarchy>"""

# Confirmed on the device: the button cycles, it does not set.
GIMBAL_CYCLE = ["FPV", "팔로우", "틸트 잠김"]


class CyclingBridge(FakeBridge):
    def __init__(self, start: str = "FPV") -> None:
        self.index = GIMBAL_CYCLE.index(start)
        super().__init__(GIMBAL_PANEL.format(mode=start))

    def tap(self, x: int, y: int) -> None:
        super().tap(x, y)
        self.index = (self.index + 1) % len(GIMBAL_CYCLE)
        self._dump = GIMBAL_PANEL.format(mode=GIMBAL_CYCLE[self.index])


def test_gimbal_mode_reads_the_label() -> None:
    controller = MimoController(CyclingBridge("팔로우"), settle_sec=0.0)  # type: ignore[arg-type]
    state = controller.gimbal_mode()
    assert state["mode"] == "follow"
    assert state["speed"] == "느리게"


@pytest.mark.parametrize("start", GIMBAL_CYCLE)
@pytest.mark.parametrize("target,expected", [("팔로우", "follow"), ("잠금", "lock"), ("fpv", "fpv")])
def test_set_gimbal_mode_reaches_the_target_from_anywhere(start: str, target: str, expected: str) -> None:
    # There is no setter, only a cycling button, so the label has to be re-read
    # after every tap. A fixed number of taps lands wherever the panel happened
    # to start.
    bridge = CyclingBridge(start)
    controller = MimoController(bridge, settle_sec=0.0)  # type: ignore[arg-type]
    result = controller.set_gimbal_mode(target)
    assert result["mode"] == expected
    assert controller.gimbal_mode()["mode"] == expected
    assert result["taps"] <= len(GIMBAL_CYCLE)


def test_unknown_gimbal_mode_is_rejected() -> None:
    controller = MimoController(CyclingBridge(), settle_sec=0.0)  # type: ignore[arg-type]
    with pytest.raises(AdbError, match="unknown_gimbal_mode"):
        controller.set_gimbal_mode("파노라마")


def test_gimbal_mode_without_the_panel_reports_none() -> None:
    controller = MimoController(FakeBridge(dump="<?xml version='1.0'?><hierarchy/>"), settle_sec=0.0)  # type: ignore[arg-type]
    assert controller.gimbal_mode()["mode"] is None


# ── a dialog covering the screen ─────────────────────────────────────────────
# uiautomator returns the topmost window only, so while a dialog is up the
# screen behind it is simply absent from the dump. Measured on the tablet: the
# gimbal panel dumped 11 nodes and the live wizard 19, neither containing any
# anchor from the camera view underneath.
STOP_CONFIRM_DIALOG = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" resource-id="android:id/content"
        content-desc="" text="" clickable="false" enabled="true" bounds="[900,700][2000,1150]"/>
  <node class="android.widget.TextView" resource-id=""
        content-desc="" text="라이브를 종료할까요?" clickable="false" enabled="true" bounds="[950,760][1950,860]"/>
  <node class="android.widget.Button" resource-id=""
        content-desc="" text="취소" clickable="true" enabled="true" bounds="[1000,1000][1400,1100]"/>
  <node class="android.widget.Button" resource-id=""
        content-desc="" text="확인" clickable="true" enabled="true" bounds="[1500,1000][1900,1100]"/>
</hierarchy>"""

LIVE_RUNNING_DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.TextView" resource-id="mimo.sz:id/living_stream_title"
        content-desc="" text="라이브 중" clickable="false" enabled="true" bounds="[1300,100][1700,160]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/live_stream_duration"
        content-desc="" text="00:12:31" clickable="false" enabled="true" bounds="[1350,200][1650,260]"/>
  <node class="android.widget.Button" resource-id="mimo.sz:id/stop_live_stream"
        content-desc="" text="라이브 종료" clickable="true" enabled="true" bounds="[1300,1600][1700,1700]"/>
</hierarchy>"""


class StoppingBridge(FakeBridge):
    """Live screen -> confirmation dialog -> camera view, as the tablet does."""

    def __init__(self, *, confirm_really_stops: bool = True) -> None:
        super().__init__(LIVE_RUNNING_DUMP)
        self.confirm_really_stops = confirm_really_stops
        self.stage = "live"

    def tap(self, x: int, y: int) -> None:
        super().tap(x, y)
        if self.stage == "live":
            self.stage = "dialog"
            self._dump = STOP_CONFIRM_DIALOG
        elif self.stage == "dialog":
            self.stage = "stopped" if self.confirm_really_stops else "live"
            self._dump = REAL_DUMP if self.confirm_really_stops else LIVE_RUNNING_DUMP


def test_a_dialog_is_not_mistaken_for_a_stopped_stream() -> None:
    # The bug this exists for: stop_live() tapped 라이브 종료, the dialog covered
    # the live screen, and live_status() reported running=False. ensure_live()
    # believing that would have torn down a perfectly good stream.
    controller = MimoController(FakeBridge(STOP_CONFIRM_DIALOG), settle_sec=0.0)  # type: ignore[arg-type]
    status = controller.live_status()
    assert status["running"] is None, "a covered screen is unknown, not stopped"
    assert status["obscured"] is True


def test_ensure_live_refuses_to_act_while_the_screen_is_covered() -> None:
    controller = MimoController(FakeBridge(STOP_CONFIRM_DIALOG), settle_sec=0.0)  # type: ignore[arg-type]
    bridge = controller.bridge
    result = controller.ensure_live()
    assert result["action"] == "unknown_obscured"
    assert result["ok"] is False
    # The point of refusing: no wizard was walked, so nothing was torn down.
    assert bridge.taps == []  # type: ignore[attr-defined]


def test_camera_view_is_not_reported_as_obscured() -> None:
    controller, _ = _controller()
    assert controller.screen_is_obscured() is False
    assert controller.live_status()["running"] is False


def test_stop_live_answers_the_confirmation_dialog() -> None:
    # Tapping 라이브 종료 only raises the dialog; without answering it the
    # stream keeps running while the return value says it stopped.
    bridge = StoppingBridge()
    controller = MimoController(bridge, settle_sec=0.0)  # type: ignore[arg-type]
    result = controller.stop_live()
    assert result["confirmed"]["confirmed"] == "확인"
    assert result["live"]["running"] is False
    assert result["ok"] is True


def test_stop_live_never_taps_cancel() -> None:
    bridge = StoppingBridge()
    controller = MimoController(bridge, settle_sec=0.0)  # type: ignore[arg-type]
    controller.stop_live()
    cancel_centre = (1200, 1050)
    assert cancel_centre not in bridge.taps, "tapped 취소 and would have called it stopped"


def test_stop_live_reports_failure_when_the_stream_survives() -> None:
    # If answering the dialog does not actually end the stream, say so rather
    # than returning ok on the strength of having tapped something.
    bridge = StoppingBridge(confirm_really_stops=False)
    controller = MimoController(bridge, settle_sec=0.0)  # type: ignore[arg-type]
    result = controller.stop_live()
    assert result["ok"] is False
    assert result["live"]["running"] is True


# ── screen reading is cached, not pinned ─────────────────────────────────────
def test_pan_does_not_redump_the_screen_every_time() -> None:
    # A dump costs about 4.5s on this tablet. Paying it per move makes
    # "sweep until you find someone" impossible.
    controller, bridge = _controller()
    controller.pan("left")
    after_first = bridge.dumps
    controller.pan("right")
    controller.pan("left")
    assert bridge.dumps == after_first, "re-read the screen for every pan"


def test_the_cache_expires() -> None:
    controller, bridge = _controller()
    controller.dump_ttl_sec = 0.0
    controller.pan("left")
    before = bridge.dumps
    controller.pan("right")
    assert bridge.dumps > before


def test_tapping_reuses_a_reading_taken_moments_ago() -> None:
    # A dump costs ~4.5s. A sweep's setup taps twice within a second of itself
    # (return to the camera view, then recenter) and used to pay for two.
    controller, bridge = _controller()
    controller.pan("left")
    before = bridge.dumps
    controller.recenter()
    assert bridge.dumps == before


def test_tapping_re_reads_once_the_screen_reading_is_stale() -> None:
    # The `enabled` check is the whole point of _tap_control: a control that
    # went disabled since the reading would otherwise be tapped anyway, which
    # succeeds silently. So the reuse window has to be short.
    from alture_jarvis import mimo_control

    controller, bridge = _controller()
    controller.pan("left")
    before = bridge.dumps
    # Age the cached reading past the tap window.
    controller._dump_at -= mimo_control.TAP_MAX_AGE_SEC + 1
    controller.recenter()
    assert bridge.dumps > before


def test_the_tap_window_is_far_shorter_than_the_reporting_one() -> None:
    from alture_jarvis import mimo_control

    assert mimo_control.TAP_MAX_AGE_SEC < mimo_control.DUMP_TTL_SEC


def test_preview_region_prefers_the_video_rect_over_the_whole_screen() -> None:
    # `tracking` is sized to the video (9:16 here); preview_sf spans the entire
    # screen including the mode strip and the joystick, and cropping to that
    # would hand those to the detector.
    dump = REAL_DUMP.replace(
        "</hierarchy>",
        """  <node class="android.view.View" resource-id="mimo.sz:id/tracking"
        content-desc="" text="" clickable="false" enabled="true" bounds="[954,0][1989,1840]"/>
  <node class="android.view.SurfaceView" resource-id="mimo.sz:id/preview_sf"
        content-desc="" text="" clickable="false" enabled="true" bounds="[0,0][2944,1840]"/>
</hierarchy>""",
    )
    controller = MimoController(FakeBridge(dump), settle_sec=0.0)  # type: ignore[arg-type]
    assert controller.preview_region() == (954, 0, 1989, 1840)


def test_preview_region_falls_back_to_the_surface() -> None:
    dump = REAL_DUMP.replace(
        "</hierarchy>",
        """  <node class="android.view.SurfaceView" resource-id="mimo.sz:id/preview_sf"
        content-desc="" text="" clickable="false" enabled="true" bounds="[0,0][2944,1840]"/>
</hierarchy>""",
    )
    controller = MimoController(FakeBridge(dump), settle_sec=0.0)  # type: ignore[arg-type]
    assert controller.preview_region() == (0, 0, 2944, 1840)


def test_preview_region_is_none_when_mimo_is_showing_something_else() -> None:
    controller = MimoController(FakeBridge(STOP_CONFIRM_DIALOG), settle_sec=0.0)  # type: ignore[arg-type]
    assert controller.preview_region() is None


# ── getting back to the camera view ──────────────────────────────────────────
class BackNavigatingBridge(FakeBridge):
    """A page with a back arrow that ignores KEYCODE_BACK, as Mimo's do."""

    PAGE = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.ImageView" resource-id="mimo.sz:id/page_back"
        content-desc="" text="" clickable="true" enabled="true" bounds="[737,43][869,107]"/>
  <node class="android.widget.TextView" resource-id="mimo.sz:id/tip_title"
        content-desc="" text="라이브 플랫폼 선택" clickable="true" enabled="true" bounds="[820,224][2125,274]"/>
</hierarchy>"""

    def __init__(self) -> None:
        super().__init__(self.PAGE)

    def tap(self, x: int, y: int) -> None:
        super().tap(x, y)
        self._dump = REAL_DUMP


def test_return_to_camera_view_uses_the_arrow_not_the_back_key() -> None:
    # Measured: the live platform picker sat through four KEYCODE_BACKs. The
    # on-screen arrow is what actually leaves the page.
    bridge = BackNavigatingBridge()
    controller = MimoController(bridge, settle_sec=0.0)  # type: ignore[arg-type]
    result = controller.return_to_camera_view()
    assert result["ok"] is True
    assert bridge.taps == [(803, 75)]
    assert bridge.keys == [], "sent a back key to a page that ignores it"


def test_return_to_camera_view_is_a_no_op_when_already_there() -> None:
    controller, bridge = _controller()
    assert controller.return_to_camera_view()["attempts"] == 0
    assert bridge.taps == []


def test_return_to_camera_view_gives_up_loudly() -> None:
    # A camera that never appears must raise, not quietly report success and
    # leave the capture cropping a settings page.
    controller = MimoController(FakeBridge(STOP_CONFIRM_DIALOG), settle_sec=0.0)  # type: ignore[arg-type]
    with pytest.raises(AdbError, match="camera_view_not_reached"):
        controller.return_to_camera_view(attempts=2)


def test_selector_overrides_are_data_not_code(tmp_path) -> None:
    # Mimo will rename something one day; that has to be a data fix.
    override = tmp_path / "selectors.json"
    override.write_text(json.dumps({"gimbal_recenter": {"resource_id": "id/fpv_shutter"}}), encoding="utf-8")
    bridge = FakeBridge()
    controller = MimoController(bridge, selector_overrides=override, settle_sec=0.0)  # type: ignore[arg-type]
    controller.recenter()
    assert bridge.taps == [(2800, 920)]  # the shutter's position
