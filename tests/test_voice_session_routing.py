"""말한 것은 지금 보고 있는 대화로 들어가야 한다.

2026-08-05 실측: 워크스페이스에서 마이크를 눌러 말했더니 받아쓰기도 답변도 화면에
안 나타났다. 고장이 아니라 **다른 대화로 들어가고 있었다** — 음성 경로가 세션을
`office-main` 으로 하드코딩하고 있어서, 워크스페이스가 보고 있는 새 대화는 빈 채로
"생각하는 중"만 돌았다. 그때 만들어진 1,530자짜리 답변은 아무도 못 봤다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.models import JarvisState


def _runtime(tmp_path: Path):
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )
    return create_app(config, start_services=False).state.jarvis


class _FakeRecorder:
    def start(self) -> dict[str, object]:
        return {"ok": True, "device": "fake"}

    def stop(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def test_the_workspace_session_is_remembered_when_the_mic_starts(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.recorder = _FakeRecorder()

    runtime.ptt_toggle("jarvis-abc123")

    assert runtime._voice_session_id == "jarvis-abc123"


def test_the_hotkey_inherits_that_session(tmp_path: Path) -> None:
    """F9는 본문을 못 보낸다. 사용자는 화면 하나를 보고 있지 세션을 나눠 생각하지
    않으므로, 마지막으로 보던 대화를 이어 쓴다."""
    runtime = _runtime(tmp_path)
    runtime.recorder = _FakeRecorder()
    runtime.ptt_toggle("jarvis-abc123")
    runtime.state.transition(JarvisState.IDLE, "test")

    runtime.ptt_toggle()  # 세션 없이 (F9)

    assert runtime._voice_session_id == "jarvis-abc123"


def test_without_a_workspace_it_falls_back_to_the_default_session(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    assert runtime._voice_session_id == ""
    # _transcribe_command_job 이 이 값을 그대로 쓰므로, 빈 값이면 기본 대화로 간다.
    assert runtime.config.conversation_session_id


def test_a_spoken_command_lands_in_the_remembered_session(tmp_path: Path) -> None:
    """받아쓰기 -> 채팅 잡으로 넘어갈 때 세션이 따라가는지. 이게 이번 사고의 핵심이다."""
    runtime = _runtime(tmp_path)
    runtime.recorder = _FakeRecorder()
    runtime.ptt_toggle("jarvis-xyz789")
    runtime.stt = type(
        "_Fake", (), {"transcribe": staticmethod(lambda _path: {"text": "오늘 일정 알려줘"})}
    )()

    audio = tmp_path / "outputs" / "recordings" / "ptt-test.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"")
    job = runtime.store.create_job("transcribe_command", "음성 명령", {"path": str(audio)})
    result = runtime._transcribe_command_job(job)

    child = runtime.store.get_job(str(result["routed_job_id"]))
    assert child["payload"]["session_id"] == "jarvis-xyz789"
    assert child["payload"]["origin"] == "voice"


def test_the_screen_is_told_which_job_to_adopt(tmp_path: Path) -> None:
    """화면은 자기가 만든 작업만 그린다. 음성 작업은 화면이 만들지 않았으므로,
    '이 잡이 네 세션 것이다'라고 알려주지 않으면 영영 안 붙는다."""
    runtime = _runtime(tmp_path)
    runtime.recorder = _FakeRecorder()
    runtime.ptt_toggle("jarvis-xyz789")
    runtime.stt = type(
        "_Fake", (), {"transcribe": staticmethod(lambda _path: {"text": "안녕"})}
    )()
    audio = tmp_path / "outputs" / "recordings" / "ptt-test2.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"")

    job = runtime.store.create_job("transcribe_command", "음성 명령", {"path": str(audio)})
    result = runtime._transcribe_command_job(job)

    events = [e.to_dict() for e in runtime.events.get_since(0, 500)]
    routed = [e for e in events if e.get("event") == "voice_routed"]
    assert routed, "voice_routed 이벤트가 없으면 화면이 작업을 못 알아본다"
    payload = routed[-1]["payload"]
    assert payload["session_id"] == "jarvis-xyz789"
    assert payload["job_id"] == result["routed_job_id"]
    assert payload["transcript"] == "안녕"
