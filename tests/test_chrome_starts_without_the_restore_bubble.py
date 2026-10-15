"""**온텔릭 크롬이 뜰 때 번쩍이지 않는다** — 지난 종료를 「정상」으로 적고 띄운다 (2026-09-18 밤).

사용자: 「크롬을 띄울 때 팍 떴다가 스르륵 들어간다 — 사용자가 놀란다.」

온텔릭이 재시작·업데이트되면 크롬이 강제로 꺼져 프로필에 `exit_type: Crashed` 가 남는다. 다음에 띄우면 크롬이
「페이지 복원」 말풍선을 띄우며 창을 스스로 앞으로 끌어올렸다. 실측(`bench/browser_agents/measure_chrome_flash.py`):

    Crashed 조건 · 고치기 전   사람 창 위로 200~300ms(4/5판) · 최소화 4~8번 · 앞창 약 4.8초
    Normal 조건                0 · 0 · 0 (×5)
    Crashed 조건 · 고친 뒤     0 · 0 · 0 (×5)
"""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, browser_profile_dir=tmp_path / "profile"))


def _prefs(tmp_path: Path) -> Path:
    return tmp_path / "profile" / "Default" / "Preferences"


def test_a_crashed_profile_is_marked_clean_before_chrome_starts(tmp_path: Path) -> None:
    path = _prefs(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"profile": {"exit_type": "Crashed", "name": "x"}, "translate": {"enabled": False}}),
                    encoding="utf-8")

    assert _worker(tmp_path)._mark_our_profile_exited_cleanly() is True

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["profile"]["exit_type"] == "Normal" and saved["profile"]["exited_cleanly"] is True
    assert saved["profile"]["name"] == "x" and saved["translate"] == {"enabled": False}, "다른 값은 그대로 둔다"


def test_a_clean_profile_is_not_rewritten(tmp_path: Path) -> None:
    path = _prefs(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"profile": {"exit_type": "Normal", "exited_cleanly": True}}), encoding="utf-8")
    assert _worker(tmp_path)._mark_our_profile_exited_cleanly() is False


def test_a_brand_new_profile_is_left_alone(tmp_path: Path) -> None:
    assert _worker(tmp_path)._mark_our_profile_exited_cleanly() is False
    assert not _prefs(tmp_path).exists(), "처음 뜨는 프로필에 파일을 지어내지 않는다"


def test_a_broken_preferences_file_does_not_stop_the_launch(tmp_path: Path) -> None:
    path = _prefs(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{ 깨진 json", encoding="utf-8")
    assert _worker(tmp_path)._mark_our_profile_exited_cleanly() is False


def test_the_spawn_path_marks_it_and_adds_no_automation_flag() -> None:
    """띄우는 길이 부르는지, 그리고 플래그(`--hide-crash-restore-bubble`)로 때우지 않았는지."""
    import inspect

    source = inspect.getsource(BrowserWorker._spawn_chrome)
    assert "self._mark_our_profile_exited_cleanly()" in source
    assert "--hide-crash-restore-bubble" not in source.split('"""', 2)[-1]
