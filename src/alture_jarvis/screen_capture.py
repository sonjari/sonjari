"""Watch the tablet's own screen instead of asking the camera to livestream.

Mimo will not drive the gimbal while it is livestreaming. Starting a stream
swaps the camera view for a status page, and the joystick (`right_stick`) and
the gimbal button go with it; BLE is no help either, because a streaming camera
stops advertising. Measured, both of them. That makes "look around until you
find someone" impossible over RTMP: seeing and moving are mutually exclusive.

So JARVIS stops asking for a stream. Mimo stays parked on its ordinary camera
view -- where every control still exists -- and the video comes from capturing
the tablet screen and cropping out the preview. Seeing and moving stop fighting
each other, the round trip drops from RTMP's seconds to about a tenth of one,
and the preview is already in the same coordinate space as the taps we send,
which is what ActiveTrack will need.

The transport is `screenrecord` piped over adb and decoded with PyAV. Measured
against the tablet over wireless adb, at the full 2944x1840:

    screencap raw     0.14 fps   21.7 MB/frame
    screencap -p      1.05 fps    0.4 MB/frame
    screenrecord h264 19.5 fps

`screencap` was the obvious thing to reach for and it is not fast enough to run
a closed loop on -- it barely keeps up with inference alone. Full resolution
costs nothing over half here, and face embedding needs the real pixels, so this
captures at full size and crops.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Callable

from .android_bridge import default_adb_path

# screenrecord stops on its own at this many seconds and cannot be talked out of
# it, so the capture restarts rather than treating the end as a failure.
SCREENRECORD_LIMIT_SEC = 180
# Restart a little early: hitting the limit means the stream is already dead by
# the time we notice, and a planned restart can be timed instead of discovered.
RESTART_MARGIN_SEC = 8.0

# 프레임을 받다가 끊긴 것이면 곧바로 다시 붙는다 — 그 틈은 눈을 감고 있는 시간이고,
# screenrecord 가 제 시간 제한에 걸리는 3분마다 반드시 온다.
RESTART_GAP_SEC = 0.3
# 한 프레임도 못 받고 끝났으면 얘기가 다르다. 태블릿이 아예 없는 것일 수 있고
# (사무실 이전·DHCP 임대 변경·adb 끊김), 그때 0.3초마다 다시 붙는 것은 초당 세 번
# 헛도는 것이다. 2026-08-09 에 이 헛돌기가 PyAV 트레이스백을 곱해 로그를 186MB 로
# 만들었다. 잡음은 원인대로 고쳤지만(_ForwardOnlyStream) 헛도는 것 자체도 값이 있다.
MAX_RETRY_GAP_SEC = 15.0

# A capture area is only believed if it looks like video. A degenerate or
# absurdly letterboxed rectangle means the dump was read mid-transition, and
# cropping to it would quietly hand YOLO a sliver of the screen bezel.
MIN_REGION_PX = 160
MIN_REGION_ASPECT = 0.2
MAX_REGION_ASPECT = 5.0


class _ForwardOnlyStream:
    """파이프를 **못 되감는 것**으로 감싸서 PyAV 에게 넘긴다.

    윈도우 파이프는 자기가 되감기는 줄로 안다. 실측(2026-08-09):

        seekable()  -> True      (거짓말)
        tell()      -> 0
        seek(0, 2)  -> 0         (SEEK_END 도 그냥 0 을 준다)
        seek(-1, 1) -> OSError: [Errno 22] Invalid argument

    PyAV 는 `seek`·`tell` 이 있고 `seekable()` 이 참이면 seek 콜백을 꽂는다
    (`container/pyio.py`). 그래서 h264 디먹서가 프로브 뒤에 뒤로 감으려 할 때마다
    Errno 22 가 나고, PyAV 는 그걸 삼키면서 **트레이스백을 stderr 로 찍는다.**
    프레임마다 반복되니 초당 수십 줄이다.

    실측 피해: `outputs/jarvis.stderr.log` 가 186MB · 465만 줄이 됐고 그중
    455만 줄(98%)이 이 한 종류였다. 브라우저가 죽은 진짜 원인을 찾을 때 이 잡음을
    먼저 걷어내야 했다 — 로그가 이 지경이면 없는 것과 같다.

    고치는 자리는 여기다. `seek`·`tell` 을 아예 노출하지 않으면 PyAV 는 콜백을
    안 꽂고, ffmpeg 는 처음부터 스트림으로 다룬다. 되감기는 원래 못 하는 것이라
    잃는 기능도 없다.
    """

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def read(self, size: int = -1) -> bytes:
        return self._raw.read(size)

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:
            pass


def region_is_plausible(region: tuple[int, int, int, int], screen: tuple[int, int] | None = None) -> bool:
    """Does this rectangle look like a video preview rather than a glitch?"""
    left, top, right, bottom = region
    width, height = right - left, bottom - top
    if width < MIN_REGION_PX or height < MIN_REGION_PX:
        return False
    if left < 0 or top < 0:
        return False
    aspect = width / height
    if not MIN_REGION_ASPECT <= aspect <= MAX_REGION_ASPECT:
        return False
    if screen is not None and (right > screen[0] or bottom > screen[1]):
        return False
    return True


class TabletScreenCapture:
    """A latest-frame video source shaped like `cv2.VideoCapture`.

    Duck-typed rather than subclassed so `VisionService._capture_loop` can drive
    it without knowing which source it got: `isOpened()`, `read()`, `release()`
    and a `set()` that accepts and ignores the buffer/size hints meant for a
    real capture device.

    Frames are decoded on a background thread that keeps only the most recent
    one. Anything else would build the same stale backlog the RTMP path had to
    defend against, and a backlog here means the gimbal is reacting to where
    someone stood several seconds ago.
    """

    def __init__(
        self,
        *,
        serial: str = "",
        adb_path: str = "",
        region_provider: Callable[[], tuple[int, int, int, int] | None] | None = None,
        region_refresh_sec: float = 20.0,
        start_timeout_sec: float = 15.0,
    ) -> None:
        self.adb_path = adb_path or default_adb_path()
        self.serial = serial
        self.region_provider = region_provider
        self.region_refresh_sec = max(1.0, region_refresh_sec)
        self.start_timeout_sec = max(1.0, start_timeout_sec)

        self._lock = threading.Lock()
        self._frame_ready = threading.Event()
        self._stop = threading.Event()
        self._latest: Any = None
        self._latest_seq = 0
        self._taken_seq = 0
        self._error = ""
        self._restarts = 0
        self._region: tuple[int, int, int, int] | None = None
        self._region_checked_at = 0.0
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None

    def _resolve_serial(self, configured: str) -> str:
        """쓸 시리얼을 정한다. 설정값이 살아 있으면 그것, 아니면 붙어 있는 것.

        빈 문자열로 두면 `adb` 가 알아서 고르지만, 기기가 둘 이상 붙어 있으면
        (지금처럼 USB + 무선) `more than one device` 로 죽는다. 그래서 여기서 정한다.
        """
        try:
            from .android_bridge import AndroidBridge

            bridge = AndroidBridge(adb_path=self.adb_path, serial=configured)
            found = bridge._attached_serial()
        except Exception:
            found = ""
        return found or configured

    # ── lifecycle ────────────────────────────────────────────────────────────
    def open(self) -> None:
        if not self.adb_path:
            raise RuntimeError("adb_not_found")
        # ★ **열 때** 시리얼을 다시 정한다 (2026-08-14).
        #
        # 여기는 `adb` 를 직접 부르는 경로라 `AndroidBridge.connect()` 의 탐색을
        # 안 탄다. 그래서 런처에 박혀 있던 `192.168.1.50:5555` 를 그대로 물고
        # `no_frames` 만 반복했다 — 태블릿은 `192.168.1.50` 에 있었고 USB 로도
        # 꽂혀 있었는데도. 화면에는 "카메라가 고장났다"로 보인다.
        #
        # 생성자가 아니라 여기인 이유: 생성은 순수해야 한다(기기를 만지면 안 된다).
        # 그리고 **다시 열 때마다** 다시 정해야 임대 주소가 바뀌어도 따라간다 —
        # 재접속 루프가 매번 이 자리를 지난다.
        self.serial = self._resolve_serial(self.serial)
        self._stop.clear()
        # Cleared so a reopened capture waits for new pixels rather than
        # returning instantly on the flag its previous run left set.
        self._frame_ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="jarvis-tablet-screen", daemon=True
        )
        self._thread.start()
        # Wait for real pixels rather than for the process to spawn: adb happily
        # starts and then fails to reach the tablet, and a source that reports
        # itself open on that basis strands the retry loop one level up.
        if not self._frame_ready.wait(self.start_timeout_sec):
            error = self._error or "no_frames"
            self.release()
            raise RuntimeError(f"tablet_screen_open_failed:{error}")

    def isOpened(self) -> bool:  # noqa: N802 - cv2.VideoCapture's spelling
        return bool(self._thread and self._thread.is_alive())

    def set(self, *_: Any) -> bool:
        """Accept the cv2 property hints; none of them apply to a screen pipe."""
        return False

    def read(self) -> tuple[bool, Any]:
        """Hand back the newest frame, or (False, None) if none is waiting.

        A frame is returned once. Serving the same one repeatedly would let a
        dead capture look like a slow one, and the caller's stall detection --
        the thing that gets vision back -- would never fire.
        """
        with self._lock:
            if self._latest is None or self._latest_seq == self._taken_seq:
                return False, None
            self._taken_seq = self._latest_seq
            return True, self._latest

    def release(self) -> None:
        self._stop.set()
        self._kill_process()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._thread = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "source": "tablet_screen",
                "serial": self.serial,
                "region": list(self._region) if self._region else None,
                "restarts": self._restarts,
                "error": self._error,
                "frames": self._latest_seq,
            }

    # ── capture ──────────────────────────────────────────────────────────────
    def _command(self) -> list[str]:
        command = [self.adb_path]
        if self.serial:
            command += ["-s", self.serial]
        return command + [
            "exec-out",
            "screenrecord",
            "--output-format=h264",
            f"--time-limit={SCREENRECORD_LIMIT_SEC}",
            "-",
        ]

    def _kill_remote_screenrecord(self) -> None:
        """Stop any `screenrecord` still running on the tablet.

        Killing the local adb client does not kill what it started on the
        device: after a restart the old screenrecord sat there in futex_wait
        holding the encoder, and the next one produced no frames at all --
        which surfaces as `tablet_screen_open_failed:no_frames` and looks like
        the capture never worked rather than like a leak. Every restart leaked
        one, so this runs on the way out and again on the way in.

        SIGINT rather than SIGKILL: screenrecord finalises its output on INT,
        and a killed encoder can leave the device unwilling to start another.
        """
        command = [self.adb_path]
        if self.serial:
            command += ["-s", self.serial]
        try:
            subprocess.run(
                command + ["shell", "killall", "-INT", "screenrecord"],
                capture_output=True,
                timeout=10.0,
                check=False,
            )
        except Exception:
            # Nothing to kill, or the tablet is gone -- neither is worth failing
            # a capture over.
            pass

    def _kill_process(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.kill()
            process.wait(timeout=5.0)
        except Exception:
            pass
        self._kill_remote_screenrecord()

    @staticmethod
    def _retry_gap(idle_rounds: int) -> float:
        """다음 시도까지 얼마나 기다릴 것인가.

        프레임을 하나라도 받았으면 `idle_rounds` 는 0 이고, 곧바로 다시 붙는다.
        한 번도 못 받은 것이 이어지면 배로 늘려 15초에서 멈춘다 — 기기가 돌아오면
        늦어도 15초 안에 다시 잡는다는 뜻이고, 그동안 헛돌지는 않는다는 뜻이다.
        """
        if idle_rounds <= 0:
            return RESTART_GAP_SEC
        return min(RESTART_GAP_SEC * (2**idle_rounds), MAX_RETRY_GAP_SEC)

    def _run(self) -> None:
        idle_rounds = 0
        while not self._stop.is_set():
            with self._lock:
                seq_before = self._latest_seq
            try:
                self._stream_once()
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)
            finally:
                self._kill_process()
            if self._stop.is_set():
                break
            with self._lock:
                produced = self._latest_seq > seq_before
                self._restarts += 1
            # 프레임을 받았으면 그 틈은 blindness 이므로 짧게 — screenrecord 가 제
            # 시간 제한에 걸리는 3분마다 반드시 온다. 인코더는 위의 kill 로 이미
            # 놓았으니 기다려서 놓아 줄 것도 없다.
            idle_rounds = 0 if produced else idle_rounds + 1
            self._stop.wait(self._retry_gap(idle_rounds))

    def _stream_once(self) -> None:
        import av

        # A leftover from a previous run -- ours or a crashed session's -- holds
        # the encoder and starves this one silently.
        self._kill_remote_screenrecord()
        process = subprocess.Popen(
            self._command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self._process = process
        deadline = time.monotonic() + SCREENRECORD_LIMIT_SEC - RESTART_MARGIN_SEC
        # Without these PyAV spends about 3.5s probing before the first frame,
        # and that cost is paid again on every restart.
        container = av.open(
            # 날 파이프를 그대로 주면 안 된다 — `_ForwardOnlyStream` 참고.
            _ForwardOnlyStream(process.stdout),
            format="h264",
            mode="r",
            options={"probesize": "32", "analyzeduration": "0", "flags": "low_delay"},
        )
        try:
            for frame in container.decode(video=0):
                if self._stop.is_set() or time.monotonic() >= deadline:
                    break
                image = frame.to_ndarray(format="bgr24")
                cropped = self._crop(image)
                with self._lock:
                    self._latest = cropped
                    self._latest_seq += 1
                    self._error = ""
                self._frame_ready.set()
        finally:
            try:
                container.close()
            except Exception:
                pass

    # ── cropping ─────────────────────────────────────────────────────────────
    def _crop(self, image: Any) -> Any:
        """Trim the screenshot down to Mimo's preview.

        The rectangle is re-read from the running UI, never pinned: on this
        tablet a control moved 51px between two dumps, and a crop at stale
        coordinates hands over a slice of app chrome while every frame still
        looks like it arrived normally.
        """
        region = self._current_region()
        if region is None:
            return image
        height, width = image.shape[:2]
        left, top, right, bottom = region
        left, top = max(0, left), max(0, top)
        right, bottom = min(width, right), min(height, bottom)
        if right - left < MIN_REGION_PX or bottom - top < MIN_REGION_PX:
            return image
        return image[top:bottom, left:right]

    def _current_region(self) -> tuple[int, int, int, int] | None:
        if self.region_provider is None:
            return None
        now = time.monotonic()
        if now - self._region_checked_at < self.region_refresh_sec:
            return self._region
        self._region_checked_at = now
        try:
            found = self.region_provider()
        except Exception:
            # Keep the last good rectangle. A failed dump -- Mimo mid-animation,
            # the tablet briefly busy -- is not a reason to start handing the
            # whole screen to the detector.
            return self._region
        if found is not None and region_is_plausible(found):
            self._region = found
        return self._region
