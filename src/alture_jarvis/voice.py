from __future__ import annotations

import os
import re
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable

from .config import JarvisConfig


_DLL_HANDLES: list[Any] = []


def _configure_cuda_dll_paths() -> list[str]:
    """Expose venv-scoped CUDA 12 libraries required by CTranslate2 on Windows.

    ★ 같은 경로를 **두 번 넣지 않는다**(2026-08-08).

    예전에는 부를 때마다 `PATH` 앞에 그대로 덧붙였다. 이 함수는 `dependency_status()`
    가 부르고, 그건 `/health` 가 부른다 — 즉 **헬스체크를 부를 때마다 PATH 가 자랐다.**
    윈도우 환경변수 상한은 32767자라 언젠가 반드시 터진다:

        ValueError: the environment variable is longer than 32767 characters

    실제로 터져 있었다. `/health` 가 500 을 돌려주고 있었고(`/`·`/v1/state`·`/v1/tools`
    는 멀쩡했다), 겉으로는 "자비스가 죽었다"로 보였다. 죽은 게 아니라 **헬스체크만**
    죽어 있었고, 그 둘은 워치독에게 같은 얼굴이다(사고 P 의 거울상 — 그때는 죽은 것을
    살았다고 봤고, 이건 산 것을 죽었다고 본다).

    PATH 가 상한에 닿으면 피해가 헬스체크로 끝나지 않는다. 그 뒤로 이 프로세스에서
    환경변수를 건드리는 **모든** 코드가 같은 자리에서 터진다.
    """
    if os.name != "nt":
        return []
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    candidates = [
        nvidia_root / "cuda_runtime" / "bin",
        nvidia_root / "cublas" / "bin",
        nvidia_root / "cudnn" / "bin",
    ]
    existing = [str(path) for path in candidates if path.is_dir()]
    if existing:
        current = os.environ.get("PATH", "")
        already = set(current.split(os.pathsep))
        missing = [path for path in existing if path not in already]
        if missing:
            os.environ["PATH"] = os.pathsep.join(missing + [current])
        if hasattr(os, "add_dll_directory") and not _DLL_HANDLES:
            for path in existing:
                _DLL_HANDLES.append(os.add_dll_directory(path))
    return existing


def _cuda_math_libraries_load() -> bool:
    """ctranslate2 가 그래픽 카드에서 받아쓰는 데 필요한 cuBLAS 를 실제로 올릴 수 있는가.

    GPU 개수(`get_cuda_device_count`)는 드라이버만 있어도 1 이다 — 그것만 보면 라이브러리 없는 포장본이
    「카드 있음」으로 읽혀 매번 실패한다. 그래서 **실제로 올려 본다**(생존 검사는 실제 왕복으로).
    """
    if os.name != "nt":
        return True
    _configure_cuda_dll_paths()
    try:
        import ctypes

        # winmode=0: 표준 검색(PATH 포함) — CUDA 를 시스템에 깐 PC 도 「있음」으로 본다
        ctypes.WinDLL("cublas64_12.dll", winmode=0)
        return True
    except OSError:
        return False


def _looks_like_cuda_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(key in text for key in ("cublas", "cudnn", "cuda", "out of memory"))


