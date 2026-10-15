"""Drive the Osmo Pocket 3 by operating DJI Mimo on the tablet.

The camera ignores gimbal commands over BLE (verified against the real device:
telemetry streams fine, every motor command shape is ignored with and without an
active livestream). Mimo can obviously drive the gimbal, so JARVIS drives Mimo.

Selectors live in SELECTORS as data, not scattered through the code, and are
overridable from a JSON file. Mimo will ship an update that renames something
eventually; when it does this should be a one-line data edit by whoever reads
`scripts/map_mimo_ui.py` output, not a code change.

Ids below were read off a real Lenovo Idea Tab Pro running mimo.sz. Anything
marked UNVERIFIED was visible in the dump but could not be exercised, because
the camera was flat at 0% and Mimo cannot show its connected UI without it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .android_bridge import AdbError, AndroidBridge, UiNode, find_node
from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

MIMO_PACKAGE = "mimo.sz"

# resource-id suffixes are matched in full; the package prefix is added below so
# a rebranded package only needs MIMO_PACKAGE changed.
SELECTORS: dict[str, dict[str, Any]] = {
    # Confirmed present in a real dump, camera attached.
    "gimbal_recenter": {"resource_id": "id/fpv_gimbal_center"},
    "gimbal_settings": {"resource_id": "id/dji_homebar_gimbal_setting"},
    "gimbal_selfie": {"resource_id": "id/fpv_gimbal_selfie"},
    "shutter": {"resource_id": "id/fpv_shutter"},
    "playback": {"resource_id": "id/fpv_playback"},
    "settings": {"resource_id": "id/dji_homebar_settings"},
    "home": {"resource_id": "id/dji_homebar_home"},
    "focus_switch": {"resource_id": "id/fpv_camera_focus_switch"},
    "liveview_mirror": {"resource_id": "id/fpv_liveview_mirror"},
    # The gimbal joystick. It only exists while the camera is attached, and it
    # reports clickable=false because it handles raw touch itself -- so it is
    # driven by held motion events, never tapped.
    "joystick": {"resource_id": "id/right_stick", "clickable_only": False},
    # Live setup wizard. Live is not "pick the mode and hit the shutter" -- it
    # opens a settings page that has to be filled in first.
    "live_start": {"resource_id": "id/start_live_setting"},
    "live_guide_close": {"resource_id": "id/user_guide_close"},
    # The back arrow on Mimo's inner pages. Needed because those pages ignore
    # KEYCODE_BACK -- the live platform picker sat there through four of them.
    "page_back": {"resource_id": "id/page_back"},
    "live_network_row": {"resource_id": "id/settings_network_container"},
    "live_network_state": {"resource_id": "id/network_description", "clickable_only": False},
    "live_rtmp_url": {"resource_id": "id/rtmp_description", "clickable_only": False},
    # The live session screen, shown once streaming has begun.
    "live_running_title": {"resource_id": "id/living_stream_title", "clickable_only": False},
    "live_duration": {"resource_id": "id/live_stream_duration", "clickable_only": False},
    # The real stop control. NOT the shutter -- during a live session the
    # shutter starts and stops SD-card recording, so using it to "stop the
    # stream" leaves the stream up and quietly fills the card instead.
    "live_stop": {"resource_id": "id/stop_live_stream"},
    # Gimbal quick-settings strip, revealed by tapping gimbal_settings.
    "gimbal_mode_button": {"resource_id": "id/quick_gimbal_mode_layout"},
    "gimbal_mode_label": {"resource_id": "id/quick_gimbal_mode_content", "clickable_only": False},
    "gimbal_speed_label": {"resource_id": "id/gimbal_quick_set_config_content", "clickable_only": False},
    # Where the video actually sits on screen, for capturing the preview.
    # `tracking` is the ActiveTrack overlay, which Mimo sizes to the video
    # itself: with the camera shooting portrait it measured [954,0][1989,1840],
    # exactly 9:16, while preview_sf spans the whole 2944x1840 screen including
    # the black side bars and the control strips. So tracking is the better
    # anchor and preview_sf is the fallback for when it is absent.
    "preview_tracking": {"resource_id": "id/tracking", "clickable_only": False},
    "preview_surface": {"resource_id": "id/preview_sf", "clickable_only": False},
}

# There is no "set mode" control -- the button cycles, so the only way to reach
# a mode is to tap until the label says so. Order confirmed on the device:
# FPV -> 팔로우 -> 틸트 잠김 -> FPV.
GIMBAL_MODE_LABELS = {
    "fpv": "FPV",
    "follow": "팔로우",
    "lock": "틸트 잠김",
}
GIMBAL_MODE_ALIASES = {
    "fpv": "fpv",
    "팔로우": "follow",
    "따라가기": "follow",
    "follow": "follow",
    "잠금": "lock",
    "락": "lock",
    "틸트 잠김": "lock",
    "lock": "lock",
}

# Mimo leaves the placeholder text in the RTMP row when nothing is configured,
# so an empty field looks like a filled one unless this is checked for.
RTMP_PLACEHOLDER_MARKERS = ("your streaming", "예:", "e.g")
NETWORK_UNSET_MARKERS = ("선택", "select", "연결 안", "not connected")

# Answering Mimo's "라이브를 종료할까요?" dialog. Text rather than resource-id
# because the dialog only exists during a livestream and could not be dumped
# while this was written -- a made-up id would look authoritative and match
# nothing. Cancel is checked first and wins: tapping 취소 and then reporting the
# stream as stopped is the failure this is guarding against.
#
# Matched whole, not as substrings. "예" appears inside plenty of Korean words
# ("예약", "예시"), and a substring rule would happily accept one of those as a
# yes button. Dialog buttons carry short exact labels, so exactness costs
# nothing and rules the mistake out.
DIALOG_CONFIRM_LABELS = frozenset({"확인", "종료", "예", "네", "ok", "yes", "라이브 종료"})
DIALOG_CANCEL_LABELS = frozenset({"취소", "cancel", "아니오", "아니요", "no", "닫기"})

# The capture-mode strip down the right edge. Each entry is a `fpv_text` node
# distinguished only by its label, so these are matched by text.
MODE_LABELS = {
    "live": "라이브",
    "photo": "사진",
    "video": "동영상",
    "pano": "파노라마",
    "lowlight": "저조도",
    "slowmo": "슬로 모션",
    "timelapse": "타임랩스",
    "hyperlapse": "하이퍼랩스",
}

DIRECTIONS = {
    "left": (-1, 0),
    "right": (1, 0),
    "up": (0, -1),
    "down": (0, 1),
}

# How long a screen reading may be reused. `uiautomator dump` measured a median
# of 4.5 seconds on this tablet, and pan() used to pay that before every single
# move -- unusable for "sweep until you find someone", where the loop is
# look-move-look. Capturing the screen makes it worse: dumps went from 12/12 to
# 8/12 with screenrecord running, because the two contend.
#
# This is not the coordinate pinning the project forbids. Positions still come
# from the running UI; they are just not re-read several times a second. Every
# action that can move the UI clears the cache below, and the TTL bounds how
# long a change we did not cause -- someone picking the tablet up, the camera
# detaching -- can go unnoticed. Anything that must be current (live state,
# gimbal mode while cycling it) asks for a fresh read explicitly.
DUMP_TTL_SEC = 20.0

# How stale a reading may be when it is about to be tapped. Short enough that
# nothing realistically becomes disabled inside it, long enough that two
# consecutive actions do not each pay for their own 4.5-second dump.
TAP_MAX_AGE_SEC = 3.0


@dataclass(frozen=True, slots=True)
class MimoStatus:
    installed: bool
    foreground: bool
    package: str
    screen: tuple[int, int]
    controls_found: list[str]
    live: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "foreground": self.foreground,
            "package": self.package,
            "screen": list(self.screen),
            "controls_found": self.controls_found,
            "live": self.live,
            # Mimo keeps streaming after it goes to the background, so its UI
            # being unreadable says nothing about the camera. Without this the
            # report reads "camera_ready: false" while frames are arriving
            # normally, and sends whoever is debugging after the wrong thing.
            "ui_readable": self.foreground,
            # A camera-less Mimo still shows its chrome, so "the app is up" is
            # not the same as "the camera is attached".
            "camera_ready": "gimbal_recenter" in self.controls_found if self.foreground else None,
            "note": "" if self.foreground else "Mimo is backgrounded; its UI cannot be read. This does not stop an already-running livestream.",
        }


class MimoController:
    def __init__(
        self,
        bridge: AndroidBridge,
        *,
        package: str = MIMO_PACKAGE,
        selector_overrides: Path | None = None,
        settle_sec: float = 1.2,
        dump_ttl_sec: float = DUMP_TTL_SEC,
    ) -> None:
        self.bridge = bridge
        self.package = package
        self.settle_sec = settle_sec
        self.dump_ttl_sec = max(0.0, dump_ttl_sec)
        self.selectors = {key: dict(value) for key, value in SELECTORS.items()}
        if selector_overrides and selector_overrides.exists():
            loaded = json.loads(selector_overrides.read_text(encoding="utf-8"))
            for key, value in loaded.items():
                self.selectors[key] = dict(value)
        self._dump_cache: list[UiNode] | None = None
        self._dump_at = 0.0

    # ── helpers ──────────────────────────────────────────────────────────────
    def _selector(self, name: str) -> dict[str, str]:
        try:
            raw = self.selectors[name]
        except KeyError as exc:
            raise AdbError(f"unknown_control:{name}") from exc
        resolved = dict(raw)
        rid = resolved.get("resource_id", "")
        if rid.startswith("id/"):
            resolved["resource_id"] = f"{self.package}:{rid}"
        return resolved

    def _nodes(self, *, fresh: bool = False, max_age: float | None = None) -> list[UiNode]:
        """The current screen, reusing a recent reading when one is available.

        Pass `fresh=True` wherever a stale answer would be acted on rather than
        merely reported -- see DUMP_TTL_SEC. `max_age` is the middle ground:
        "recent enough", for callers that need a current reading but would
        otherwise force a second 4.5-second dump seconds after the last one.
        """
        limit = self.dump_ttl_sec if max_age is None else max_age
        if not fresh and self._dump_cache is not None:
            if time.monotonic() - self._dump_at < limit:
                return self._dump_cache
        nodes = self.bridge.ui_dump()
        self._dump_cache = nodes
        self._dump_at = time.monotonic()
        return nodes

    def _invalidate(self) -> None:
        """Forget the cached screen after doing something that can change it."""
        self._dump_cache = None

    def _tap_control(self, name: str) -> dict[str, Any]:
        selector = self._selector(name)
        # Recent, not necessarily new: this checks `enabled` before tapping, and
        # a control that went disabled since the last reading would otherwise be
        # tapped anyway -- which succeeds and does nothing, the exact failure
        # the check exists to prevent. But forcing a dump every time cost 4.5
        # seconds each, and a sweep's setup paid it twice within a second of
        # itself (return_to_camera_view then recenter) for no gain. Three
        # seconds is far shorter than anything that disables a control here.
        nodes = self._nodes(max_age=TAP_MAX_AGE_SEC)
        node = find_node(nodes, **selector)
        if node is None:
            raise AdbError(f"control_not_on_screen:{name}")
        if not node.enabled:
            # Tapping a disabled control succeeds and does nothing, which then
            # looks like the command was delivered and the camera ignored it.
            raise AdbError(f"control_disabled:{name}")
        x, y = node.center
        self.bridge.tap(x, y)
        self._invalidate()
        time.sleep(self.settle_sec)
        return {"ok": True, "control": name, "at": [x, y]}

    # ── app lifecycle ────────────────────────────────────────────────────────
    def ensure_foreground(self, *, timeout_sec: float = 15.0) -> dict[str, Any]:
        """Wake the tablet and bring Mimo up.

        A tablet parked on a charging stand has its screen off, and every tap
        sent to a dark screen is accepted and discarded.
        """
        self.bridge.wake()
        time.sleep(0.6)
        deadline = time.time() + timeout_sec
        if self.bridge.current_app() != self.package:
            self.bridge.launch(self.package)
        while time.time() < deadline:
            if self.bridge.current_app() == self.package:
                time.sleep(self.settle_sec)
                return {"ok": True, "package": self.package}
            time.sleep(1.0)
        raise AdbError(f"mimo_did_not_come_to_front:{self.package}")

    def status(self) -> MimoStatus:
        installed = self.bridge.is_installed(self.package)
        foreground = self.bridge.current_app() == self.package
        try:
            screen = self.bridge.screen_size()
        except AdbError:
            screen = (0, 0)
        found: list[str] = []
        live: dict[str, Any] = {}
        if foreground:
            nodes = self._nodes()
            for name in self.selectors:
                node = find_node(nodes, **self._selector(name))
                if node is not None and node.enabled:
                    found.append(name)
            live = self.live_status()
        return MimoStatus(installed, foreground, self.package, screen, found, live)

    # ── capture modes ────────────────────────────────────────────────────────
    def available_modes(self) -> list[str]:
        nodes = self._nodes()
        labels = {node.text for node in nodes if node.resource_id.endswith("id/fpv_text")}
        return [key for key, label in MODE_LABELS.items() if label in labels]

    def select_mode(self, mode: str) -> dict[str, Any]:
        label = MODE_LABELS.get(mode)
        if label is None:
            raise AdbError(f"unknown_mode:{mode} (known: {', '.join(sorted(MODE_LABELS))})")
        nodes = self._nodes(fresh=True)
        # Match the exact label, not a substring: "타임랩스" is contained in
        # "하이퍼랩스" in neither direction, but "사진" appears inside other
        # strings often enough that substring matching picks the wrong strip.
        node = next(
            (
                n
                for n in nodes
                if n.resource_id.endswith("id/fpv_text") and n.text.strip() == label and n.clickable
            ),
            None,
        )
        if node is None:
            raise AdbError(f"mode_not_on_screen:{mode}")
        x, y = node.center
        self.bridge.tap(x, y)
        self._invalidate()
        time.sleep(self.settle_sec)
        return {"ok": True, "mode": mode, "label": label, "at": [x, y]}

    # ── gimbal ───────────────────────────────────────────────────────────────
    def recenter(self) -> dict[str, Any]:
        return self._tap_control("gimbal_recenter")

    def open_gimbal_settings(self) -> dict[str, Any]:
        """Reveal the quick-settings strip that holds the mode and speed."""
        return self._tap_control("gimbal_settings")

    def gimbal_mode(self, *, fresh: bool = False) -> dict[str, Any]:
        """Current gimbal mode, or None if the strip is not open."""
        label = self._text_of("gimbal_mode_label", fresh=fresh)
        if not label:
            return {"mode": None, "label": "", "speed": ""}
        return {
            # Lowercased before lookup: the on-screen label is "FPV" while the
            # alias key is "fpv", so without this the mode never matches itself
            # and set_gimbal_mode cycles right past the target it is already on.
            "mode": GIMBAL_MODE_ALIASES.get(label.lower(), label),
            "label": label,
            "speed": self._text_of("gimbal_speed_label"),
        }

    def set_gimbal_mode(self, mode: str) -> dict[str, Any]:
        """Cycle the mode button until the label matches.

        Mimo exposes no direct setter, only a cycling button, so the label is
        re-read after every tap. Capped at one full cycle plus one: tapping
        blindly a fixed number of times lands on whatever happens to be next
        when the panel starts somewhere unexpected.
        """
        target = GIMBAL_MODE_ALIASES.get(mode.strip().lower())
        if target is None:
            raise AdbError(f"unknown_gimbal_mode:{mode} (팔로우/잠금/FPV)")
        self.ensure_foreground()
        if not self._text_of("gimbal_mode_label", fresh=True):
            self.open_gimbal_settings()
            time.sleep(1.0)
        # Every reading here is fresh: this loop stops when the label matches,
        # so a stale label means it either stops on the wrong mode or cycles
        # past the right one forever.
        current = self.gimbal_mode(fresh=True)
        if current["mode"] is None:
            raise AdbError("gimbal_mode_panel_not_open (is the camera attached?)")
        taps = 0
        while current["mode"] != target and taps < len(GIMBAL_MODE_LABELS) + 1:
            self._tap_control("gimbal_mode_button")
            taps += 1
            current = self.gimbal_mode(fresh=True)
        if current["mode"] != target:
            raise AdbError(f"gimbal_mode_not_reached:{target} (stuck at {current['label']!r})")
        return {"ok": True, "mode": target, "label": current["label"], "taps": taps}

    def flip(self) -> dict[str, Any]:
        """Swap between front and rear framing (the selfie toggle)."""
        return self._tap_control("gimbal_selfie")

    def joystick_geometry(self) -> tuple[int, int, int]:
        """Centre and usable radius of Mimo's on-screen gimbal stick.

        Read from the UI rather than pinned to the numbers seen once: the
        control strip shifts (the recenter button moved 51px between two dumps
        on this same tablet), and a stick driven at stale coordinates presses
        empty screen while every command still reports success.

        The reading may be up to DUMP_TTL_SEC old, because a dump costs about
        4.5 seconds here and paying that before every move makes sweeping for
        someone impossible. The stick does not move while the camera view is
        up, and anything that leaves that view clears the cache.
        """
        node = find_node(self._nodes(), **self._selector("joystick"))
        if node is None:
            raise AdbError("joystick_not_on_screen (is the camera attached?)")
        left, top, right, bottom = node.bounds
        cx, cy = (left + right) // 2, (top + bottom) // 2
        radius = min(right - left, bottom - top) // 2
        return cx, cy, radius

    # ── preview geometry ─────────────────────────────────────────────────────
    def on_camera_view(self, *, fresh: bool = False) -> bool:
        """Is Mimo showing the camera, with the gimbal controls available?

        The joystick is the test rather than the preview: a preview surface
        exists on several of Mimo's pages, but `right_stick` only exists where
        the gimbal can actually be driven.
        """
        return find_node(self._nodes(fresh=fresh), **self._selector("joystick")) is not None

    def return_to_camera_view(self, *, attempts: int = 4) -> dict[str, Any]:
        """Back out of whatever page Mimo is on until the camera view is up.

        Mimo's inner pages swallow KEYCODE_BACK -- the live platform picker
        sits there and ignores it however many times it is sent -- so the
        on-screen `page_back` arrow is tried first and the key is only the
        fallback for screens that have no arrow.
        """
        self.ensure_foreground()
        for attempt in range(attempts):
            if self.on_camera_view(fresh=True):
                return {"ok": True, "attempts": attempt}
            arrow = find_node(self._nodes(), **self._selector("page_back"))
            if arrow is not None:
                self.bridge.tap(*arrow.center)
            else:
                self.bridge.key("KEYCODE_BACK")
            self._invalidate()
            time.sleep(max(self.settle_sec, 1.5))
        if self.on_camera_view(fresh=True):
            return {"ok": True, "attempts": attempts}
        raise AdbError("camera_view_not_reached (is the camera attached?)")

    def preview_region(self) -> tuple[int, int, int, int] | None:
        """Where the camera picture sits on the tablet screen.

        Used to crop the screen capture down to the video. Read from the live
        dump on every call rather than pinned, for the same reason the joystick
        is: this tablet moved a control 51px between two dumps, and a crop at
        stale coordinates feeds the detector app chrome while every frame still
        arrives looking perfectly normal.

        Returns None when neither anchor is on screen -- Mimo backgrounded, the
        camera detached, the live wizard open. The caller keeps its last good
        rectangle rather than falling back to the full screen, which would put
        the mode strip and the joystick in front of the detector.
        """
        nodes = self._nodes()
        for name in ("preview_tracking", "preview_surface"):
            node = find_node(nodes, **self._selector(name))
            if node is None:
                continue
            left, top, right, bottom = node.bounds
            if right - left > 0 and bottom - top > 0:
                return (left, top, right, bottom)
        return None

    def pan(
        self,
        direction: str,
        *,
        seconds: float = 1.0,
        deflection: float = 0.8,
    ) -> dict[str, Any]:
        """Hold Mimo's gimbal stick in `direction` for `seconds`.

        Measured against the live preview, a held motion event swings the gimbal
        roughly 1.6x as far as an equivalent `swipe` (41.6 vs 25.4 mean pixel
        change, against an idle noise floor of 1.0) -- `swipe` presses, slides
        and releases, while a real joystick wants the stick kept over.

        `seconds` is how long the stick is held, not an angle: Mimo publishes no
        angle readout, so any figure in degrees here would be invented.
        """
        vector = DIRECTIONS.get(direction)
        if vector is None:
            raise AdbError(f"unknown_direction:{direction} (known: {', '.join(DIRECTIONS)})")
        deflection = max(0.15, min(1.0, deflection))
        seconds = max(0.1, min(5.0, seconds))
        cx, cy, radius = self.joystick_geometry()
        offset = int(radius * deflection)
        tx, ty = cx + vector[0] * offset, cy + vector[1] * offset

        self.bridge.hold_drag(cx, cy, tx, ty, seconds)
        time.sleep(self.settle_sec)
        return {
            "ok": True,
            "direction": direction,
            "seconds": seconds,
            "deflection": deflection,
            "stick": [cx, cy],
            "held_at": [tx, ty],
            "note": "held joystick; Mimo exposes no angle readout, so this is a duration not an angle",
        }

    # ── livestream ───────────────────────────────────────────────────────────
    def _text_of(self, name: str, *, fresh: bool = False) -> str:
        node = find_node(self._nodes(fresh=fresh), **self._selector(name))
        return node.text.strip() if node else ""

    def live_setup_state(self) -> dict[str, Any]:
        """What the live settings page is still missing.

        Both blockers are credentials -- a Wi-Fi password for the camera and an
        RTMP URL carrying a stream password -- so they are reported, never
        filled in from here.
        """
        rtmp = self._text_of("live_rtmp_url", fresh=True)
        network = self._text_of("live_network_state")
        rtmp_set = bool(rtmp) and not any(m in rtmp.lower() for m in RTMP_PLACEHOLDER_MARKERS)
        network_set = bool(network) and not any(m in network.lower() for m in NETWORK_UNSET_MARKERS)
        missing = []
        if not network_set:
            missing.append("camera_network")
        if not rtmp_set:
            missing.append("rtmp_url")
        return {
            "on_setup_page": bool(rtmp or network),
            "rtmp_text": rtmp,
            "network_text": network,
            "ready": not missing,
            "missing": missing,
        }

    def open_live_setup(self) -> dict[str, Any]:
        """Get as far as the live settings page and report what it needs."""
        self.ensure_foreground()
        # The mode strip only exists on the camera screen. Once the wizard is
        # open there is nothing to select, so calling this twice -- or after a
        # failed attempt left us on the page -- must not blow up.
        already = self.live_setup_state()
        mode: dict[str, Any] | str = "already_open"
        if not already["on_setup_page"]:
            mode = self.select_mode("live")
            time.sleep(2.0)
        # Mimo drops a "how to connect Wi-Fi manually" guide over the page; it
        # covers the controls, so it has to go before anything can be read.
        guide = find_node(self._nodes(), **self._selector("live_guide_close"))
        if guide is not None:
            x, y = guide.center
            self.bridge.tap(x, y)
            self._invalidate()
            time.sleep(1.5)
        return {"ok": True, "mode": mode, "setup": self.live_setup_state()}

    def start_live(self) -> dict[str, Any]:
        """Start the RTMP session, once the page has what it needs.

        Live is a settings page, not the shutter: it wants the camera joined to
        a Wi-Fi network and an RTMP URL. Tapping 라이브 시작 without those
        succeeds as a tap and silently produces no stream, so the state is
        checked first and the missing piece is named.
        """
        opened = self.open_live_setup()
        state = opened["setup"]
        if not state["ready"]:
            raise AdbError(
                "live_setup_incomplete:" + ",".join(state["missing"])
                + f" (network={state['network_text']!r} rtmp={state['rtmp_text']!r})"
            )
        started = self._tap_control("live_start")
        return {"ok": True, **opened, "started": started}

    def screen_is_obscured(self, nodes: list[UiNode] | None = None) -> bool:
        """Is a dialog or popup covering the screen we are trying to read?

        `uiautomator dump` returns the topmost window only, not the activity
        underneath: with Mimo's gimbal panel open the whole dump was 11 nodes,
        and with the live wizard up it was 19. Every anchor belonging to the
        screen behind it simply is not there.

        That is why "no 라이브 종료 button" cannot be read as "no livestream" --
        which is exactly what went wrong before: stop_live() tapped 라이브 종료,
        the "라이브를 종료할까요?" dialog appeared, live_status() could no longer
        see the live screen behind it and reported the stream as stopped.
        """
        nodes = self._nodes() if nodes is None else nodes
        for name in ("joystick", "gimbal_recenter", "shutter", "live_stop", "live_running_title"):
            if find_node(nodes, **self._selector(name)) is not None:
                return False
        # The capture-mode strip means the camera view is up even when the
        # gimbal controls are missing because no camera is attached.
        return not any(node.resource_id.endswith("id/fpv_text") for node in nodes)

    def live_status(self, *, fresh: bool = True) -> dict[str, Any]:
        """Is a live session running right now, and for how long?

        Read from the session screen rather than remembered, because the
        session can end without us: the camera drops off Wi-Fi, Mimo is killed,
        the tablet reboots. Anything cached here would keep claiming a stream
        that stopped hours ago.

        `running` is deliberately tri-state. None means "cannot tell" -- a
        dialog is in the way, or Mimo is backgrounded -- and callers that would
        act on the answer have to treat that as different from False. Collapsing
        the two is what let a confirmation dialog masquerade as a stopped
        stream.
        """
        nodes = self._nodes(fresh=fresh)
        title = find_node(nodes, **self._selector("live_running_title"))
        duration = find_node(nodes, **self._selector("live_duration"))
        stop = find_node(nodes, **self._selector("live_stop"))
        running: bool | None = bool(stop) or bool(title and "라이브" in title.text)
        obscured = False
        if not running and self.screen_is_obscured(nodes):
            running, obscured = None, True
        return {
            "running": running,
            "obscured": obscured,
            "duration": duration.text.strip() if duration else "",
            "title": title.text.strip() if title else "",
        }

    def _confirm_dialog(self) -> dict[str, Any] | None:
        """Answer a yes/no dialog affirmatively, if one is up.

        Matched by button text rather than by id: the dialog could not be
        exercised while writing this (it only exists during a livestream), so
        inventing an id would be guessing. The affirmative labels are listed
        explicitly and the cancel labels are excluded, because the failure mode
        here is tapping 취소 and reporting the stream as stopped.
        """
        nodes = self._nodes(fresh=True)
        if not self.screen_is_obscured(nodes):
            return None
        for node in sorted(nodes, key=lambda n: n.area or 1 << 30):
            label = node.text.strip()
            folded = label.lower()
            if not label or not node.clickable or not node.enabled:
                continue
            if folded in DIALOG_CANCEL_LABELS:
                continue
            if folded in DIALOG_CONFIRM_LABELS:
                x, y = node.center
                self.bridge.tap(x, y)
                self._invalidate()
                time.sleep(max(self.settle_sec, 1.5))
                return {"confirmed": label, "at": [x, y]}
        return None

    def stop_live(self) -> dict[str, Any]:
        """End the livestream, including the confirmation Mimo asks for.

        Tapping 라이브 종료 only raises "라이브를 종료할까요?"; without answering
        it the stream keeps running while every return value says it stopped.
        So the dialog is answered and the result is then verified rather than
        assumed.
        """
        self.ensure_foreground()
        # "라이브 종료", never the shutter: during a live session the shutter
        # toggles SD-card recording, so tapping it here leaves the stream up and
        # silently starts filling the card.
        tapped = self._tap_control("live_stop")
        confirmed = self._confirm_dialog()
        after = self.live_status()
        return {
            # Honest about the one case we cannot check: if something is still
            # covering the screen, we do not know whether the stream ended.
            "ok": after["running"] is False,
            "stopped": tapped,
            "confirmed": confirmed,
            "live": after,
        }

    def ensure_live(self) -> dict[str, Any]:
        """Start the stream only if it is really not running.

        The Mimo UI is a weak signal here: a session can be streaming happily
        while the visible screen is the ordinary camera view, so "the live
        screen is not showing" does not mean "there is no live". Acting on that
        alone would walk the wizard and tear down a working stream.

        So the live view is opened first and only then judged. The authoritative
        signal for whether video is actually flowing is frame arrival on the
        JARVIS side, which is what decides to call this in the first place.
        """
        self.ensure_foreground()
        status = self.live_status()
        if status["running"]:
            return {"ok": True, "action": "already_running", "live": status}
        if status["running"] is None:
            # Something is covering the screen, so "not streaming" is a guess.
            # Walking the wizard on a guess tears down a working stream, which
            # is worse than doing nothing and being asked again.
            return {"ok": False, "action": "unknown_obscured", "live": status}
        try:
            self.select_mode("live")
            time.sleep(2.5)
        except AdbError:
            # Already off the camera screen -- the wizard or the live view is up.
            pass
        status = self.live_status()
        if status["running"]:
            return {"ok": True, "action": "already_running_confirmed", "live": status}
        if status["running"] is None:
            return {"ok": False, "action": "unknown_obscured", "live": status}
        return {"ok": True, "action": "started", "live": self.start_live()}


# Korean synonyms, because the model is asked in Korean and "왼쪽 봐줘" has to
# reach pan("left") without the model having to know the English word.
DIRECTION_WORDS = {
    "left": "left",
    "왼쪽": "left",
    "좌": "left",
    "right": "right",
    "오른쪽": "right",
    "우": "right",
    "up": "up",
    "위": "up",
    "위쪽": "up",
    "down": "down",
    "아래": "down",
    "아래쪽": "down",
}


class MimoTools:
    """Gimbal control exposed to the model, in the shape the catalog expects."""

    def __init__(self, config: JarvisConfig, controller: MimoController) -> None:
        self.config = config
        self.controller = controller
        self._definitions = self._build_definitions()

    @staticmethod
    def _function(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required or []},
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function(
                "camera_look",
                "사무실 카메라(오즈모 짐벌)를 원하는 방향으로 돌린다. "
                "사용자가 '왼쪽 봐줘', '위쪽 보여줘'처럼 시야를 옮겨달라고 할 때 쓴다.",
                {
                    "direction": {
                        "type": "string",
                        "description": "왼쪽/오른쪽/위/아래 (left/right/up/down)",
                    },
                    "seconds": {
                        "type": "number",
                        "description": "돌리는 시간(초). 조금이면 0.5, 많이면 2.0. 기본 1.0",
                        "minimum": 0.1,
                        "maximum": 5.0,
                    },
                },
                ["direction"],
            ),
            self._function(
                "camera_recenter",
                "사무실 카메라 짐벌을 정면 기본 위치로 되돌린다.",
                {},
            ),
            self._function(
                "camera_gimbal_mode",
                "사무실 카메라의 짐벌 모드를 바꾼다. "
                "팔로우(움직임을 부드럽게 따라감) / 잠금(틸트 고정) / FPV(기울임까지 따라감).",
                {
                    "mode": {
                        "type": "string",
                        "description": "팔로우 / 잠금 / FPV (follow/lock/fpv)",
                    }
                },
                ["mode"],
            ),
            self._function(
                "camera_status",
                "사무실 카메라 제어 상태를 확인한다. 태블릿 연결·Mimo 실행·카메라 부착 여부를 알려준다.",
                {},
            ),
            self._function(
                "camera_start_live",
                "사무실 카메라의 라이브 송출(RTMP)을 시작한다. "
                "⚠ 지금은 탭 화면을 직접 보는 방식이라 이 도구는 쓰지 않는다 — "
                "영상이 안 나온다는 말에 이걸 부르지 말 것. 그럴 땐 camera_status로 상태부터 볼 것.",
                {},
            ),
            self._function(
                "camera_stop_live",
                "사무실 카메라의 라이브 송출을 중지한다.",
                {},
            ),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions) if self.config.camera_control_enabled else []

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self.ollama_tools}

    # ── handlers ─────────────────────────────────────────────────────────────
    def look(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = str(arguments.get("direction", "")).strip().lower()
        direction = DIRECTION_WORDS.get(raw)
        if direction is None:
            raise ValueError(f"unknown_direction:{raw or '(empty)'} (왼쪽/오른쪽/위/아래)")
        seconds = float(arguments.get("seconds") or 1.0)
        self.controller.ensure_foreground()
        return self.controller.pan(direction, seconds=seconds)

    def recenter(self, _: dict[str, Any]) -> dict[str, Any]:
        self.controller.ensure_foreground()
        return self.controller.recenter()

    def gimbal_mode(self, arguments: dict[str, Any]) -> dict[str, Any]:
        mode = str(arguments.get("mode", "")).strip()
        if not mode:
            return self.controller.gimbal_mode()
        return self.controller.set_gimbal_mode(mode)

    def status(self, _: dict[str, Any] | None = None) -> dict[str, Any]:
        bridge = self.controller.bridge.status()
        if not bridge.get("connected"):
            # Say which half is missing. "카메라를 못 찾음" when the tablet is
            # simply offline sends the next person to the wrong device.
            return {"enabled": self.config.camera_control_enabled, "tablet": bridge, "mimo": None}
        mimo = self.controller.status().to_dict()
        if not mimo["ui_readable"]:
            # Bring it forward and look again, rather than reporting a blank.
            # Mimo drops to the background whenever the tablet screen locks,
            # which is most of the time on a charging stand.
            try:
                self.controller.ensure_foreground()
                mimo = self.controller.status().to_dict()
            except AdbError as exc:
                mimo["note"] = f"{mimo['note']} (foregrounding failed: {exc})"
        return {
            "enabled": self.config.camera_control_enabled,
            "tablet": bridge,
            "mimo": mimo,
        }

    def start_live(self, _: dict[str, Any]) -> dict[str, Any]:
        if self.config.camera_screen_capture_enabled:
            # Starting a stream is how JARVIS goes blind now. Mimo replaces the
            # camera view with a status page the moment it streams, so the
            # screen capture would carry on happily -- cropping a page of
            # timers and reporting that nobody is in the room. Nothing about
            # that looks like a failure from the outside, which is exactly why
            # it must not be reachable by asking.
            raise ValueError(
                "live_would_blind_vision: 지금은 탭 화면을 보고 있어서 라이브를 켜면 "
                "카메라 화면이 사라져 시야를 잃습니다. 정말 송출이 필요하면 "
                "JARVIS_CAMERA_SCREEN_CAPTURE=false 로 바꾸고 재시작해야 합니다."
            )
        return self.controller.start_live()

    def stop_live(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.controller.stop_live()

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "camera_look": self.look,
            "camera_recenter": self.recenter,
            "camera_gimbal_mode": self.gimbal_mode,
            "camera_status": self.status,
            "camera_start_live": self.start_live,
            "camera_stop_live": self.stop_live,
        }
        # L1, not L2: these move a camera in our own office and are trivially
        # undone by recentering, and an approval popup on every "왼쪽 봐줘"
        # would defeat the point of asking by voice. Nothing here leaves the
        # building or destroys anything.
        risks = {
            "camera_look": RiskLevel.L1,
            "camera_recenter": RiskLevel.L1,
            "camera_gimbal_mode": RiskLevel.L1,
            "camera_status": RiskLevel.L0,
            "camera_start_live": RiskLevel.L1,
            "camera_stop_live": RiskLevel.L1,
        }
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    risk_level=risks[name],
                    handler=handlers[name],
                    enabled=self.config.camera_control_enabled,
                )
            )
