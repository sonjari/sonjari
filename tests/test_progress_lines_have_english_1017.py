"""하네스가 화면에 내는 진행 줄은 전부 영어 사전에 있다 (2026-10-17 영어판 점검).

진행 줄은 나가는 순간 화면 언어로 바뀐다(`ui_i18n`). 사전에 없으면 영어 화면에 한국어가 그대로 나간다 — 그날 다섯 줄이 빠져 있었다
(그중 하나는 같은 날 넣은 「정리를 도구와 같이 써 버려서…」). 새 진행 줄을 넣으면 이 시험이 번역을 같이 넣으라고 알린다.
"""

from __future__ import annotations

import re
from pathlib import Path

from alture_jarvis import ui_i18n

SRC = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"
LINE = re.compile(r'_progress\(\s*job_id\s*,\s*"[^"]*"\s*,\s*"([^"{]+)"\s*[,)]')


def test_every_fixed_progress_line_has_an_english_translation(tmp_path) -> None:
    ui_i18n.configure(tmp_path / "lang.json")
    ui_i18n.set_lang("en")
    try:
        missing = [
            (path.name, text)
            for path in sorted(SRC.glob("*.py"))
            for text in LINE.findall(path.read_text(encoding="utf-8"))
            if re.search(r"[가-힣]", ui_i18n.translate_text(text))
        ]
    finally:
        ui_i18n.set_lang("ko")
    assert missing == [], f"ui_i18n_en.json 에 번역이 없는 진행 줄: {missing}"
