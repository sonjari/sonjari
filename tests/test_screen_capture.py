from __future__ import annotations

import numpy as np
import pytest

from alture_jarvis.screen_capture import TabletScreenCapture, region_is_plausible

SCREEN = (2944, 1840)
# The real preview rectangle read off the tablet: Mimo sizes `tracking` to the
# video, and with the camera shooting portrait that is exactly 9:16.
VIDEO_RECT = (954, 0, 1989, 1840)


def _frame(width: int = 2944, height: int = 1840) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def _capture(region_provider=None, **kwargs) -> TabletScreenCapture:
    return TabletScreenCapture(serial="test:5555", adb_path="adb", region_provider=region_provider, **kwargs)


# ── which rectangles are believable ──────────────────────────────────────────
def test_the_real_preview_rect_is_accepted() -> None:
    assert region_is_plausible(VIDEO_RECT, SCREEN) is True
    left, top, right, bottom = VIDEO_RECT
    assert (right - left) / (bottom - top) == pytest.approx(9 / 16, abs=0.001)


@pytest.mark.parametrize(
    "region,why",
    [
        ((0, 0, 0, 0), "empty"),
        ((100, 100, 110, 900), "a slice of bezel"),
        ((0, 0, 2944, 20), "a status bar strip"),
        ((-50, 0, 900, 900), "off the left edge"),
        ((0, 0, 5000, 1840), "wider than the screen"),
    ],
)
def test_nonsense_rectangles_are_rejected(region, why) -> None:
    # A dump read mid-transition produces these, and cropping to one would hand
    # YOLO a sliver of app chrome while every frame still looks normal.
    assert region_is_plausible(region, SCREEN) is False, why


# ── latest-frame semantics ───────────────────────────────────────────────────
def test_no_frame_yet_reads_false() -> None:
    capture = _capture()
    ok, frame = capture.read()
    assert ok is False and frame is None


def test_a_frame_is_served_once() -> None:
    # Handing the same frame back repeatedly would let a dead capture look like
    # a slow one, and the caller's stall detection -- the thing that gets vision
    # back -- would never fire.
    capture = _capture()
    capture._latest = _frame()
    capture._latest_seq = 1

    ok, first = capture.read()
    assert ok is True and first is not None
    assert capture.read() == (False, None)

    capture._latest_seq = 2
    ok, _ = capture.read()
    assert ok is True, "a newer frame must be served"


# ── cropping ─────────────────────────────────────────────────────────────────
def test_the_frame_is_cropped_to_the_preview() -> None:
    capture = _capture(region_provider=lambda: VIDEO_RECT)
    cropped = capture._crop(_frame())
    assert cropped.shape[:2] == (1840, 1035)


def test_without_a_provider_the_whole_screen_is_used() -> None:
    capture = _capture()
    assert capture._crop(_frame()).shape[:2] == (1840, 2944)


def test_an_implausible_rect_is_ignored_rather_than_cropped_to() -> None:
    capture = _capture(region_provider=lambda: (0, 0, 2944, 20))
    assert capture._crop(_frame()).shape[:2] == (1840, 2944)


def test_the_last_good_rect_survives_a_failed_dump() -> None:
    # Mimo mid-animation, the tablet briefly busy: a failed read is not a reason
    # to start feeding the detector the mode strip and the joystick.
    calls = {"n": 0}

    def flaky() -> tuple[int, int, int, int] | None:
        calls["n"] += 1
        if calls["n"] == 1:
            return VIDEO_RECT
        raise RuntimeError("ui_dump_failed")

    capture = _capture(region_provider=flaky, region_refresh_sec=0.0)
    assert capture._crop(_frame()).shape[:2] == (1840, 1035)
    assert capture._crop(_frame()).shape[:2] == (1840, 1035), "lost the rect on a failed dump"


def test_the_rect_is_not_re_read_on_every_frame() -> None:
    # At ~18 fps a dump per frame would saturate adb; measured, dumps and
    # screenrecord already contend (12/12 successes became 8/12).
    calls = {"n": 0}

    def counting() -> tuple[int, int, int, int]:
        calls["n"] += 1
        return VIDEO_RECT

    capture = _capture(region_provider=counting, region_refresh_sec=60.0)
    for _ in range(20):
        capture._crop(_frame())
    assert calls["n"] == 1