class SpeechToText:
    def __init__(self, config: JarvisConfig) -> None:
        self.config = config
        self._model: Any = None
        self._lock = threading.Lock()
        # 설정한 카드가 없어서 다른 데로 내려갔으면 그 사실. 빈 문자열이면 그대로 썼다.
        self._fallback_reason = ""
        self._device_used = ""
        # 그래픽 카드에서 받아쓰다 CUDA 라이브러리로 실패했으면 이 프로세스에선 CPU 로만 간다.
        self._force_cpu_reason = ""

    def dependency_status(self) -> dict[str, Any]:
        if not self.config.voice_enabled:
            return {"ok": False, "enabled": False}
        try:
            dll_paths = _configure_cuda_dll_paths()
            import faster_whisper  # noqa: F401

            status = {
                "ok": True,
                "enabled": True,
                "model_loaded": self._model is not None,
                "cuda_dll_paths": dll_paths,
            }
            if self._device_used:
                status["device"] = self._device_used
            if self._fallback_reason:
                # 화면과 /health 에 그대로 뜬다. 내려간 것을 숨기지 않는다.
                status["fallback"] = self._fallback_reason
            return status
        except ImportError:
            return {"ok": False, "enabled": True, "error": "faster_whisper_not_installed"}

    def _resolve_device(self) -> tuple[str, int, str]:
        """어느 장치에 올릴지 정한다. `(device, index, 내려간 이유)`.

        설정 번호가 실제로 있으면 그대로 쓴다. 없으면 0번, GPU 가 없으면 CPU.
        **내려갔으면 이유를 돌려준다** — 조용히 내려가면 나중에 "왜 느리지"의
        원인을 처음부터 다시 판다.
        """
        device = str(self.config.stt_device or "cpu")
        index = int(self.config.stt_device_index or 0)
        if self._force_cpu_reason:
            return "cpu", 0, self._force_cpu_reason
        if device == "cuda" and not _cuda_math_libraries_load():
            # ★ 2026-09-24 노트북 포장본: 포장이 `nvidia` 폴더(cuBLAS 수백 MB)를 빼서 그래픽 카드 받아쓰기가
            #   매번 `cublas64_12.dll is not found` 로 실패했다. 기본값이 cuda 라 포장본에선 **항상** 실패였다.
            return "cpu", 0, "그래픽 카드용 계산 라이브러리(cuBLAS)가 없어 CPU 로 받아씁니다"
        if device != "cuda":
            return device, index, ""
        try:
            import ctranslate2

            count = int(ctranslate2.get_cuda_device_count())
        except Exception:  # noqa: BLE001 — 셀 수 없으면 설정을 믿는다
            return device, index, ""
        if count <= 0:
            return "cpu", 0, "CUDA 장치가 하나도 없어 CPU 로 내려갔습니다"
        if index >= count:
            return (
                "cuda",
                0,
                f"cuda:{index} 가 없어 cuda:0 으로 내려갔습니다 (지금 GPU {count}장)",
            )
        return device, index, ""

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                _configure_cuda_dll_paths()
                from faster_whisper import WhisperModel

                device, index, fallback = self._resolve_device()
                self._fallback_reason = fallback
                self._model_used = self._model_for(device)
                if device == "cpu":
                    # CPU 는 int8 이 답이다(float16 은 CPU 에서 안 된다). 스레드는 절반·최대 8 —
                    # 대화 모델·브라우저와 같이 도는 PC 라 전부 뺏지 않는다.
                    self._model = WhisperModel(self._model_used, device="cpu", compute_type="int8",
                                               cpu_threads=max(2, min(8, (os.cpu_count() or 4) // 2)))
                else:
                    self._model = WhisperModel(
                        self._model_used,
                        device=device,
                        device_index=index,
                        compute_type=self.config.stt_compute_type,
                    )
                self._device_used = f"{device}:{index}"
            return self._model

    def _model_for(self, device: str) -> str:
        """CPU 로 받아쓸 때는 작은 모델(`stt_cpu_model`)을 쓴다 (2026-09-24 실측).

        5초 한국어 음성, CPU 6스레드: large-v3-turbo 6.4초 · small 1.5초 · base 0.6초 — 받아쓴 글은 셋 다 맞았다
        (합성 음성 1문장이라 쉬운 표본이다). 사람이 말하고 6초 넘게 기다리면 「너무 느리다」가 된다(노트북 사용자).
        """
        if device == "cpu" and self.config.stt_cpu_model:
            return self.config.stt_cpu_model
        return self.config.stt_model

    def warmup(self) -> dict[str, Any]:
        """Load faster-whisper weights so the first PTT request does not pay the cost."""
        if not self.config.voice_enabled:
            return {"ok": False, "enabled": False}
        started = time.perf_counter()
        self._load()
        result = {
            "ok": True,
            "enabled": True,
            "model": getattr(self, "_model_used", "") or self.config.stt_model,
            # 설정값이 아니라 **실제로 올린 곳**을 적는다. 둘이 갈리는 순간이
            # 있기 때문에(카드를 뽑았을 때) 이 줄이 필요하다.
            "device": self._device_used or f"{self.config.stt_device}:{self.config.stt_device_index}",
            "load_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if self._fallback_reason:
            result["fallback"] = self._fallback_reason
        return result

    def transcribe(self, path: Path) -> dict[str, Any]:
        language = (self.config.stt_language or "").strip().lower()
        language = None if language in ("", "auto") else language
        try:
            model = self._load()
            segments, info = model.transcribe(str(path), language=language, vad_filter=True)
            # 받아쓰기는 글자를 꺼낼 때 돈다 — CUDA 오류도 여기서 난다.
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:  # noqa: BLE001
            if not self._device_used.startswith("cuda") or not _looks_like_cuda_failure(exc):
                raise
            # 그래픽 카드 쪽이 실행 중에 무너졌다(라이브러리·메모리). 이 프로세스는 CPU 로 한 번 더 한다.
            with self._lock:
                self._force_cpu_reason = f"그래픽 카드 받아쓰기가 실패해 CPU 로 바꿨습니다: {str(exc)[:120]}"
                self._model = None
            model = self._load()
            segments, info = model.transcribe(str(path), language=language, vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        return {
            "text": text,
            "language": getattr(info, "language", "ko"),
            "duration": getattr(info, "duration", None),
        }


class PushToTalkRecorder:
    """Records Pocket 3 microphone audio while an API/UI button is held."""

    def __init__(self, config: JarvisConfig) -> None:
        self.config = config
        self._stream: Any = None
        self._frames: list[Any] = []
        self._lock = threading.Lock()
        # 지금 들리는 소리 크기(0~1). 화면이 「내 말을 듣고 있구나」를 그리는 재료다(2026-09-30 대표 요청).
        # 이벤트 버스로 흘리지 않는다 — 초당 수십 번이면 다시 붙은 화면이 받아야 할 이벤트를 고리에서 밀어낸다.
        self._level = 0.0

    def level(self) -> dict[str, Any]:
        """지금 녹음 중인가와 마지막 소리 크기. 녹음이 아니면 0."""
        recording = self._stream is not None
        return {"recording": recording, "level": round(self._level, 3) if recording else 0.0}

    @staticmethod
    def _level_of(indata: Any) -> float:
        """int16 한 덩이의 크기를 0~1 로 — dBFS 를 -60~0 에 펴서 작은 목소리도 보이게."""
        import math

        samples = indata.astype("float32") / 32768.0
        rms = float((samples * samples).mean()) ** 0.5
        if rms <= 1e-6:
            return 0.0
        return max(0.0, min(1.0, (20.0 * math.log10(rms) + 60.0) / 60.0))

    def _device_index(self) -> int | None:
        import sounddevice as sd

        wanted = self.config.microphone_name.lower()
        for index, device in enumerate(sd.query_devices()):
            if wanted in str(device.get("name", "")).lower() and int(device.get("max_input_channels", 0)) > 0:
                return index
        return None

    def start(self) -> dict[str, Any]:
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return {"recording": True, "already_started": True}
            self._frames = []
            self._level = 0.0

            def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
                del frames, time_info, status
                self._frames.append(indata.copy())
                try:
                    self._level = self._level_of(indata)
                except Exception:  # noqa: BLE001 — 크기를 못 재도 녹음은 계속한다
                    pass

            self._stream = sd.InputStream(
                device=self._device_index(),
                channels=1,
                samplerate=self.config.sample_rate,
                dtype="int16",
                callback=callback,
            )
            self._stream.start()
        return {"recording": True}

    def stop(self, output: Path) -> Path:
        with self._lock:
            if self._stream is None:
                raise RuntimeError("not_recording")
            stream = self._stream
            self._stream = None
        stream.stop()
        stream.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        raw = b"".join(frame.tobytes() for frame in self._frames)
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.config.sample_rate)
            wav.writeframes(raw)
        self._frames = []
        return output


class HotkeyBridge:
    """Physical two-press PTT toggle; never acts as an approval channel."""

    _HOTKEY_ID = 0x4A52
    _WM_HOTKEY = 0x0312
    _WM_QUIT = 0x0012
    _MOD_ALT = 0x0001
    _MOD_CONTROL = 0x0002
    _MOD_SHIFT = 0x0004
    _MOD_WIN = 0x0008
    _MOD_NOREPEAT = 0x4000

    def __init__(self, config: JarvisConfig, on_toggle: Callable[[], Any]) -> None:
        self.config = config
        # Start-vs-stop is decided by the runtime state machine, not here. This
        # class used to keep its own `_active` flag, which silently drifted the
        # moment the HUD orb was used for one half of a toggle -- and a failed
        # stop left the flag stuck so every later press tried to stop again.
        self.on_toggle = on_toggle
        self._registered = False
        self._handle: Any = None
        self._lock = threading.Lock()
        self._trigger_count = 0
        self._last_trigger_at: float | None = None
        self._last_action = ""
        self._last_error = ""
        self._backend = ""
        self._native_thread: threading.Thread | None = None
        self._native_thread_id = 0
        self._native_ready = threading.Event()

    def _toggle(self) -> None:
        with self._lock:
            self._trigger_count += 1
            self._last_trigger_at = time.time()
            try:
                self._last_action = str(self.on_toggle().get("action") or "")
                self._last_error = ""
            except Exception as exc:
                self._last_action = ""
                self._last_error = str(exc)[:200]

    @staticmethod
    def _native_supported() -> bool:
        return os.name == "nt"

    @classmethod
    def _parse_windows_hotkey(cls, hotkey: str) -> tuple[int, int]:
        modifiers = cls._MOD_NOREPEAT
        virtual_key: int | None = None
        key_names = {
            "space": 0x20,
            "enter": 0x0D,
            "return": 0x0D,
            "tab": 0x09,
            "escape": 0x1B,
            "esc": 0x1B,
        }
        for raw_part in hotkey.lower().split("+"):
            part = raw_part.strip()
            if part in {"ctrl", "control"}:
                modifiers |= cls._MOD_CONTROL
            elif part == "shift":
                modifiers |= cls._MOD_SHIFT
            elif part == "alt":
                modifiers |= cls._MOD_ALT
            elif part in {"win", "windows", "meta"}:
                modifiers |= cls._MOD_WIN
            elif part in key_names:
                virtual_key = key_names[part]
            elif len(part) == 1 and part.isascii() and part.isalnum():
                virtual_key = ord(part.upper())
            elif re.fullmatch(r"f(?:[1-9]|1\d|2[0-4])", part):
                virtual_key = 0x70 + int(part[1:]) - 1
            else:
                raise ValueError(f"unsupported_hotkey_key:{part}")
        if virtual_key is None:
            raise ValueError(f"hotkey_missing_key:{hotkey}")
        return modifiers, virtual_key

    def _start_windows_hotkey(self) -> dict[str, Any]:
        import ctypes
        from ctypes import wintypes

        modifiers, virtual_key = self._parse_windows_hotkey(self.config.hotkey)
        self._native_ready.clear()
        self._last_error = ""

        def message_loop() -> None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._native_thread_id = int(kernel32.GetCurrentThreadId())
            registered = bool(
                user32.RegisterHotKey(None, self._HOTKEY_ID, modifiers, virtual_key)
            )
            if not registered:
                error_code = ctypes.get_last_error()
                self._last_error = f"register_hotkey_failed:{error_code}"
                self._native_ready.set()
                return
            self._backend = "win32_register_hotkey"
            self._registered = True
            self._native_ready.set()
            message = wintypes.MSG()
            while True:
                result = int(user32.GetMessageW(ctypes.byref(message), None, 0, 0))
                if result <= 0:
                    break
                if message.message == self._WM_HOTKEY and int(message.wParam) == self._HOTKEY_ID:
                    self._toggle()
            user32.UnregisterHotKey(None, self._HOTKEY_ID)
            self._registered = False

        self._native_thread = threading.Thread(
            target=message_loop,
            name="jarvis-global-hotkey",
            daemon=True,
        )
        self._native_thread.start()
        self._native_ready.wait(timeout=3.0)
        if not self._registered:
            return {
                "enabled": True,
                "ok": False,
                "hotkey": self.config.hotkey,
                "backend": "win32_register_hotkey",
                "error": self._last_error or "register_hotkey_timeout",
            }
        return {
            "enabled": True,
            "ok": True,
            "hotkey": self.config.hotkey,
            "mode": "toggle",
            "backend": self._backend,
            "exclusive": True,
            "no_repeat": True,
        }

    def start(self) -> dict[str, Any]:
        if not self.config.hotkey_enabled:
            return {"enabled": False}
        if self._native_supported():
            try:
                return self._start_windows_hotkey()
            except Exception as exc:
                self._last_error = str(exc)[:200]
                return {
                    "enabled": True,
                    "ok": False,
                    "hotkey": self.config.hotkey,
                    "backend": "win32_register_hotkey",
                    "error": self._last_error,
                }
        try:
            import keyboard

            self._handle = keyboard.add_hotkey(
                self.config.hotkey,
                self._toggle,
                suppress=self.config.hotkey_suppress,
                trigger_on_release=self.config.hotkey_trigger_on_release,
            )
            self._registered = True
            self._backend = "keyboard_hook"
            return {
                "enabled": True,
                "ok": True,
                "hotkey": self.config.hotkey,
                "mode": "toggle",
                "suppress": self.config.hotkey_suppress,
                "trigger_on_release": self.config.hotkey_trigger_on_release,
                "backend": self._backend,
            }
        except Exception as exc:
            return {"enabled": True, "ok": False, "error": str(exc)}

    def stop(self) -> None:
        if not self._registered:
            return
        if self._backend == "win32_register_hotkey":
            import ctypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            if self._native_thread_id:
                user32.PostThreadMessageW(self._native_thread_id, self._WM_QUIT, 0, 0)
            if self._native_thread and self._native_thread.is_alive():
                self._native_thread.join(timeout=2.0)
            self._registered = False
            self._native_thread = None
            self._native_thread_id = 0
            return
        try:
            import keyboard

            keyboard.remove_hotkey(self._handle)
        finally:
            self._registered = False
            self._handle = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.config.hotkey_enabled,
                "ok": self._registered,
                "hotkey": self.config.hotkey,
                "mode": "toggle",
                "backend": self._backend,
                "exclusive": self._backend == "win32_register_hotkey",
                "suppress": (
                    True if self._backend == "win32_register_hotkey" else self.config.hotkey_suppress
                ),
                "trigger_on_release": (
                    False
                    if self._backend == "win32_register_hotkey"
                    else self.config.hotkey_trigger_on_release
                ),
                "last_action": self._last_action,
                "trigger_count": self._trigger_count,
                "last_trigger_at": self._last_trigger_at,
                "last_error": self._last_error,
            }
