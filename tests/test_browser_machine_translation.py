"""크롬 자동 번역 — 우리 프로필에서만 끄고, 번역된 화면은 알린다 (2026-09-18).

영어 페이지가 번역체로 읽혔다(OpenAI→「오픈아이」, Plans→「계략」). 온텔릭 프로필엔 번역 설정이 없었고,
사람의 크롬(Default)에 「영어는 항상 한국어로」가 켜져 있었다. 사람의 설정은 건드리지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                                      browser_profile_dir=tmp_path / "profile"))


def test_translate_is_turned_off_in_our_profile_and_other_settings_survive(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    prefs = tmp_path / "profile" / "Default" / "Preferences"
    prefs.parent.mkdir(parents=True)
    prefs.write_text(json.dumps({"intl": {"selected_languages": "ko-KR,ko,en-US,en"},
                                 "translate": {"some_key": 1}}), encoding="utf-8")
    assert worker._turn_off_translate_in_our_profile() is True
    saved = json.loads(prefs.read_text(encoding="utf-8"))
    assert saved["translate"] == {"some_key": 1, "enabled": False}
    assert saved["intl"]["selected_languages"] == "ko-KR,ko,en-US,en", "다른 설정은 그대로여야 한다"
    assert worker._turn_off_translate_in_our_profile() is False, "이미 꺼져 있으면 다시 쓰지 않는다"


def test_a_fresh_profile_gets_translate_off_before_first_launch(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    assert worker._turn_off_translate_in_our_profile() is True
    saved = json.loads((tmp_path / "profile" / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert saved == {"translate": {"enabled": False}}


def test_both_launch_paths_turn_translate_off_first() -> None:
    import inspect

    assert "_turn_off_translate_in_our_profile()" in inspect.getsource(BrowserWorker._spawn_chrome)
    assert "_turn_off_translate_in_our_profile()" in inspect.getsource(BrowserWorker._launch_chrome)


playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield launched
        launched.close()


def test_a_page_chrome_translated_is_flagged_and_an_ordinary_page_is_not(tmp_path: Path, browser, monkeypatch) -> None:
    worker = _worker(tmp_path)
    monkeypatch.setattr(worker, "_structured_data", lambda _page: None)
    monkeypatch.setattr(worker, "_note_trait", lambda *_a, **_k: None)
    page = browser.new_page()
    # 크롬 번역이 남기는 모양 그대로 — <html class="translated-ltr"> 와 <font> 감싸기
    page.set_content('<html class="translated-ltr" lang="ko"><body><p><font style="vertical-align: inherit;">오픈아이</font></p></body></html>')
    flagged = worker._attach_structured(page, {"text": "오픈아이"})
    assert flagged.get("machine_translated") is True
    assert "machine_translated" in flagged["instruction"]
    page.set_content("<html lang='en'><body><p>OpenAI</p></body></html>")
    plain = worker._attach_structured(page, {"text": "OpenAI"})
    assert "machine_translated" not in plain and "instruction" not in plain
    page.close()
