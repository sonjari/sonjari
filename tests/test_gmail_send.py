from __future__ import annotations

import base64
import email
import json
import time
from email.header import decode_header
from pathlib import Path

import httpx
import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.external_actions import ExternalActionStore
from alture_jarvis.google_workspace import GoogleWorkspace
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec


def _config(tmp_path: Path) -> JarvisConfig:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed),
        google_write_enabled=True,
        external_action_ttl_sec=300,
        # google_token_path/google_client_secret_path use a default_factory
        # that ignores runtime_root and falls back to the real production
        # path unless explicitly overridden here -- without this, tests that
        # seed a token would silently overwrite the live OAuth token cache.
        google_client_secret_path=tmp_path / "google" / "client_secret.json",
        google_token_path=tmp_path / "google" / "token.dpapi",
    )


def _seed_token(config: JarvisConfig) -> None:
    from alture_jarvis.google_workspace import TokenVault

    vault = TokenVault(config.google_token_path)
    vault.save(
        {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "expires_at": time.time() + 3600,
        }
    )


class RequestRecorder:
    def __init__(self, response_body: dict | None = None, status_code: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.response_body = response_body or {"id": "msg-1", "threadId": "thread-1"}
        self.status_code = status_code

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status_code, json=self.response_body)

    @property
    def call_count(self) -> int:
        return len(self.requests)


def _workspace(tmp_path: Path, config: JarvisConfig, recorder: RequestRecorder | None = None):
    local_computer = LocalComputerTools(config)
    actions = ExternalActionStore(tmp_path / "data" / "jarvis.db")
    workspace = GoogleWorkspace(config, EventBus(), local_computer=local_computer, actions=actions)
    if recorder is not None:
        workspace._transport = httpx.MockTransport(recorder.handler)
    return workspace, actions


def test_prepare_send_requires_at_least_one_recipient(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config)
    with pytest.raises(ValueError, match="recipient_required"):
        workspace.gmail_prepare_send({"to": [], "subject": "hi", "body_text": "hi"})


def test_prepare_send_blocks_crlf_header_injection_in_subject(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config)
    with pytest.raises(ValueError, match="header_injection"):
        workspace.gmail_prepare_send(
            {"to": ["a@example.com"], "subject": "hi\r\nBcc: evil@example.com", "body_text": "hi"}
        )


def test_prepare_send_blocks_crlf_in_recipient(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config)
    with pytest.raises(ValueError, match="header_injection"):
        workspace.gmail_prepare_send(
            {"to": ["a@example.com\r\nBcc:evil@example.com"], "subject": "hi", "body_text": "hi"}
        )


def test_prepare_send_rejects_invalid_email(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config)
    with pytest.raises(ValueError, match="invalid_email_address"):
        workspace.gmail_prepare_send({"to": ["not-an-email"], "subject": "hi", "body_text": "hi"})


