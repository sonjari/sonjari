"""말한 답이 전체화면에 붙어야 한다 — 구석 팝업이 아니라.

2026-08-05 2차 실측: 마이크로 말하면 받아쓰기는 전체화면에 뜨는데 **답변은 작은
팝업으로 밀려났다.** 음성 잡의 origin 이 언제나 "voice" 였고, 작은 HUD 는 voice 를
자기 것으로 알고 패널을 펼치도록 되어 있었기 때문이다(hudMachine: origin==="workspace"
일 때만 비켜선다).

그래서 "누가 보고 있는가"를 백엔드가 알아야 한다. 화면이 주기적으로 자기 존재와 보고
있는 대화를 알려 오고, 음성 잡은 그 판정에 따라 origin 을 받는다. 화면이 꺼졌으면
다시 팝업으로 — 그때는 그게 유일하게 보이는 창이기 때문이다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig


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


def _speak(runtime, session: str, text: str = "안녕") -> dict[str, object]:
    runtime.recorder = _FakeRecorder()
    runtime.ptt_toggle(session)
    runtime.stt = type("_Fake", (), {"transcribe": staticmethod(lambda _p: {"text": text})})()
    audio = runtime.config.output_dir / "recordings" / "ptt-test.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"")
    job = runtime.store.create_job("transcribe_command", "음성 명령", {"path": str(audio)})
    return runtime._transcribe_command_job(job)


def test_presence_is_empty_before_the_workspace_says_anything(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    assert runtime.workspace_session() == ""


def test_the_workspace_says_which_conversation_it_is_showing(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.note_workspace_presence("jarvis-abc123")
    assert runtime.workspace_session() == "jarvis-abc123"


def test_presence_goes_stale(tmp_path: Path) -> None:
    """창을 닫아도 마지막 신호가 영원히 남으면, 음성 답변이 아무 데도 안 뜬다."""
    runtime = _runtime(tmp_path)
    runtime.note_workspace_presence("jarvis-abc123")
    session, seen_at = runtime._workspace_presence
    runtime._workspace_presence = (session, seen_at - runtime.config.workspace_presence_ttl_sec - 5)
    assert runtime.workspace_session() == ""


def test_a_spoken_answer_belongs_to_the_screen_that_is_watching(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.note_workspace_presence("jarvis-xyz789")

    result = _speak(runtime, "jarvis-xyz789")

    child = runtime.store.get_job(str(result["routed_job_id"]))
    assert child["payload"]["origin"] == "workspace", "전체화면이 보고 있는데 팝업으로 나갔다"


def test_the_screen_is_told_the_origin_too(tmp_path: Path) -> None:
    """화면이 잡을 자기 것으로 삼을 때 쓰는 이벤트에도 같은 판정이 실려야 한다."""
    runtime = _runtime(tmp_path)
    runtime.note_workspace_presence("jarvis-xyz789")

    _speak(runtime, "jarvis-xyz789")

    routed = [
        event.to_dict()
        for event in runtime.events.get_since(0, 500)
        if event.to_dict().get("event") == "voice_routed"
    ]
    assert routed[-1]["payload"]["origin"] == "workspace"


def test_without_a_live_workspace_it_stays_a_popup(tmp_path: Path) -> None:
    """창이 없으면 팝업이 맞다. 이걸 뒤집으면 답이 갈 곳이 아예 없어진다."""
    runtime = _runtime(tmp_path)

    result = _speak(runtime, "jarvis-xyz789")

    child = runtime.store.get_job(str(result["routed_job_id"]))
    assert child["payload"]["origin"] == "voice"


def test_a_workspace_looking_elsewhere_does_not_claim_it(tmp_path: Path) -> None:
    """F9 로 다른 대화에 말했는데 화면은 딴 대화를 보고 있는 경우. 화면에 안 붙을
    답을 화면 것이라고 표시하면, 어디에도 안 뜬다."""
    runtime = _runtime(tmp_path)
    runtime.note_workspace_presence("jarvis-other")

    result = _speak(runtime, "jarvis-xyz789")

    child = runtime.store.get_job(str(result["routed_job_id"]))
    assert child["payload"]["origin"] == "voice"


def test_the_endpoint_records_presence(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

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
    app = create_app(config, start_services=False)
    client = TestClient(app)

    response = client.post(
        "/v1/ui/presence",
        json={"session_id": "jarvis-live"},
        headers={"X-JARVIS-TOKEN": "test-token"},
    )

    assert response.status_code == 200
    assert app.state.jarvis.workspace_session() == "jarvis-live"
    assert client.post("/v1/ui/presence", json={"session_id": "x"}).status_code == 401