def test_a_rect_bigger_than_the_frame_is_clamped() -> None:
    # The tablet can rotate between the dump and the frame.
    capture = _capture(region_provider=lambda: VIDEO_RECT)
    cropped = capture._crop(_frame(1472, 920))
    assert cropped.shape[1] == 1472 - 954
    assert cropped.shape[0] == 920


# ── plumbing ─────────────────────────────────────────────────────────────────
def test_it_quacks_like_a_videocapture() -> None:
    # VisionService._capture_loop drives this without knowing which source it
    # got, so the cv2 surface it uses has to exist.
    capture = _capture()
    assert capture.isOpened() is False
    assert capture.set(1, 2) is False
    capture.release()


def test_the_command_streams_h264_to_stdout() -> None:
    command = _capture()._command()
    assert command[:4] == ["adb", "-s", "test:5555", "exec-out"]
    assert "screenrecord" in command
    assert "--output-format=h264" in command
    assert command[-1] == "-"


def test_restarting_cleans_up_the_tablet_side_process(monkeypatch) -> None:
    # Killing the local adb client leaves screenrecord running on the tablet,
    # where it holds the encoder and starves the next one -- which shows up as
    # "no frames" and reads like the capture never worked.
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "alture_jarvis.screen_capture.subprocess.run",
        lambda command, **_: calls.append(command),
    )
    capture = _capture()
    capture._kill_remote_screenrecord()
    assert calls == [["adb", "-s", "test:5555", "shell", "killall", "-INT", "screenrecord"]]


def test_cleanup_survives_an_unreachable_tablet(monkeypatch) -> None:
    def boom(*_, **__):
        raise OSError("device offline")

    monkeypatch.setattr("alture_jarvis.screen_capture.subprocess.run", boom)
    _capture()._kill_remote_screenrecord()  # must not raise


def test_opening_without_adb_says_so(monkeypatch) -> None:
    # platform-tools ships as a zip with no installer, so a machine that has
    # never had it set up hits this. Say which piece is missing rather than
    # timing out waiting for frames that were never going to arrive.
    monkeypatch.setattr("alture_jarvis.screen_capture.default_adb_path", lambda: "")
    capture = TabletScreenCapture(serial="test:5555")
    with pytest.raises(RuntimeError, match="adb_not_found"):
        capture.open()


# ── 기기가 없을 때 헛돌지 않는다 ──────────────────────────────────────────────
#
# 2026-08-09: 태블릿이 사무실에 없어 adb 가 비어 있었는데, 캡처는 0.3 초마다 계속
# 다시 붙었다. 초당 세 번이고, 그때마다 PyAV 가 트레이스백을 찍어
# `outputs/jarvis.stderr.log` 가 186MB · 465만 줄이 됐다. 잡음은 원인대로 고쳤지만
# (`_ForwardOnlyStream`) 헛도는 것 자체를 줄여야 다음 잡음도 안 곱해진다.
#
# 지키는 것 둘: 프레임을 받다 끊긴 것은 **여전히 즉시** 다시 붙고(3분마다 오는
# 정상 재시작이다), 한 번도 못 받은 것이 이어질 때만 물러선다.

def test_a_stream_that_produced_frames_reconnects_immediately() -> None:
    from alture_jarvis.screen_capture import RESTART_GAP_SEC, TabletScreenCapture

    assert TabletScreenCapture._retry_gap(0) == RESTART_GAP_SEC


def test_an_absent_device_backs_off_instead_of_hammering() -> None:
    from alture_jarvis.screen_capture import MAX_RETRY_GAP_SEC, TabletScreenCapture

    gaps = [TabletScreenCapture._retry_gap(n) for n in range(1, 12)]
    assert gaps == sorted(gaps), "물러서는 폭이 줄었다"
    assert gaps[0] > TabletScreenCapture._retry_gap(0)
    assert gaps[-1] == MAX_RETRY_GAP_SEC, "무한정 늘어나면 기기가 돌아와도 안 잡는다"
    assert max(gaps) <= MAX_RETRY_GAP_SEC