def test_prepare_send_deduplicates_recipients(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, actions = _workspace(tmp_path, config)
    result = workspace.gmail_prepare_send(
        {"to": ["a@example.com", "A@Example.com"], "subject": "hi", "body_text": "hi"}
    )
    action = actions.get_prepared_action(result["action_id"])
    assert action["payload"]["to"] == ["a@example.com"]


def test_prepare_send_blocks_attachment_outside_allowed_root(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config)
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(PermissionError, match="outside"):
        workspace.gmail_prepare_send(
            {
                "to": ["a@example.com"],
                "subject": "hi",
                "body_text": "hi",
                "attachments": [str(outside)],
            }
        )


def test_prepare_send_blocks_oversized_attachment(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.gmail_attachment_max_bytes = 10
    workspace, _ = _workspace(tmp_path, config)
    allowed = Path(config.local_file_allowed_roots)
    big_file = allowed / "big.txt"
    big_file.write_bytes(b"x" * 100)
    with pytest.raises(ValueError, match="too_large"):
        workspace.gmail_prepare_send(
            {
                "to": ["a@example.com"],
                "subject": "hi",
                "body_text": "hi",
                "attachments": [str(big_file)],
            }
        )


def test_prepare_send_returns_action_id_and_preview_without_side_effects(tmp_path: Path) -> None:
    config = _config(tmp_path)
    recorder = RequestRecorder()
    workspace, actions = _workspace(tmp_path, config, recorder)
    result = workspace.gmail_prepare_send(
        {"to": ["a@example.com"], "cc": ["b@example.com"], "subject": "제목", "body_text": "본문"}
    )
    assert result["action_id"]
    assert result["requires_approval"] is True
    assert result["preview"]["to"] == ["a@example.com"]
    assert recorder.call_count == 0
    action = actions.get_prepared_action(result["action_id"])
    assert action["status"] == "prepared"


def test_mime_korean_subject_round_trips(tmp_path: Path) -> None:
    payload = {
        "to": ["a@example.com"],
        "cc": [],
        "bcc": [],
        "subject": "안녕하세요 JARVIS 테스트",
        "body_text": "본문 내용입니다.",
        "body_html": "",
        "attachments": [],
    }
    raw = GoogleWorkspace._build_gmail_mime(payload)
    message = email.message_from_bytes(raw)
    decoded_parts = decode_header(message["Subject"])
    subject = "".join(
        part.decode(encoding or "utf-8") if isinstance(part, bytes) else part
        for part, encoding in decoded_parts
    )
    assert subject == "안녕하세요 JARVIS 테스트"
    assert message["To"] == "a@example.com"


def test_mime_multi_recipient_and_attachment(tmp_path: Path) -> None:
    attachment_path = tmp_path / "note.txt"
    attachment_path.write_text("첨부 내용", encoding="utf-8")
    payload = {
        "to": ["a@example.com", "b@example.com"],
        "cc": ["c@example.com"],
        "bcc": ["d@example.com"],
        "subject": "multi",
        "body_text": "hello",
        "body_html": "",
        "attachments": [{"path": str(attachment_path), "name": "note.txt", "size": attachment_path.stat().st_size}],
    }
    raw = GoogleWorkspace._build_gmail_mime(payload)
    message = email.message_from_bytes(raw)
    assert message["To"] == "a@example.com, b@example.com"
    assert message["Cc"] == "c@example.com"
    assert message["Bcc"] == "d@example.com"
    assert message.is_multipart()
    filenames = [part.get_filename() for part in message.walk() if part.get_filename()]
    assert "note.txt" in filenames


def test_send_commits_exactly_once_via_mock_transport(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    recorder = RequestRecorder()
    workspace, actions = _workspace(tmp_path, config, recorder)
    prepared = workspace.gmail_prepare_send(
        {"to": ["a@example.com"], "subject": "hi", "body_text": "hi"}
    )
    assert recorder.call_count == 0

    result = workspace.gmail_send({"action_id": prepared["action_id"]})
    assert result["message_id"] == "msg-1"
    assert recorder.call_count == 1

    action = actions.get_prepared_action(prepared["action_id"])
    assert action["status"] == "committed"

    request = recorder.requests[0]
    assert request.method == "POST"
    body = json.loads(request.content)
    decoded = base64.urlsafe_b64decode(body["raw"] + "===")
    assert b"hi" in decoded


def test_send_is_idempotent_on_repeat_commit(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    recorder = RequestRecorder()
    workspace, _ = _workspace(tmp_path, config, recorder)
    prepared = workspace.gmail_prepare_send(
        {"to": ["a@example.com"], "subject": "hi", "body_text": "hi"}
    )
    first = workspace.gmail_send({"action_id": prepared["action_id"]})
    second = workspace.gmail_send({"action_id": prepared["action_id"]})

    assert recorder.call_count == 1
    assert first["message_id"] == second["message_id"]
    assert second["duplicate_commit"] is True


def test_send_without_prior_prepare_fails(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    recorder = RequestRecorder()
    workspace, _ = _workspace(tmp_path, config, recorder)
    with pytest.raises(RuntimeError, match="not_found_or_expired"):
        workspace.gmail_send({"action_id": "does-not-exist"})
    assert recorder.call_count == 0


def test_scope_insufficient_surfaces_reconnect_error(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    recorder = RequestRecorder(status_code=403)
    workspace, actions = _workspace(tmp_path, config, recorder)
    prepared = workspace.gmail_prepare_send(
        {"to": ["a@example.com"], "subject": "hi", "body_text": "hi"}
    )
    with pytest.raises(RuntimeError, match="google_scope_insufficient_reconnect_required"):
        workspace.gmail_send({"action_id": prepared["action_id"]})
    action = actions.get_prepared_action(prepared["action_id"])
    assert action["status"] == "failed"


def test_unapproved_commit_never_reaches_network_via_tool_gateway(tmp_path: Path) -> None:
    """The generic ToolGateway L2 nonce gate must block google_gmail_send
    entirely before our handler (and therefore the network) is ever touched."""
    config = _config(tmp_path)
    _seed_token(config)
    recorder = RequestRecorder()
    workspace, _ = _workspace(tmp_path, config, recorder)

    store = JobStore(tmp_path / "data" / "gateway.db")
    events = EventBus()
    gateway = ToolGateway(store, events)
    gateway.register(
        ToolSpec(
            name="google_gmail_send",
            description="",
            risk_level=RiskLevel.L2,
            handler=workspace.gmail_send,
        )
    )
    prepared = workspace.gmail_prepare_send(
        {"to": ["a@example.com"], "subject": "hi", "body_text": "hi"}
    )

    result = gateway.execute("google_gmail_send", {"action_id": prepared["action_id"]})

    assert result.status == "approval_required"
    assert result.approval_nonce
    assert recorder.call_count == 0
