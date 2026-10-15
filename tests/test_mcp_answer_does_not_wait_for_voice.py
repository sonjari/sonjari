"""호스트(클로드 등)가 맡긴 판은 **음성 합성을 기다리지 않고** 답을 돌려준다 — 소리는 뒤에서 그대로 난다.

★ 2026-09-29 헤르메스 T7 대결 뒤 계측: MCP 판 77개 중 64개가 답 전체를 음성으로 합성하느라 완료를 가운데값 5.7초 붙잡았다
(판 끝 꼬리 가운데값: 창에서 시킨 판 5.2초 · MCP 판 12.4초). 창에서 말로 시킨 판은 예전처럼 말을 끝낸 뒤 완료한다.
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


def test_an_mcp_job_returns_before_the_voice_is_made() -> None:
    runtime = _runtime()
    job = {"id": "j1", "payload": {"origin": "mcp", "delivery": "auto"}}

    result = runtime._present(job=job, content=ANSWER, title="t")

    assert result["speech"] == {"requested": True, "status": "background"}
    assert runtime.tts.spoken == []                       # 아직 말하는 중 — 답은 이미 돌아왔다
    assert "tts" not in runtime._moves                    # 상태기계를 뺏지 않는다
    runtime.tts.release.set()
    assert runtime.events.done.wait(5)
    assert runtime.tts.spoken == [result["spoken_text"]]  # 소리는 그대로 난다


def test_a_job_from_the_window_still_speaks_before_it_finishes() -> None:
    runtime = _runtime()
    runtime.tts.release.set()
    job = {"id": "j2", "payload": {"origin": "workspace", "delivery": "auto"}}

    result = runtime._present(job=job, content=ANSWER, title="t")

    assert result["speech"]["requested"] is True and result["speech"].get("ok") is True
    assert runtime.tts.spoken
