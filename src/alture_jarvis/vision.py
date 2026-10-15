from __future__ import annotations

import base64
import collections
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .config import JarvisConfig
from .events import EventBus


class PresenceTracker:
    def __init__(self, enter_hits: int, enter_window: int, exit_after_sec: float) -> None:
        self.enter_hits = max(1, enter_hits)
        self.history: collections.deque[bool] = collections.deque(maxlen=max(enter_window, enter_hits))
        self.exit_after_sec = max(0.1, exit_after_sec)
        self.present = False
        self.last_seen = 0.0

    def update(self, detected: bool, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        self.history.append(bool(detected))
        if detected:
            self.last_seen = now
        if not self.present and sum(self.history) >= self.enter_hits:
            self.present = True
            return "entered"
        if self.present and not detected and now - self.last_seen >= self.exit_after_sec:
            self.present = False
            self.history.clear()
            return "left"
        return None


class VisionService:
    """Latest-frame camera capture with independently throttled YOLO inference."""

    def __init__(
        self,
        config: JarvisConfig,
        events: EventBus,
        *,
        screen_region_provider: Callable[[], tuple[int, int, int, int] | None] | None = None,
    ) -> None:
        self.config = config
        self.events = events
        # Supplied by the runtime when the picture comes off the tablet screen:
        # it asks Mimo where the preview sits so the capture can crop to it.
        # A plain callable rather than the controller itself -- vision has no
        # business knowing what Mimo is.
        self.screen_region_provider = screen_region_provider
        # Set once the inference thread has loaded it, so on-demand detection
        # (detect_people) can share it instead of putting a second copy on the
        # GPU.
        self._model: Any = None
        self._stop = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._inference_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._latest_frame: Any = None
        self._frame_sequence = 0
        self._last_frame_at = 0.0
        self._last_detection: dict[str, Any] = {"person_present": False, "people": 0}
        self._status: dict[str, Any] = {
            "running": False,
            "ready": False,
            "capture_ready": False,
            "inference_ready": False,
        }

    def dependency_status(self) -> dict[str, Any]:
        if not self.config.vision_enabled:
            return {"ok": False, "enabled": False}
        try:
            import cv2  # noqa: F401
            import ultralytics  # noqa: F401

            return {"ok": True, "enabled": True}
        except ImportError as exc:
            return {"ok": False, "enabled": True, "error": f"dependency_missing:{exc.name}"}

    def start(self) -> None:
        if not self.config.camera_enabled or not self.config.vision_enabled:
            self._status = {"running": False, "ready": False, "disabled": True}
            return
        if self._capture_thread and self._capture_thread.is_alive():
            return
        self._stop.clear()
        with self._lock:
            self._status = {
                "running": True,
                "ready": False,
                "capture_ready": False,
                "inference_ready": False,
                "error": "",
                **self._source_label(),
            }
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="jarvis-camera-capture", daemon=True
        )
        self._inference_thread = threading.Thread(
            target=self._inference_loop, name="jarvis-yolo-inference", daemon=True
        )
        self._capture_thread.start()
        self._inference_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        for thread in (self._capture_thread, self._inference_thread):
            if thread:
                thread.join(timeout=timeout)
        with self._lock:
            self._status["running"] = False
            self._status["ready"] = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._status,
                **self._last_detection,
                "frame_sequence": self._frame_sequence,
                "last_frame_at": self._last_frame_at,
            }

    def latest_jpeg_with_metadata(self) -> tuple[bytes, int, float]:
        with self._lock:
            frame = self._latest_frame
            frame_sequence = self._frame_sequence
            captured_at = self._last_frame_at
        if frame is None:
            return b"", frame_sequence, captured_at
        import cv2

        encoded_ok, encoded = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85]
        )
        return (encoded.tobytes() if encoded_ok else b""), frame_sequence, captured_at

    def latest_jpeg(self) -> bytes:
        frame, _, _ = self.latest_jpeg_with_metadata()
        return frame

    def latest_frame(self) -> tuple[Any, int]:
        """The newest frame as pixels, with the sequence number it arrived on.

        The sequence is what lets a caller tell "the picture after I moved the
        gimbal" from "the picture I was already looking at" -- a sweep that
        scans the frame it had before panning reports on the wrong direction
        and never notices.
        """
        with self._lock:
            return self._latest_frame, self._frame_sequence

    def wait_for_frame_after(self, sequence: int, timeout: float = 5.0) -> tuple[Any, int]:
        """Block until a frame newer than `sequence` arrives."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._frame_sequence <= sequence and not self._stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            return self._latest_frame, self._frame_sequence

    def detect_people(self, frame: Any) -> list[tuple[int, int, int, int]]:
        """Person boxes in one specific frame, using the already-loaded model.

        Separate from the background inference loop because a sweep has to know
        what was in the frame it just captured, not what the room looked like
        whenever the 1fps loop last ran. Shares the model rather than loading a
        second copy onto the GPU.
        """
        model = self._model
        if model is None or frame is None:
            return []
        results = model.predict(
            frame,
            classes=[0],
            conf=0.35,
            imgsz=self.config.vision_imgsz,
            device=self.config.vision_device,
            verbose=False,
        )
        if not results or getattr(results[0], "boxes", None) is None:
            return []
        boxes: list[tuple[int, int, int, int]] = []
        for row in results[0].boxes.xyxy.tolist():
            left, top, right, bottom = (int(round(value)) for value in row[:4])
            boxes.append((left, top, right, bottom))
        return boxes

    def snapshot(self, output: Path) -> Path:
        frame = self.latest_jpeg()
        if not frame:
            raise RuntimeError("camera_frame_unavailable")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(frame)
        return output

    def latest_base64(self) -> str:
        frame = self.latest_jpeg()
        return base64.b64encode(frame).decode("ascii") if frame else ""

    def latest_base64_with_metadata(self) -> dict[str, Any]:
        frame, frame_sequence, captured_at = self.latest_jpeg_with_metadata()
        return {
            "image": base64.b64encode(frame).decode("ascii") if frame else "",
            "frame_id": frame_sequence,
            "captured_at": captured_at,
        }

    def _stream_ffmpeg_options(self, stream_url: str) -> str:
        """I/O timeouts for the capture, in OpenCV's "key;value|key;value" form.

        Without a timeout, opening a stream whose publisher is absent -- the
        tablet carrying the camera walked out of Wi-Fi range -- blocks inside
        FFmpeg indefinitely and wedges this thread, so the retry loop below
        never gets to run and vision never comes back on its own.

        The option names differ per protocol: RTSP wants `timeout` on the
        demuxer, while RTMP and other URL-based inputs want `rw_timeout`.
        Passing the wrong one is not harmless, so pick by scheme.
        """
        override = self.config.camera_stream_ffmpeg_options.strip()
        if override:
            return override
        micros = int(max(1.0, self.config.camera_stream_read_timeout_sec) * 1_000_000)
        if stream_url.lower().startswith("rtsp://"):
            return f"rtsp_transport;tcp|timeout;{micros}"
        return f"rw_timeout;{micros}"

    def _source_kind(self) -> str:
        """Which of the three capture sources is configured.

        Screen capture wins over a stream URL when both are set: the URL is
        normally left in place from the RTMP era, and silently preferring it
        would put Mimo back into the livestream mode that hides the gimbal.
        """
        if self.config.camera_screen_capture_enabled:
            return "tablet_screen"
        if self.config.camera_stream_url.strip():
            return "stream"
        return "usb"

    def _open_capture(self, cv2: Any) -> Any:
        """Open the configured source: tablet screen, network stream, or USB."""
        kind = self._source_kind()
        if kind == "tablet_screen":
            from .screen_capture import TabletScreenCapture

            capture = TabletScreenCapture(
                serial=self.config.camera_control_adb_serial,
                region_provider=self.screen_region_provider,
                start_timeout_sec=max(1.0, self.config.camera_stream_read_timeout_sec),
            )
            capture.open()
            return capture
        stream_url = self.config.camera_stream_url.strip()
        if kind == "stream":
            # Read by the FFmpeg backend when the capture is constructed.
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = self._stream_ffmpeg_options(stream_url)
            # FFmpeg is the only backend that speaks rtsp/rtmp. Frame size and
            # rate belong to the sender here, so only the 1-frame buffer is set
            # -- without it OpenCV hands back a growing backlog of stale frames
            # and presence detection reacts to a room minutes out of date.
            capture = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not capture.isOpened():
                raise RuntimeError("camera_stream_open_failed")
            return capture
        backend = cv2.CAP_MSMF if self.config.camera_backend.lower() == "msmf" else cv2.CAP_ANY
        capture = cv2.VideoCapture(self.config.camera_index, backend)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera_height)
        capture.set(cv2.CAP_PROP_FPS, self.config.camera_fps)
        if not capture.isOpened():
            raise RuntimeError("pocket3_camera_open_failed")
        return capture

    def _source_label(self) -> dict[str, Any]:
        kind = self._source_kind()
        if kind == "tablet_screen":
            return {"source": "tablet_screen", "serial": self.config.camera_control_adb_serial}
        if kind == "stream":
            return {"source": "stream", "stream_url": self.config.camera_stream_url.strip()}
        return {"source": "usb", "camera_index": self.config.camera_index}

    def _capture_loop(self) -> None:
        import cv2

        # Both remote sources go quiet rather than erroring when they die, so
        # they share the deadline below; only USB fails by returning errors.
        stream_mode = self._source_kind() in ("stream", "tablet_screen")
        # A stalled network stream keeps returning "no frame" instead of
        # erroring, so a wall-clock deadline is what actually detects it. USB
        # keeps the original consecutive-failure count -- that is how it fails.
        read_timeout = max(1.0, self.config.camera_stream_read_timeout_sec)
        if self._source_kind() == "tablet_screen":
            # screenrecord stops itself every 3 minutes, so the screen source
            # restarts on its own and is briefly frameless by design. At the
            # 12s used for a stream, this loop declared it dead mid-restart and
            # tore the whole capture down to rebuild it -- turning a ~6 second
            # gap into up to 30 seconds of blindness, every three minutes.
            # The outer loop only needs to catch a capture that is really gone.
            read_timeout = max(read_timeout, 45.0)
        retry_wait = max(0.5, self.config.camera_stream_reconnect_sec) if stream_mode else 5.0
        reconnecting = False
        while not self._stop.is_set():
            capture = None
            try:
                capture = self._open_capture(cv2)
                if reconnecting:
                    self.events.publish("vision_reconnected", self._source_label())
                with self._condition:
                    self._status.update({"running": True, "error": "", "reconnecting": False})
                    self._condition.notify_all()

                frame_count = 0
                failed_reads = 0
                last_good_read = time.monotonic()
                fps_window_started = time.monotonic()
                while not self._stop.is_set():
                    ok, frame = capture.read()
                    if not ok:
                        failed_reads += 1
                        if stream_mode:
                            if time.monotonic() - last_good_read >= read_timeout:
                                raise RuntimeError("camera_stream_stalled")
                        elif failed_reads >= 30:
                            raise RuntimeError("camera_stream_lost")
                        self._stop.wait(0.05)
                        continue
                    failed_reads = 0
                    last_good_read = time.monotonic()
                    frame_count += 1
                    now = time.monotonic()
                    with self._condition:
                        self._latest_frame = frame
                        self._frame_sequence += 1
                        self._last_frame_at = time.time()
                        self._status["capture_ready"] = True
                        self._status["ready"] = bool(self._status.get("inference_ready"))
                        if now - fps_window_started >= 2.0:
                            self._status["capture_fps"] = round(frame_count / (now - fps_window_started), 2)
                            frame_count = 0
                            fps_window_started = now
                        self._condition.notify_all()
            except Exception as exc:
                reconnecting = True
                error = f"capture:{exc}"
                with self._condition:
                    previous = str(self._status.get("error") or "")
                    self._status.update({"running": True, "ready": False, "capture_ready": False, "reconnecting": True, "error": error})
                    self._condition.notify_all()
                if previous != error:
                    self.events.publish("vision_error", {"component": "capture", "error": str(exc), "retrying": True})
            finally:
                if capture is not None:
                    capture.release()
            if not self._stop.is_set():
                self._stop.wait(retry_wait)
        with self._condition:
            self._status.update({"running": False, "ready": False, "capture_ready": False})
            self._condition.notify_all()

    def _inference_loop(self) -> None:
        try:
            from ultralytics import YOLO

            model = YOLO(self.config.vision_model)
            self._model = model
            tracker = PresenceTracker(
                self.config.person_enter_hits,
                self.config.person_enter_window,
                self.config.person_exit_after_sec,
            )
            with self._condition:
                while self._latest_frame is None and not self._stop.is_set():
                    self._condition.wait(timeout=0.25)
                self._status["inference_ready"] = not self._stop.is_set()
                self._status["ready"] = bool(
                    self._status.get("capture_ready") and self._status["inference_ready"]
                )

            period = 1.0 / max(0.5, self.config.vision_fps)
            next_inference = time.monotonic()
            inference_count = 0
            fps_window_started = next_inference
            while not self._stop.is_set():
                remaining = next_inference - time.monotonic()
                if remaining > 0 and self._stop.wait(remaining):
                    break
                with self._lock:
                    frame = self._latest_frame
                if frame is None:
                    if self._stop.wait(0.05):
                        break
                    continue

                started = time.monotonic()
                results = model.predict(
                    frame,
                    classes=[0],
                    conf=0.35,
                    imgsz=self.config.vision_imgsz,
                    device=self.config.vision_device,
                    verbose=False,
                )
                finished = time.monotonic()
                next_inference = max(started + period, finished)
                inference_count += 1
                people = 0
                if results and getattr(results[0], "boxes", None) is not None:
                    people = len(results[0].boxes)
                transition = tracker.update(people > 0, finished)
                detection = {
                    "person_present": tracker.present,
                    "people": people,
                    "last_inference_at": time.time(),
                }
                with self._lock:
                    self._last_detection = detection
                    self._status["inference_ms"] = round((finished - started) * 1000, 1)
                    if finished - fps_window_started >= 2.0:
                        self._status["inference_fps"] = round(
                            inference_count / (finished - fps_window_started), 2
                        )
                        inference_count = 0
                        fps_window_started = finished
                if transition:
                    self.events.publish(f"person_{transition}", detection)
        except Exception as exc:
            self._record_error("inference", exc)
        finally:
            with self._lock:
                self._status["inference_ready"] = False
                self._status["ready"] = False

    def _record_error(self, component: str, exc: Exception) -> None:
        error = f"{component}:{exc}"
        with self._condition:
            self._status.update({"running": False, "ready": False, "error": error})
            self._condition.notify_all()
        self._stop.set()
        self.events.publish("vision_error", {"component": component, "error": str(exc)})
