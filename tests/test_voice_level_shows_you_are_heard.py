"""듣는 중 파형의 재료 (2026-09-30) — 대표: 「내 음성을 얘가 알아듣고 있구나」가 보이게."""
from __future__ import annotations

import numpy as np

from alture_jarvis.voice import PushToTalkRecorder


def test_silence_is_zero_and_a_loud_voice_is_near_one() -> None:
    assert PushToTalkRecorder._level_of(np.zeros((480, 1), dtype="int16")) == 0.0
    loud = (np.sin(np.linspace(0, 60, 480)) * 20000).astype("int16").reshape(-1, 1)
    assert PushToTalkRecorder._level_of(loud) > 0.85


def test_a_quiet_voice_still_shows() -> None:
    quiet = (np.sin(np.linspace(0, 60, 480)) * 300).astype("int16").reshape(-1, 1)
    assert 0.2 < PushToTalkRecorder._level_of(quiet) < 0.7


def test_nothing_is_reported_while_not_recording(tmp_path) -> None:
    from test_api import _config

    recorder = PushToTalkRecorder(_config(tmp_path))
    recorder._level = 0.9
    assert recorder.level() == {"recording": False, "level": 0.0}
