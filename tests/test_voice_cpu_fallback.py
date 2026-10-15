"""그래픽 카드 받아쓰기가 안 되는 PC 에서는 CPU·작은 모델로 (2026-09-24 노트북 포장본).

포장이 cuBLAS 를 빼서 받아쓰기가 매번 `cublas64_12.dll is not found` 로 실패했다. 기본값이 cuda 라 포장본에선
항상 실패였다. 그리고 CPU 로 large-v3-turbo 를 돌리면 5초 음성에 6초가 걸린다 — CPU 는 small.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

from alture_jarvis import voice
from alture_jarvis.config import JarvisConfig


class _Seg:
    def __init__(self, text: str) -> None:
        self.text = text


def _fake_whisper(monkeypatch, *, fail_on_cuda: bool = False) -> list[dict]:
    made: list[dict] = []

    class FakeModel:
        def __init__(self, name, **kwargs):
            self.device = kwargs.get("device")
            made.append({"name": name, **kwargs})

        def transcribe(self, path, **kwargs):
            made[-1]["language"] = kwargs.get("language")

            def gen():
                if fail_on_cuda and self.device == "cuda":
                    raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
                yield _Seg("오늘 몇 월 며칠이야?")

            return gen(), types.SimpleNamespace(language="ko", duration=2.0)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    return made


def test_missing_cublas_goes_to_cpu_with_the_small_model(monkeypatch):
    made = _fake_whisper(monkeypatch)
    monkeypatch.setattr(voice, "_cuda_math_libraries_load", lambda: False)
    stt = voice.SpeechToText(JarvisConfig())
    out = stt.transcribe(Path("x.wav"))
    assert out["text"] == "오늘 몇 월 며칠이야?"
    assert made[0]["name"] == "small" and made[0]["device"] == "cpu" and made[0]["compute_type"] == "int8"
    assert "cuBLAS" in stt.dependency_status().get("fallback", "")


def test_a_cuda_failure_at_run_time_retries_once_on_cpu(monkeypatch):
    made = _fake_whisper(monkeypatch, fail_on_cuda=True)
    monkeypatch.setattr(voice, "_cuda_math_libraries_load", lambda: True)
    monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(get_cuda_device_count=lambda: 1))
    stt = voice.SpeechToText(JarvisConfig())
    out = stt.transcribe(Path("x.wav"))
    assert out["text"] == "오늘 몇 월 며칠이야?"
    assert [(m["name"], m["device"]) for m in made] == [("large-v3-turbo", "cuda"), ("small", "cpu")]
    # 다음 받아쓰기부터는 처음부터 CPU 다(매번 실패를 다시 겪지 않는다).
    assert stt._resolve_device()[0] == "cpu"


def test_a_working_gpu_keeps_the_big_model(monkeypatch):
    made = _fake_whisper(monkeypatch)
    monkeypatch.setattr(voice, "_cuda_math_libraries_load", lambda: True)
    monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(get_cuda_device_count=lambda: 1))
    voice.SpeechToText(JarvisConfig()).transcribe(Path("x.wav"))
    assert (made[0]["name"], made[0]["device"]) == ("large-v3-turbo", "cuda")


def test_language_is_a_setting_and_auto_means_detect(monkeypatch):
    made = _fake_whisper(monkeypatch)
    monkeypatch.setattr(voice, "_cuda_math_libraries_load", lambda: False)
    voice.SpeechToText(JarvisConfig()).transcribe(Path("x.wav"))
    assert made[-1]["language"] == "ko"
    monkeypatch.setenv("JARVIS_STT_LANGUAGE", "auto")
    cfg = JarvisConfig.from_env()
    assert cfg.stt_language == "auto"
    voice.SpeechToText(cfg).transcribe(Path("x.wav"))
    assert made[-1]["language"] is None
