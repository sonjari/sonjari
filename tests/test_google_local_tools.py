from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.external_actions import ExternalActionStore
from alture_jarvis.google_workspace import GoogleWorkspace, TokenVault
from alture_jarvis.local_computer import LocalComputerTools


def _workspace(config: JarvisConfig, tmp_path: Path) -> GoogleWorkspace:
    local_computer = LocalComputerTools(config)
    actions = ExternalActionStore(tmp_path / "data" / "jarvis.db")
    return GoogleWorkspace(config, EventBus(), local_computer=local_computer, actions=actions)


def test_google_desktop_credentials_and_read_only_status(tmp_path: Path) -> None:
    secret = tmp_path / "google" / "client_secret.json"
    secret.parent.mkdir()
    secret.write_text(
        json.dumps(
            {
                "installed": {
                    "project_id": "alture-jarvis-local",
                    "client_id": "desktop.apps.googleusercontent.com",
                    "client_secret": "test-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        google_client_secret_path=secret,
        google_token_path=tmp_path / "google" / "token.dpapi",
    )
    workspace = _workspace(config, tmp_path)

    status = workspace.status()

    assert status["configured"] is True
    assert status["connected"] is False
    # A public install requests least-privilege scopes. Write scopes are not
    # requested until the user explicitly enables write access.
    assert status["mode"] == "read_only"
    # ★ 2026-09-16 (인수인계 H4): 제한 권한(drive.readonly·gmail.readonly)은 공개판에서 요청하지 않는다 —
    #   Google 연례 보안 평가(CASA) 대상. 드라이브는 사용자가 고른 파일만 보는 drive.file 로.
    read_only_or_identity_scopes = {
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/drive.file",
    }
    assert set(status["scopes"]) == read_only_or_identity_scopes


def test_token_vault_round_trip(tmp_path: Path) -> None:
    vault = TokenVault(tmp_path / "token.dpapi")
    value = {"access_token": "not-a-real-token", "expires_at": 123.0}

    vault.save(value)

    assert vault.load() == value
    assert vault.path.read_bytes() != json.dumps(value).encode("utf-8")


def test_local_files_are_allowlisted_and_sensitive_names_are_blocked(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    note = allowed / "meeting-notes.md"
    note.write_text("다음 회의 핵심 안건", encoding="utf-8")
    secret = allowed / "client_secret_example.json"
    secret.write_text("secret", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed),
        local_read_roots=str(allowed),
    )
    tools = LocalComputerTools(config)

    listed = tools.list_directory({"path": str(allowed)})
    searched = tools.search_files({"query": "meeting"})
    read = tools.read_text_file({"path": str(note)})

    assert [item["name"] for item in listed["items"]] == ["meeting-notes.md"]
    assert searched["items"][0]["path"] == str(note)
    assert "핵심 안건" in read["content"]
    with pytest.raises(PermissionError, match="outside"):
        tools.read_text_file({"path": str(outside)})
    with pytest.raises(PermissionError, match="sensitive"):
        tools.read_text_file({"path": str(secret)})
