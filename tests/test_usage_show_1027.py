"""「쓰는 법」 쇼의 「봤다」 (2026-10-27 대표 · 설계서 generated_reports/usage_show_1027/설계서.md).

지키는 것: 처음 깐 사람은 마법사를 마친 뒤 · 이미 쓰던 사람은 다음에 켤 때 **한 번** · 본 뒤에는 안 뜬다 ·
판 번호(「바뀐 것」)와 상관없다 · 기록이 깨져도 조용히 「안 봤다」로 · 쇼의 판을 올리면 다시 뜬다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis import usage_show
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig


def test_a_person_still_in_the_wizard_is_not_shown_the_show(tmp_path: Path) -> None:
    assert usage_show.status(tmp_path, setup_done=False) == {"show": False, "version": usage_show.SHOW_VERSION, "seen": 0}


def test_shown_once_after_setup_then_never_again(tmp_path: Path) -> None:
    assert usage_show.status(tmp_path, setup_done=True)["show"] is True
    assert usage_show.mark_seen(tmp_path)["ok"] is True
    after = usage_show.status(tmp_path, setup_done=True)
    assert after["show"] is False and after["seen"] == usage_show.SHOW_VERSION


@pytest.mark.parametrize("raw", ["", "not json", "[1]", '{"version": "x"}', '{"version": true}', '{"version": -3}'])
def test_a_broken_record_means_not_seen(tmp_path: Path, raw: str) -> None:
    (tmp_path / usage_show.SEEN_NAME).write_text(raw, encoding="utf-8")
    assert usage_show.read_seen(tmp_path) == 0
    assert usage_show.status(tmp_path, setup_done=True)["show"] is True


def test_a_newer_show_version_is_shown_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    usage_show.mark_seen(tmp_path)
    monkeypatch.setattr(usage_show, "SHOW_VERSION", usage_show.SHOW_VERSION + 1)
    assert usage_show.status(tmp_path, setup_done=True)["show"] is True


def test_the_record_is_its_own_file_not_the_whats_new_one(tmp_path: Path) -> None:
    from alture_jarvis import whats_new

    usage_show.mark_seen(tmp_path)
    assert usage_show.SEEN_NAME != whats_new.SEEN_NAME
    assert whats_new.read_seen(tmp_path) is None


def test_the_api_shows_once_after_the_wizard(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = create_app(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    ), start_services=False)
    client = TestClient(app)
    headers = {"X-Jarvis-Token": "test-token"}
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    # 마법사 중(설정 기록이 없음) — 안 뜬다
    assert client.get("/v1/usage-show", headers=headers).json()["show"] is False
    (tmp_path / "data" / "setup_state.json").write_text(json.dumps({"completed": True, "steps": []}), encoding="utf-8")
    assert client.get("/v1/usage-show", headers=headers).json()["show"] is True
    assert client.post("/v1/usage-show/seen", headers=headers).json()["ok"] is True
    assert client.get("/v1/usage-show", headers=headers).json()["show"] is False
    # 토큰 없이는 못 연다
    assert client.get("/v1/usage-show").status_code in (401, 403)
