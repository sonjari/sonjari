from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.models import ApprovalStatus, JarvisState, JobStatus


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )


def _runtime(tmp_path: Path):
    return create_app(_config(tmp_path), start_services=False).state.jarvis


class _FakeRecorder:
    """Stands in for the sounddevice recorder, which needs real hardware."""

    def __init__(self, fail_on_start: bool = False) -> None:
        self.started = 0
        self.stopped = 0
        self.fail_on_start = fail_on_start

    def start(self) -> dict[str, object]:
        if self.fail_on_start:
            raise RuntimeError("no_input_device")
        self.started += 1
        return {"ok": True, "device": "fake"}

    def stop(self, path: Path) -> None:
        self.stopped += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def _park_on_approval(runtime, *, expires_in: float) -> str:
    """Recreate a chat job parked on an L2 approval."""
    job = runtime.store.create_job("chat", "메일 발송", {"prompt": "메일 보내줘"})
    runtime.store.set_status(job["id"], JobStatus.WAITING_APPROVAL)
    runtime.store.create_approval(
        nonce="nonce-test",
        job_id=str(job["id"]),
        tool_name="google_gmail_send",
        arguments={"action_id": "action-test"},
        expires_at=time.time() + expires_in,
    )
    runtime.state.transition(JarvisState.WORKING, "chat")
    runtime._move(JarvisState.WAITING_APPROVAL, "job_approval")
    return str(job["id"])


def test_denied_approval_releases_the_state_machine(tmp_path) -> None:
    # Denial cancels the job in the store, but no handler is running to notice.
    # Leaving the state busy here is what made the orb permanently unpressable.
    runtime = _runtime(tmp_path)
    job_id = _park_on_approval(runtime, expires_in=300)

    decision = runtime.decide_approval("nonce-test", False)

    assert decision is not None
    assert decision["status"] == ApprovalStatus.DENIED.value
    assert runtime.store.get_job(job_id)["status"] == JobStatus.CANCELLED.value
    assert runtime.state.snapshot().state is JarvisState.IDLE


def test_expired_approval_no_longer_holds_the_state_busy(tmp_path) -> None:
    # Nobody decides this one -- the popup was dismissed or the TTL ran out.
    runtime = _runtime(tmp_path)
    _park_on_approval(runtime, expires_in=-1)

    assert runtime.reconcile_state() is JarvisState.IDLE
    assert runtime.state.snapshot().state is JarvisState.IDLE


def test_reconcile_keeps_a_state_that_a_live_job_still_owns(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.store.create_job("chat", "조사", {"prompt": "조사해줘"})
    runtime.state.transition(JarvisState.WORKING, "chat")

    assert runtime.reconcile_state() is JarvisState.WORKING

    # A pending approval that has not expired is live work too.
    runtime.state.reset("test")
    _park_on_approval(runtime, expires_in=300)
    assert runtime.reconcile_state() is JarvisState.WAITING_APPROVAL


def test_ptt_toggle_is_decided_by_the_runtime_not_the_caller(tmp_path) -> None:
    # The hotkey used to keep its own start/stop flag. Stopping from the HUD
    # left that flag stuck on "recording", so every later F9 press tried to
    # stop a recording that was not running and silently failed.
    runtime = _runtime(tmp_path)
    recorder = _FakeRecorder()
    runtime.recorder = recorder

    assert runtime.ptt_toggle()["action"] == "started"
    assert runtime.state.snapshot().state is JarvisState.LISTENING

    assert runtime.ptt_toggle()["action"] == "stopped"
    assert recorder.stopped == 1
    assert runtime.state.snapshot().state is JarvisState.TRANSCRIBING

    # The transcribe job finishes and hands the state back.
    runtime.state.reset("voice_routed")
    assert runtime.ptt_toggle()["action"] == "started"
    assert recorder.started == 2


def test_toggle_after_a_stop_from_the_other_input_still_starts(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    recorder = _FakeRecorder()
    runtime.recorder = recorder

    runtime.ptt_toggle()
    # The HUD orb stops it directly instead of going through the toggle.
    runtime.ptt_stop()
    runtime.state.reset("voice_routed")

    assert runtime.ptt_toggle()["action"] == "started"
    assert recorder.started == 2
    assert recorder.stopped == 1


def test_a_recorder_that_refuses_to_start_does_not_wedge_the_state(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.recorder = _FakeRecorder(fail_on_start=True)

    with pytest.raises(RuntimeError):
        runtime.ptt_start()

    assert runtime.state.snapshot().state is JarvisState.IDLE
    # And the next press is still accepted.
    runtime.recorder = _FakeRecorder()
    assert runtime.ptt_toggle()["action"] == "started"


def test_state_endpoint_reports_a_reconciled_state(tmp_path) -> None:
    # The HUD polls this to resync after a dropped socket, so it must not hand
    # back a busy state that nothing can leave.
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    _park_on_approval(runtime, expires_in=-1)

    with TestClient(app) as client:
        assert client.get("/v1/state").json()["state"] == JarvisState.IDLE.value


def test_toggle_endpoint_round_trips(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    app.state.jarvis.recorder = _FakeRecorder()
    headers = {"X-JARVIS-TOKEN": "test-token"}

    with TestClient(app) as client:
        assert client.post("/v1/voice/ptt/toggle").status_code == 401
        assert client.post("/v1/voice/ptt/toggle", headers=headers).json()["action"] == "started"
        assert client.post("/v1/voice/ptt/toggle", headers=headers).json()["action"] == "stopped"
