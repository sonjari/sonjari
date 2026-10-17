"""음성은 읽을 글이 영어면 en 으로 보낸다 (2026-10-17 · 대표 「영어 판을 돌리는데 음성이 한국어로 나온다」).

화면 글은 나가는 순간 번역되는데, 음성 합성에는 설정값 ko 가 늘 실렸다 — 영어 답도 한국어 규칙으로 읽었다.
"""

from __future__ import annotations

from alture_jarvis.config import JarvisConfig
from alture_jarvis.tts import SupertonicTTS


def test_english_text_is_read_in_english_and_korean_stays_korean(tmp_path) -> None:
    tts = SupertonicTTS(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out"))
    assert tts._lang_for("The Eiffel Tower is 330 m tall and was completed in 1889.") == "en"
    assert tts._lang_for("에펠탑은 330m 이고 1889년에 완공됐습니다.") == "ko"
