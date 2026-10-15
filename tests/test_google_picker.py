"""드라이브 파일 고르기 — Google Picker 데스크톱 흐름 (인수인계 H4).

공식 문서(2026-09-16 확인): 권한은 `drive.file` 단독, `prompt=consent` + `trigger_onepick=true` 필수,
고른 파일은 돌아오는 주소의 `picked_file_ids` 로 온다. 회사 Google Cloud 프로젝트로 실제 확인하기 전까지는
이 시험이 주소 모양과 콜백 처리만 지킨다.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.external_actions import ExternalActionStore
from alture_jarvis.google_workspace import DRIVE_FILE_SCOPE, GoogleWorkspace
from alture_jarvis.local_computer import LocalComputerTools


def _google(tmp_path: Path, monkeypatch) -> GoogleWorkspace:
    bundled = tmp_path / "resources" / "google_oauth_client.json"
    bundled.parent.mkdir(parents=True)
    bundled.write_text(json.dumps({"installed": {"client_id": "c.apps.googleusercontent.com", "project_id": "p"}}),
                       encoding="utf-8")
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", google_oauth_bundle_path=bundled,
                          google_client_secret_path=tmp_path / "none.json", google_token_path=tmp_path / "data" / "g.bin")
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)
    google = GoogleWorkspace(config, EventBus(), local_computer=LocalComputerTools(config),
                             actions=ExternalActionStore(tmp_path / "data" / "jarvis.db"))
    google._transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "expires_in": 3600}))
    monkeypatch.setattr(google, "profile", lambda: {})
    return google


def test_picker_asks_only_drive_file_with_the_required_flags(tmp_path: Path, monkeypatch) -> None:
    google = _google(tmp_path, monkeypatch)
    try:
        started = google.start_picker()
        query = parse_qs(urlparse(started["authorization_url"]).query)
        assert query["scope"] == [DRIVE_FILE_SCOPE]
        assert query["prompt"] == ["consent"] and query["trigger_onepick"] == ["true"]
    finally:
        google._finish_flow(False, "test_done")


def test_picked_ids_are_remembered_and_the_first_token_connects(tmp_path: Path, monkeypatch) -> None:
    google = _google(tmp_path, monkeypatch)
    started = google.start_picker()
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
    done = google._oauth_callback("/oauth2/callback?" + urlencode(
        {"state": state, "code": "x", "scope": DRIVE_FILE_SCOPE, "picked_file_ids": "f1,f2"}))
    assert done == {"ok": True, "picked": 2}
    assert {row["id"] for row in google.picked_files()} == {"f1", "f2"}
    assert google.vault.exists()
    assert google.status()["picked_files"] == 2
