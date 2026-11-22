"""답을 소리로 읽는 것은 **말로 들어온 일**뿐이다 — 그리고 호스트가 맡긴 판은 음성 합성을 기다리지 않는다.

★ 2026-09-29 헤르메스 T7 대결 뒤 계측: MCP 판 77개 중 64개가 답 전체를 음성으로 합성하느라 완료를 가운데값 5.7초 붙잡았다
(판 끝 꼬리 가운데값: 창에서 시킨 판 5.2초 · MCP 판 12.4초) → 호스트 판은 소리를 뒤로 돌렸다.
★ 2026-11-16 대표: 「바깥 AI 가 MCP 로 손자리를 부르면 최종 답이 무조건 소리로 나온다 · 윈도우에서도 계속 그랬다 —
STT 로 들어왔을 때만 TTS 로」. 이제 auto 는 받아쓰기가 만든 일(`spoken_input`)만 말하고, 나머지는 화면만.
부르는 쪽이 delivery="voice" 로 분명히 청하면 그대로 따른다(호스트 판이면 여전히 뒤에서).
"""
from __future__ import annotations

import threading
from typing import Any

from alture_jarvis.presentation import PresentationPolicy
from alture_jarvis.runtime import JarvisRuntime

ANSWER = "pager.py 와 slicer.py 를 고쳤고 pytest 9개가 전부 통과했습니다."


class _SlowTTS:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.spoken: list[str] = []
        self.last_metrics: dict[str, Any] = {"synthesis_ms": 5700}

    def synthesize(self, text: str, play: bool = True) -> str:
        self.release.wait(5)
        self.spoken.append(text)
        return "out.wav"


class _Events:
    def __init__(self) -> None:
        self.seen: list[tuple[str, dict[str, Any]]] = []
        self.done = threading.Event()

    def publish(self, name: str, payload: dict[str, Any]) -> None:
        self.seen.append((name, payload))
        if name == "presentation_speech_complete":
            self.done.set()


class _Media:
    def resume_after_interaction(self) -> None:
        pass


def _runtime() -> JarvisRuntime:
    runtime = JarvisRuntime.__new__(JarvisRuntime)
    runtime.presentation = PresentationPolicy(short_max_chars=200, short_max_speech_sec=60.0)
    runtime.tts = _SlowTTS()
    runtime.events = _Events()
    runtime.media = _Media()
    runtime._moves = []
    runtime._move = lambda state, reason: runtime._moves.append(reason)  # type: ignore[method-assign]
    runtime.config = type("C", (), {"supertonic_voice": "M1"})()
    runtime._session_id = lambda payload: "s"  # type: ignore[method-assign]
    return runtime


def test_an_mcp_job_answers_on_screen_only() -> None:
    """반례(대표 11-16): 클로드가 MCP 로 맡긴 판의 최종 답이 스피커로 나오면 안 된다."""
    runtime = _runtime()
    runtime.tts.release.set()
    job = {"id": "j1", "payload": {"origin": "mcp", "delivery": "auto"}}

    result = runtime._present(job=job, content=ANSWER, title="t")

    assert result["spoken_text"] == ""
    assert result["speech"]["requested"] is False
    assert runtime.tts.spoken == []


def test_a_typed_job_from_the_window_answers_on_screen_only() -> None:
    runtime = _runtime()
    runtime.tts.release.set()
    job = {"id": "j2", "payload": {"origin": "workspace", "delivery": "auto"}}

    result = runtime._present(job=job, content=ANSWER, title="t")

    assert result["speech"]["requested"] is False
    assert runtime.tts.spoken == []


def test_a_job_without_any_origin_does_not_speak_either() -> None:
    """출처가 비면 옛 코드는 「voice」로 쳤다 — 출처가 아니라 받아쓰기 표시로 가른다."""
    runtime = _runtime()
    runtime.tts.release.set()
    job = {"id": "j3", "payload": {"delivery": "auto"}}

    result = runtime._present(job=job, content=ANSWER, title="t")

    assert result["speech"]["requested"] is False
    assert runtime.tts.spoken == []


def test_a_spoken_job_still_speaks_before_it_finishes() -> None:
    runtime = _runtime()
    runtime.tts.release.set()
    job = {"id": "j4", "payload": {"origin": "workspace", "delivery": "auto", "spoken_input": True}}

    result = runtime._present(job=job, content=ANSWER, title="t")

    assert result["speech"]["requested"] is True and result["speech"].get("ok") is True
    assert runtime.tts.spoken == [result["spoken_text"]]


def test_a_host_that_asks_for_voice_gets_it_without_waiting() -> None:
    runtime = _runtime()
    job = {"id": "j5", "payload": {"origin": "mcp", "delivery": "voice"}}

    result = runtime._present(job=job, content=ANSWER, title="t")

    assert result["speech"] == {"requested": True, "status": "background"}
    assert runtime.tts.spoken == []                       # 아직 말하는 중 — 답은 이미 돌아왔다
    assert "tts" not in runtime._moves                    # 상태기계를 뺏지 않는다
    runtime.tts.release.set()
    assert runtime.events.done.wait(5)
    assert runtime.tts.spoken == [result["spoken_text"]]


def test_the_voice_route_marks_its_jobs_as_spoken() -> None:
    """받아쓰기 길이 만드는 일 두 갈래(조사 · 그 밖) 모두에 표시가 붙는다."""
    import inspect

    source = inspect.getsource(JarvisRuntime)
    start = source.index("voice_origin = ")
    block = source[start:start + 4000]
    assert block.count('"spoken_input": True') == 2
