"""마이크가 없는 맥에서 말하기 버튼 (2026-11-22 맥미니 · 입력 장치 0개).

실제로 있었던 일: 도우미가 녹음 연결(installTap)에서 죽었고(SIGABRT · 결과 파일 없음), 백엔드는 첫 누름을
「듣는 중」으로 넘겼다가 두 번째 누름에서 helper_no_result 로 터졌다 → 화면 「Load failed」.
지금: 첫 누름에서 도우미의 끝을 잠깐 보고 까닭(mac_record_failed:<까닭>)을 바로 돌려주고, 화면엔 사람 문장이 간다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from alture_jarvis import mac_voice
from alture_jarvis.api import create_app, ptt_error_text
from alture_jarvis.config import JarvisConfig


class FakeHelper:
    """`open -W … SonjariVoice record` 대신. behaviour: no_mic · crash · started · waiting."""

    def __init__(self, behaviour: str, command: list[str]) -> None:
        self.behaviour = behaviour
        args = command[command.index("--args") + 1:]
        wav = Path(args[args.index("--out") + 1])
        result = Path(args[args.index("--result") + 1])
        self.killed = False
        if behaviour == "no_mic":
            result.write_text(json.dumps({"ok": False, "error": "no_input_device", "input_channels": 0}), encoding="utf-8")
        elif behaviour == "started":
            Path(str(wav) + ".started").write_text("", encoding="utf-8")
        self._done = behaviour in {"no_mic", "crash"}

    def poll(self):  # type: ignore[no-untyped-def]
        return 1 if self._done else None

    def kill(self) -> None:
        self.killed = True


@pytest.fixture()
def recorder(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mac_voice, "helper_present", lambda config: True)
    monkeypatch.setattr(mac_voice, "EARLY_EXIT_WAIT_SEC", 0.3)
    made: list[FakeHelper] = []

    def use(behaviour: str) -> mac_voice.MacRecorder:
        def popen(command, **kwargs):  # type: ignore[no-untyped-def]
            made.append(FakeHelper(behaviour, command))
            return made[-1]
        monkeypatch.setattr(mac_voice.subprocess, "Popen", popen)
        return mac_voice.MacRecorder(SimpleNamespace(output_dir=tmp_path, mac_voice_helper=""))

    return use


def test_no_microphone_fails_on_the_first_press_with_the_helpers_reason(recorder, tmp_path):
    rec = recorder("no_mic")
    with pytest.raises(RuntimeError, match=r"^mac_record_failed:no_input_device$"):
        rec.start()
    assert rec.level()["recording"] is False  # 「듣는 중」으로 남지 않는다
    assert list((tmp_path / "voice_helper").iterdir()) == []  # 결과 · 표시 파일을 남기지 않는다


def test_helper_that_dies_without_a_result_is_named_helper_no_result(recorder):
    rec = recorder("crash")
    with pytest.raises(RuntimeError, match=r"^mac_record_failed:helper_no_result$"):
        rec.start()
    assert rec.level()["recording"] is False


def test_started_helper_keeps_recording(recorder):
    rec = recorder("started")
    assert rec.start()["recording"] is True
    assert rec.level()["recording"] is True


def test_slow_helper_waiting_for_the_permission_prompt_is_not_a_failure(recorder):
    # 처음엔 마이크 허락 창이 떠 사람이 누를 때까지 도우미가 기다린다 — 시간이 다 돼도 실패로 치지 않는다.
    rec = recorder("waiting")
    assert rec.start()["recording"] is True


@pytest.mark.parametrize(("raw", "code", "words"), [
    ("mac_record_failed:no_input_device", "no_input_device", "마이크가 없습니다"),
    ("mac_record_failed:helper_no_result", "helper_no_result", "음성 도우미"),
    ("mac_record_failed:mic_permission_denied", "mic_permission_denied", "손자리 음성"),
    ("mac_record_failed:no_audio", "no_audio", "녹음되지 않았습니다"),
])
def test_helper_reasons_become_sentences(raw, code, words):
    text = ptt_error_text(raw)
    assert text.startswith(f"{code}: ") and words in text


def test_unknown_inner_reason_keeps_its_name():
    assert ptt_error_text("mac_record_failed:engine_start_failed: boom").startswith(
        "engine_start_failed: 녹음을 시작하지 못했습니다(engine_start_failed: boom)")


def test_probe_input_device_reaches_dependency_status(tmp_path, monkeypatch):
    monkeypatch.setattr(mac_voice, "helper_present", lambda config: True)
    stt = mac_voice.AppleSpeechToText(SimpleNamespace(voice_enabled=True, output_dir=tmp_path, mac_voice_helper=""))
    stt._probe = {"ok": True, "on_device": True, "mic": "authorized", "input_device": False, "input_channels": 0}
    status = stt.dependency_status()
    assert status["input_device"] is False and status["input_channels"] == 0


def test_screen_gets_the_no_microphone_sentence(tmp_path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md")
    app = create_app(config, start_services=False)

    def start():  # type: ignore[no-untyped-def]
        raise RuntimeError("mac_record_failed:no_input_device")
    app.state.jarvis.recorder.start = start
    with TestClient(app, raise_server_exceptions=False) as client:
        res = client.post("/v1/voice/ptt/toggle", json={}, headers={"X-JARVIS-TOKEN": "test-token"})
    assert res.status_code == 409
    assert res.json()["detail"].startswith("no_input_device: 이 맥에 연결된 마이크가 없습니다")
