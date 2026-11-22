"""맥판 음성 (2026-11-16) — 말하기는 맥 `say`, 듣기는 애플 기기 안 받아쓰기. 윈도우는 그대로.

맥 전용 길은 PC 에서 `subprocess` 를 가짜로 바꿔 시험한다. 실기기 한 판은 맥미니에서 따로 했다(인계 메모).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from alture_jarvis import mac_voice, settings, voice
from alture_jarvis.config import JarvisConfig
from alture_jarvis.tts import SupertonicTTS

VOICES = (
    "Samantha (영어(미국))   en_US    # Hello! My name is Samantha.\n"
    "Albert              en_US    # Hello! My name is Albert.\n"
    "Yuna (한국어(한국))      ko_KR    # 안녕하세요. 제 이름은 유나입니다.\n"
    "Eddy (한국어(한국))      ko_KR    # 안녕하세요. 제 이름은 Eddy입니다.\n"
)


def _write_wav(path: Path, *, seconds: float) -> None:
    import wave

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\0\0" * int(22050 * seconds))


def _config(tmp_path: Path, **extra) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs", **extra)


@pytest.fixture
def on_mac(monkeypatch):
    monkeypatch.setattr(mac_voice, "is_mac", lambda: True)
    monkeypatch.setattr(mac_voice, "_voices_cache", None)
    monkeypatch.setattr(mac_voice.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(list(command))
        if command[1:3] == ["-v", "?"]:
            return SimpleNamespace(returncode=0, stdout=VOICES, stderr="")
        if "-o" in command:
            _write_wav(Path(command[command.index("-o") + 1]), seconds=1.0)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mac_voice.subprocess, "run", run)
    return calls


# ── 엔진 고르기 ─────────────────────────────────────────────────────────────

def test_windows_keeps_supertonic_and_faster_whisper(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mac_voice, "is_mac", lambda: False)
    config = _config(tmp_path)
    assert SupertonicTTS(config).engine == "supertonic"
    assert isinstance(voice.make_speech_to_text(config), voice.SpeechToText)
    assert isinstance(voice.make_recorder(config), voice.PushToTalkRecorder)


def test_mac_auto_uses_mac_builtins(on_mac, tmp_path) -> None:
    config = _config(tmp_path)
    assert SupertonicTTS(config).engine == "macos"
    assert isinstance(voice.make_speech_to_text(config), mac_voice.AppleSpeechToText)
    assert isinstance(voice.make_recorder(config), mac_voice.MacRecorder)


def test_explicit_engine_wins_on_mac(on_mac, tmp_path) -> None:
    config = _config(tmp_path, tts_engine="supertonic", stt_engine="faster_whisper")
    assert SupertonicTTS(config).engine == "supertonic"
    assert isinstance(voice.make_speech_to_text(config), voice.SpeechToText)


# ── 말하기: say ─────────────────────────────────────────────────────────────

def test_voice_list_parsing_strips_language_suffix() -> None:
    voices = mac_voice.parse_voice_list(VOICES)
    assert voices["Yuna"] == "ko_KR"
    assert voices["Samantha"] == "en_US"


def test_mac_synthesize_uses_say_locally_and_never_calls_the_voice_server(on_mac, monkeypatch, tmp_path) -> None:
    def no_http(**_kwargs):
        raise AssertionError("맥 say 엔진은 음성 서버(집 PC)에 글을 보내면 안 된다")

    monkeypatch.setattr("alture_jarvis.tts.httpx.Client", no_http)
    config = _config(tmp_path, supertonic_base_url="http://192.0.2.10:7788")
    tts = SupertonicTTS(config)
    path = tts.synthesize("오늘 일정은 세 개입니다.")
    say = [c for c in on_mac if "-o" in c][-1]
    assert say[say.index("-v") + 1] == "Yuna"
    assert "--file-format=WAVE" in say and say[-1] == "오늘 일정은 세 개입니다."
    assert path.exists() and tts.last_metrics["engine"] == "macos"


def test_english_text_gets_english_voice(on_mac, tmp_path) -> None:
    SupertonicTTS(_config(tmp_path)).synthesize("The meeting starts at three o'clock today.")
    say = [c for c in on_mac if "-o" in c][-1]
    assert say[say.index("-v") + 1] == "Samantha"


def test_missing_configured_voice_falls_back_to_installed_korean(on_mac, tmp_path) -> None:
    assert mac_voice.pick_voice(_config(tmp_path, mac_tts_voice="NoSuchVoice"), "ko") == "Yuna"


def test_say_failure_is_an_error_not_a_silent_success(on_mac, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mac_voice.subprocess, "run",
                        lambda command, **_k: SimpleNamespace(returncode=1, stdout=VOICES, stderr="boom"))
    with pytest.raises(RuntimeError, match="say_failed"):
        mac_voice.say_to_wav("안녕", tmp_path / "x.wav", voice="Yuna")


# ── 상태 보고 ───────────────────────────────────────────────────────────────

def test_mac_health_ok_only_with_a_korean_voice(on_mac, monkeypatch, tmp_path) -> None:
    health = SupertonicTTS(_config(tmp_path)).health()
    assert health == {"enabled": True, "engine": "macos", "where": "this_device", "ok": True, "voice": "Yuna"}
    monkeypatch.setattr(mac_voice, "_voices_cache", {"Samantha": "en_US"})
    health = SupertonicTTS(_config(tmp_path)).health()
    assert health["ok"] is False and health["error"] == "korean_voice_not_installed"


def test_supertonic_health_says_where_it_speaks(monkeypatch, tmp_path) -> None:
    """11-16: 맥 /health 는 tts ok 였지만 실제로는 집 PC(192.0.2.10)가 답한 것이었다 — 어디서인지 말한다."""
    monkeypatch.setattr(mac_voice, "is_mac", lambda: False)

    class _Client:
        def __init__(self, **_k): pass
        def __enter__(self): return self
        def __exit__(self, *_a): return None
        def get(self, _url): return SimpleNamespace(status_code=200, raise_for_status=lambda: None)

    monkeypatch.setattr("alture_jarvis.tts.httpx.Client", _Client)
    remote = SupertonicTTS(_config(tmp_path, supertonic_base_url="http://192.0.2.10:7788")).health()
    local = SupertonicTTS(_config(tmp_path)).health()
    assert remote["where"] == "remote:192.0.2.10" and remote["engine"] == "supertonic"
    assert local["where"] == "this_device"


def test_mac_warmup_never_starts_supertonic(on_mac, monkeypatch, tmp_path) -> None:
    from alture_jarvis import runtime as runtime_module

    started: list[str] = []
    monkeypatch.setattr(runtime_module.tts_server, "ensure", lambda url: started.append(url) or {})
    monkeypatch.setattr(runtime_module.tts_server, "answering", lambda url: False)
    config = _config(tmp_path)
    marks: list[tuple] = []
    fake = SimpleNamespace(
        config=config, tts=SupertonicTTS(config),
        _set_warmup_component=lambda name, status, **kw: marks.append((name, status)),
        _warmup_stop=SimpleNamespace(is_set=lambda: False, wait=lambda _s: None),
    )
    runtime_module.JarvisRuntime._warm_tts(fake)
    assert started == []
    assert marks[-1] == ("tts", "ready")


def test_self_care_on_mac_offers_no_server_restart(on_mac, monkeypatch, tmp_path) -> None:
    from alture_jarvis.self_care import SelfCare

    monkeypatch.setattr(mac_voice, "_voices_cache", {})
    fake = SimpleNamespace(tts=SupertonicTTS(_config(tmp_path)), config=_config(tmp_path), _organ=SelfCare._organ)
    organ = SelfCare._check_tts(fake)
    assert organ["state"] == "down" and organ["healer"] == ""


def test_settings_on_mac_judge_by_say_not_supertonic_module(on_mac, tmp_path) -> None:
    config = _config(tmp_path)
    assert settings.unavailable_reason("tts_enabled", config) == ""
    assert "도우미" in settings.unavailable_reason("voice_enabled", config)


# ── 듣기: 도우미 ────────────────────────────────────────────────────────────

def _install_helper(tmp_path: Path) -> Path:
    app = tmp_path / "SonjariVoice.app"
    exe = app / "Contents" / "MacOS" / "SonjariVoice"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    return app


def _fake_open(monkeypatch, reply: dict, seen: list) -> None:
    def run(command, **_kwargs):
        seen.append(list(command))
        Path(command[command.index("--result") + 1]).write_text(json.dumps(reply), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mac_voice.subprocess, "run", run)


def test_helper_missing_is_reported_not_ok(on_mac, tmp_path) -> None:
    stt = mac_voice.AppleSpeechToText(_config(tmp_path, mac_voice_helper=str(tmp_path / "none.app")))
    status = stt.dependency_status()
    assert status["ok"] is False and status["error"] == "helper_missing"


def test_transcribe_goes_through_open_so_the_helper_owns_permission(on_mac, monkeypatch, tmp_path) -> None:
    seen: list = []
    _fake_open(monkeypatch, {"ok": True, "text": " 내일 오후 3시 ", "on_device": True, "engine": "speech_transcriber"}, seen)
    stt = mac_voice.AppleSpeechToText(_config(tmp_path, mac_voice_helper=str(_install_helper(tmp_path))))
    result = stt.transcribe(tmp_path / "a.wav")
    assert result["text"] == "내일 오후 3시"
    assert seen[0][:2] == ["open", "-W"] and "transcribe" in seen[0] and "ko-KR" in seen[0]


def test_answer_not_confirmed_on_device_is_refused(on_mac, monkeypatch, tmp_path) -> None:
    _fake_open(monkeypatch, {"ok": True, "text": "서버가 받아쓴 글", "on_device": False}, [])
    stt = mac_voice.AppleSpeechToText(_config(tmp_path, mac_voice_helper=str(_install_helper(tmp_path))))
    with pytest.raises(RuntimeError, match="not_on_device"):
        stt.transcribe(tmp_path / "a.wav")


def test_probe_failure_makes_status_not_ok(on_mac, monkeypatch, tmp_path) -> None:
    _fake_open(monkeypatch, {"ok": False, "error": "on_device_unsupported", "mic": "not_determined"}, [])
    stt = mac_voice.AppleSpeechToText(_config(tmp_path, mac_voice_helper=str(_install_helper(tmp_path))))
    with pytest.raises(RuntimeError, match="on_device_unsupported"):
        stt.warmup()
    status = stt.dependency_status()
    assert status["ok"] is False and status["error"] == "on_device_unsupported"


class _FakeHelperProcess:
    """`open -W … record` 대신 — 멈춤 파일이 생기면 WAV 와 결과를 쓰고 끝난다."""

    def __init__(self, command, reply_ok=True):
        self.command = command
        self.reply_ok = reply_ok
        if reply_ok:
            # 진짜 도우미처럼 녹음이 시작되면 「.started」 표시를 남긴다(11-22: 백엔드가 첫 누름에서 이것을 본다).
            Path(str(self._arg("--out")) + ".started").write_text("", encoding="utf-8")
        else:
            # 허락이 없으면 진짜 도우미는 녹음 전에 까닭을 쓰고 바로 끝난다.
            self._arg("--result").write_text(json.dumps({"ok": False, "error": "mic_permission_denied"}), encoding="utf-8")

    def _arg(self, name):
        return Path(self.command[self.command.index(name) + 1])

    def poll(self):
        return None if self.reply_ok else 1

    def wait(self, timeout=None):
        assert self._arg("--stop-file").exists(), "stop 은 멈춤 파일을 먼저 만들어야 한다"
        if self.reply_ok:
            self._arg("--out").write_bytes(b"RIFF-rec")
            reply = {"ok": True, "frames": 16000}
        else:
            reply = {"ok": False, "error": "mic_permission_denied"}
        self._arg("--result").write_text(json.dumps(reply), encoding="utf-8")
        return 0

    def kill(self):
        pass


def test_recorder_start_stop_moves_the_recording(on_mac, monkeypatch, tmp_path) -> None:
    made: list = []
    monkeypatch.setattr(mac_voice.subprocess, "Popen", lambda command, **_k: made.append(_FakeHelperProcess(command)) or made[-1])
    recorder = mac_voice.MacRecorder(_config(tmp_path, mac_voice_helper=str(_install_helper(tmp_path))))
    assert recorder.start()["recording"] is True
    assert recorder.level()["recording"] is True
    out = recorder.stop(tmp_path / "rec" / "ptt.wav")
    assert out.read_bytes() == b"RIFF-rec"
    assert made[0].command[:2] == ["open", "-W"] and "record" in made[0].command
    assert recorder.level()["recording"] is False


def test_recorder_reports_mic_denied(on_mac, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mac_voice.subprocess, "Popen", lambda command, **_k: _FakeHelperProcess(command, reply_ok=False))
    recorder = mac_voice.MacRecorder(_config(tmp_path, mac_voice_helper=str(_install_helper(tmp_path))))
    # 11-22 부터 거절은 첫 누름(start)에서 바로 온다 — 전엔 「듣는 중」으로 넘어갔다가 멈출 때 터졌다.
    with pytest.raises(RuntimeError, match="mic_permission_denied"):
        recorder.start()
    assert recorder.level()["recording"] is False


def test_near_empty_audio_from_a_listed_voice_is_a_failure(on_mac, monkeypatch, tmp_path) -> None:
    """11-16 맥미니: 「Eddy」는 끝 코드 0 으로 0.01초 소리를 만들었다 — 성공으로 치면 사람은 아무것도 못 듣는다."""
    def run(command, **_kwargs):
        _write_wav(Path(command[command.index("-o") + 1]), seconds=0.0116)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mac_voice.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="say_empty_audio"):
        mac_voice.say_to_wav("손자리야 알람 맞춰 줘", tmp_path / "x.wav", voice="Eddy")
    assert not (tmp_path / "x.wav").exists()


def test_mac_cache_hit_reports_mac_engine(on_mac, tmp_path) -> None:
    tts = SupertonicTTS(_config(tmp_path))
    tts.synthesize("안녕하세요.")
    tts.synthesize("안녕하세요.")
    assert tts.last_metrics == {"cached": True, "engine": "macos", "synthesis_ms": 0}
