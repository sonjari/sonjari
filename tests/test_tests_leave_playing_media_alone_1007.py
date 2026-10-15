"""검사는 이 PC 에서 재생 중인 미디어를 멈추지 않는다 (2026-10-07 — 회귀 출력의 `0x8001010e` 20번을 따라가서).

「말하기 버튼을 누르면 재생 중인 미디어를 잠깐 멈춘다」를 타는 검사가 윈도우의 실제 미디어 제어를 부르고 있었다.
이 PC 는 대표가 같이 쓰는 PC 다 — 회귀가 도는 동안 보던 영상이 멈추면 안 된다.
"""
from __future__ import annotations

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.media import MediaSessionController, WindowsMediaBackend


def _must_not_run(*_args, **_kwargs):
    raise AssertionError("검사가 윈도우의 실제 미디어 제어를 불렀다")


def test_the_real_media_backend_does_nothing_under_test(monkeypatch) -> None:
    monkeypatch.setattr(WindowsMediaBackend, "_pause", staticmethod(_must_not_run))
    monkeypatch.setattr(WindowsMediaBackend, "_resume", staticmethod(_must_not_run))
    backend = WindowsMediaBackend()

    assert backend.pause_playing(()) == []
    assert backend.resume(["chrome.exe"]) == []


def test_the_talk_button_path_reaches_no_real_media_control(tmp_path, monkeypatch) -> None:
    """가짜를 안 끼운 조종기 — 운영과 같은 기본 뒷단으로 「멈추기」를 타도 실제 호출까지 안 간다."""
    monkeypatch.setattr(WindowsMediaBackend, "_pause", staticmethod(_must_not_run))
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          media_pause_enabled=True)
    controller = MediaSessionController(config, EventBus())

    result = controller.pause_for_interaction()

    assert result.get("paused") == []
