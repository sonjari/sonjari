"""**맥 음성은 맥 기본 기능으로** — 말하기는 `say`, 듣기는 애플 받아쓰기(기기 안에서만) (2026-11-16 · 대표 결정).

## 왜

맥(맥미니 M4 16GB)에서 Supertonic(목소리 약 385MB) · faster-whisper 를 올리면 대화 모델 자리가 준다. 시리처럼 맥에 이미
있는 것을 쓴다. 그리고 **정보를 밖으로 보내지 않는다**(대표 원칙):

- 말하기: `say -v Yuna -o <wav>` — 이 맥 안에서 만든다. 11-16 까지 맥은 집 PC 의 Supertonic(집 안 주소 :7788)에 글을 보내
  만들어 왔다(`.env` 의 `JARVIS_SUPERTONIC_BASE_URL`). 집 밖이면 그 길은 끊긴다.
- 듣기: `SonjariVoice.app`(Swift 도우미 · `native/mac/SonjariVoice`). macOS 26+ 는 SpeechTranscriber(이 맥에 설치된 모델만),
  그 밖은 SFSpeechRecognizer + `requiresOnDeviceRecognition`. 서버로 가는 길은 도우미 코드에 없다.

## 왜 도우미를 `open` 으로 띄우나

백엔드는 LaunchAgent 가 띄운 파이썬이다. 파이썬이 바로 도우미를 자식으로 띄우면 마이크 허락의 주인은 **파이썬**이 되는데,
파이썬 실행 파일에는 허락 창에 쓸 설명(Info.plist)이 없다 — 창이 안 뜨거나 거절된다. `open` 으로 띄우면 도우미 앱이 스스로
주인이 되고, 허락 창에 「손자리 음성」과 그 까닭이 뜬다(사람이 누른다).

## 윈도우는 그대로

엔진을 `auto` 로 두면 맥이 아닐 때 지금까지의 길(Supertonic · faster-whisper)을 그대로 쓴다. 이 파일은 맥에서만 일한다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

#: 도우미 결과를 기다리는 최대 초 — 받아쓰기는 55초 소리에 0.73초(11-16 맥미니 실측)라 넉넉하다.
HELPER_TIMEOUT_SEC = 60.0
# 녹음 누름 뒤 도우미가 「시작했다」 표시를 내거나 끝날 때까지 기다리는 최대 초. 마이크 없음 · 충돌은 1초 안에 끝난다.
EARLY_EXIT_WAIT_SEC = 3.0
#: 윈도우 규칙(창 숨김)과 맞춘다 — 맥에서는 0 이라 아무 일도 안 한다.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_mac() -> bool:
    return sys.platform == "darwin"


def tts_engine(config: Any) -> str:
    """말하기 엔진 — `macos` 또는 `supertonic`. 모르는 값은 auto 로 친다."""
    wanted = str(getattr(config, "tts_engine", "auto") or "auto").strip().lower()
    if wanted in ("macos", "supertonic"):
        return wanted
    return "macos" if is_mac() else "supertonic"


def stt_engine(config: Any) -> str:
    """받아쓰기 엔진 — `apple` 또는 `faster_whisper`."""
    wanted = str(getattr(config, "stt_engine", "auto") or "auto").strip().lower()
    if wanted in ("apple", "faster_whisper"):
        return wanted
    return "apple" if is_mac() else "faster_whisper"


# ── 말하기: say ─────────────────────────────────────────────────────────────

_VOICE_LINE = re.compile(r"^(?P<name>.+?)\s{2,}(?P<locale>[a-z]{2,3}_[A-Z0-9]{2,3})\s+#")
_voices_cache: dict[str, str] | None = None
_voices_lock = threading.Lock()


def parse_voice_list(text: str) -> dict[str, str]:
    """`say -v ?` 출력 → {목소리 이름: 지역}. 「Yuna (한국어(한국))」처럼 붙은 괄호는 뗀다(`say -v Yuna` 로 부른다)."""
    voices: dict[str, str] = {}
    for line in str(text or "").splitlines():
        match = _VOICE_LINE.match(line.strip())
        if not match:
            continue
        name = re.sub(r"\s*\(.*\)\s*$", "", match.group("name")).strip()
        if name:
            voices.setdefault(name, match.group("locale"))
    return voices


def installed_voices(*, refresh: bool = False) -> dict[str, str]:
    """이 맥의 목소리. ★ `say` 는 없는 목소리 이름을 줘도 끝 코드 0 으로 조용히 기본 목소리로 읽는다(11-16 맥미니 실측) —
    그래서 「한국어 목소리가 있나」는 끝 코드가 아니라 이 목록으로 본다."""
    global _voices_cache
    with _voices_lock:
        if _voices_cache is None or refresh:
            say = shutil.which("say")
            if not say:
                _voices_cache = {}
            else:
                out = subprocess.run([say, "-v", "?"], capture_output=True, text=True, timeout=15, check=False,
                                     creationflags=_NO_WINDOW)
                _voices_cache = parse_voice_list(out.stdout)
        return dict(_voices_cache)


def pick_voice(config: Any, lang: str) -> str:
    """읽을 언어에 맞는 목소리. 설정한 이름이 이 맥에 없으면 그 언어의 첫 목소리 · 그것도 없으면 빈 값(맥 기본)."""
    voices = installed_voices()
    wanted = str(getattr(config, "mac_tts_voice_en" if lang == "en" else "mac_tts_voice", "") or "")
    if wanted and wanted in voices:
        return wanted
    prefix = "en_" if lang == "en" else f"{(lang or 'ko')[:2]}_"
    for name, locale in voices.items():
        if locale.startswith(prefix):
            return name
    return ""


def say_command(text: str, output: Path, *, voice: str, rate: int) -> list[str]:
    command = [shutil.which("say") or "say"]
    if voice:
        command += ["-v", voice]
    if rate and rate > 0:
        command += ["-r", str(int(rate))]
    # WAV 로 만든다 — 윈도우판과 같은 캐시 자리(.wav)와 afplay 재생을 그대로 쓴다.
    command += ["-o", str(output), "--file-format=WAVE", "--data-format=LEI16@22050", "--", text]
    return command


def say_to_wav(text: str, output: Path, *, voice: str, rate: int = 0, timeout: float = 120.0) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(say_command(text, output, voice=voice, rate=rate), capture_output=True, text=True,
                         timeout=timeout, check=False, creationflags=_NO_WINDOW)
    if out.returncode != 0 or not output.exists():
        raise RuntimeError(f"say_failed:{out.returncode}:{(out.stderr or '').strip()[:160]}")
    # ★ 11-16 맥미니: 목록에 있는 「Eddy」가 끝 코드 0 으로 0.01초짜리 빈 소리를 만들었다(내려받지 않은 목소리로 보임 · 짐작).
    #   끝 코드도 파일 크기도 속는다 — 실제 길이를 잰다. 두 글자 넘는 글이 0.2초 안 되면 실패다.
    seconds = wav_seconds(output)
    if len(text.strip()) >= 2 and seconds < 0.2:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"say_empty_audio:{voice or 'default'}:{seconds:.3f}s")
    return output


def wav_seconds(path: Path) -> float:
    import wave

    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / float(wav.getframerate() or 1)
    except (OSError, EOFError, wave.Error):
        return 0.0


def say_health(config: Any) -> dict[str, Any]:
    """맥 말하기가 **실제로** 되나 — `say` 가 있고, 한국어 목소리가 이 맥에 있나."""
    base = {"engine": "macos", "where": "this_device"}
    if not is_mac() or not shutil.which("say"):
        return {**base, "ok": False, "error": "say_not_found"}
    voice = pick_voice(config, "ko")
    if not voice:
        return {**base, "ok": False, "error": "korean_voice_not_installed"}
    return {**base, "ok": True, "voice": voice}


# ── 듣기: 도우미 ────────────────────────────────────────────────────────────

def helper_path(config: Any) -> Path:
    configured = str(getattr(config, "mac_voice_helper", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    # 앱 폴더(…/app/src/alture_jarvis → …/app)의 voice/. install_mac.sh 가 여기에 놓는다.
    return Path(__file__).resolve().parents[2] / "voice" / "SonjariVoice.app"


def helper_present(config: Any) -> bool:
    return (helper_path(config) / "Contents" / "MacOS" / "SonjariVoice").exists()


def open_command(app: Path, args: list[str], result: Path) -> list[str]:
    """도우미를 `open` 으로 띄우는 명령. -W 끝날 때까지 · -n 새로 · -g 앞으로 안 나옴 · -j 숨김."""
    return ["open", "-W", "-n", "-g", "-j", "-a", str(app), "--args", *args, "--result", str(result)]


def _work_dir(config: Any) -> Path:
    folder = Path(getattr(config, "output_dir", Path.cwd())) / "voice_helper"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def run_helper(config: Any, args: list[str], *, timeout: float = HELPER_TIMEOUT_SEC) -> dict[str, Any]:
    """도우미 한 번 — 결과 JSON 을 돌려준다. 결과 파일이 없으면 무엇이 없었는지를 돌려준다(지어내지 않는다)."""
    if not helper_present(config):
        return {"ok": False, "error": "helper_missing", "path": str(helper_path(config))}
    result = _work_dir(config) / f"{uuid.uuid4().hex}.json"
    try:
        out = subprocess.run(open_command(helper_path(config), args, result), capture_output=True, text=True,
                             timeout=timeout, check=False, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "helper_timeout"}
    try:
        data = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "helper_no_result", "returncode": out.returncode,
                "stderr": (out.stderr or "").strip()[:200]}
    finally:
        result.unlink(missing_ok=True)
    return data if isinstance(data, dict) else {"ok": False, "error": "helper_bad_result"}


class AppleSpeechToText:
    """`SpeechToText` 의 맥 판 — 같은 세 이름(dependency_status · warmup · transcribe)을 쓴다."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self._probe: dict[str, Any] | None = None

    def _base(self) -> dict[str, Any]:
        return {"engine": "apple", "where": "this_device"}

    def probe(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._probe is None or refresh:
            self._probe = run_helper(self.config, ["probe", "--locale", self._locale()], timeout=30.0)
        return dict(self._probe)

    def _locale(self) -> str:
        lang = str(getattr(self.config, "stt_language", "ko") or "ko").strip().lower()
        return {"ko": "ko-KR", "en": "en-US", "auto": "ko-KR", "": "ko-KR"}.get(lang, lang)

    def dependency_status(self) -> dict[str, Any]:
        if not getattr(self.config, "voice_enabled", True):
            return {**self._base(), "ok": False, "enabled": False}
        if not helper_present(self.config):
            return {**self._base(), "ok": False, "enabled": True, "error": "helper_missing",
                    "path": str(helper_path(self.config))}
        status: dict[str, Any] = {**self._base(), "ok": True, "enabled": True}
        if self._probe is not None:
            # 한 번 물어본 결과를 싣는다(/health 마다 도우미를 띄우지 않는다). 기기 안 처리가 안 되면 ok=false.
            status.update({key: self._probe.get(key) for key in ("on_device", "mic", "macos", "input_device", "input_channels")
                           if key in self._probe})
            if not self._probe.get("ok"):
                status["ok"] = False
                status["error"] = self._probe.get("error") or "probe_failed"
        else:
            status["checked"] = False
        return status

    def warmup(self) -> dict[str, Any]:
        if not getattr(self.config, "voice_enabled", True):
            return {"ok": False, "enabled": False}
        started = time.perf_counter()
        probe = self.probe(refresh=True)
        if not probe.get("ok"):
            raise RuntimeError(str(probe.get("error") or "probe_failed"))
        return {**self._base(), "ok": True, "on_device": probe.get("on_device"), "mic": probe.get("mic"),
                "load_ms": round((time.perf_counter() - started) * 1000, 1)}

    def transcribe(self, path: Path) -> dict[str, Any]:
        result = run_helper(self.config, ["transcribe", "--in", str(path), "--locale", self._locale()])
        if not result.get("ok"):
            raise RuntimeError(f"apple_stt_failed:{result.get('error')}")
        if result.get("on_device") is not True:
            # 도우미가 기기 안 처리라고 확인하지 않은 답은 쓰지 않는다 — 이 줄이 원칙을 지키는 마지막 자리다.
            raise RuntimeError("apple_stt_not_on_device")
        return {"text": str(result.get("text") or "").strip(), "language": self._locale()[:2],
                "duration": None, "engine": result.get("engine"), "ms": result.get("ms")}


class MacRecorder:
    """`PushToTalkRecorder` 의 맥 판 — 도우미가 녹음하고, 멈춤 파일이 생기면 파일을 닫는다."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._paths: dict[str, Path] = {}
        self._lock = threading.Lock()

    def level(self) -> dict[str, Any]:
        # 도우미는 소리 크기를 흘리지 않는다(아직). 녹음 중인지만 말한다.
        return {"recording": self._process is not None, "level": 0.0}

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._process is not None:
                return {"recording": True, "already_started": True}
            if not helper_present(self.config):
                raise RuntimeError("mac_voice_helper_missing")
            work = _work_dir(self.config)
            key = uuid.uuid4().hex
            self._paths = {"wav": work / f"rec-{key}.wav", "stop": work / f"rec-{key}.stop",
                           "result": work / f"rec-{key}.json"}
            command = open_command(helper_path(self.config),
                                   ["record", "--out", str(self._paths["wav"]), "--stop-file", str(self._paths["stop"])],
                                   self._paths["result"])
            self._process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,  # noqa: S603
                                             creationflags=_NO_WINDOW)
            early = self._early_exit(self._process, self._paths)
            if early is not None:
                # 도우미가 녹음을 시작하기도 전에 끝났다(마이크 없음 · 허락 거절 · 충돌). 첫 누름에서 까닭을 돌려준다 —
                # 전에는 「듣는 중」으로 넘어갔다가 두 번째 누름(멈춤)에서야 helper_no_result 로 터졌다(11-22 맥미니).
                self._process = None
                for path in self._paths.values():
                    path.unlink(missing_ok=True)
                self._paths = {}
                raise RuntimeError(f"mac_record_failed:{early}")
        return {"recording": True, "engine": "apple"}

    @staticmethod
    def _early_exit(process: "subprocess.Popen[str]", paths: dict[str, Path]) -> str | None:
        """녹음이 시작됐다는 표시(.started)나 도우미의 끝 중 먼저 오는 것을 잠깐 기다린다.

        끝났으면 결과 파일의 error(없으면 helper_no_result = 결과 없이 죽음)를, 시작됐거나 아직 모르면 None.
        ★ 시간이 다 돼도 실패로 치지 않는다 — 처음엔 마이크 허락 창이 떠서 사람이 누를 때까지 기다리기 때문이다.
        """
        started = Path(str(paths["wav"]) + ".started")
        deadline = time.monotonic() + EARLY_EXIT_WAIT_SEC
        while time.monotonic() < deadline:
            if started.exists():
                return None
            if process.poll() is not None:
                try:
                    result = json.loads(paths["result"].read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return "helper_no_result"
                if isinstance(result, dict) and not result.get("ok"):
                    return str(result.get("error") or "helper_no_result")
                return "helper_no_result"
            time.sleep(0.05)
        return None

    def stop(self, output: Path) -> Path:
        with self._lock:
            process, paths = self._process, dict(self._paths)
            self._process = None
        if process is None:
            raise RuntimeError("not_recording")
        paths["stop"].touch()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            raise RuntimeError("mac_record_stop_timeout") from None
        finally:
            paths["stop"].unlink(missing_ok=True)
        try:
            result = json.loads(paths["result"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {"ok": False, "error": "helper_no_result"}
        finally:
            paths["result"].unlink(missing_ok=True)
        if not result.get("ok"):
            paths["wav"].unlink(missing_ok=True)
            raise RuntimeError(f"mac_record_failed:{result.get('error')}")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(paths["wav"]), str(output))
        return output
