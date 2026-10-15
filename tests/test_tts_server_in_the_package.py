"""**포장본에서는 우리가 목소리 서버를 켠다** (2026-09-18).

아버님 노트북 진단 파일에 `[WinError 10061]` — 음성 서버(:7788)가 아예 안 떠 있었다. 이 PC 는 작업
스케줄러가 켜 주지만 **스토어에서 받은 앱에는 그 작업이 없다.** 목소리 코드는 실려 있었는데 켤 사람이
없었던 것이고, 그동안 설정 화면은 「소리 내어 답하기: 켜짐」이라고 적고 있었다.

여기서 지키는 것 셋:
  · 이미 떠 있으면 **아무것도 하지 않는다**(두 개를 띄우면 포트가 부딪히고 한쪽이 조용히 죽는다)
  · 밖으로 열지 않는다 — 127.0.0.1 만
  · 못 켜도 막지 않는다. 음성 때문에 대화가 늦어지면 그건 고장이다
"""

from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis import tts_server


@pytest.fixture(autouse=True)
def _reset() -> Any:
    tts_server._CHILD = None
    tts_server._LAST_TRY = 0.0
    yield
    tts_server._CHILD = None
    tts_server._LAST_TRY = 0.0


def test_a_server_that_already_answers_is_left_alone(monkeypatch: Any) -> None:
    started: list[Any] = []
    monkeypatch.setattr(tts_server, "answering", lambda *_a, **_k: True)
    monkeypatch.setattr(tts_server.subprocess, "Popen", lambda *a, **k: started.append(a))

    result = tts_server.ensure("http://127.0.0.1:7788")

    assert result == {"ok": True, "already": True}
    assert not started, "떠 있는 서버를 또 띄우면 포트가 부딪힌다"


def test_it_starts_the_bundled_server_and_waits_for_a_real_answer(monkeypatch: Any) -> None:
    calls: list[list[str]] = []
    answers = iter([False, False, True])

    class _Child:
        returncode = None

        def poll(self) -> None:
            return None

    monkeypatch.setattr(tts_server, "answering", lambda *_a, **_k: next(answers, True))
    monkeypatch.setattr(tts_server, "available", lambda: True)
    monkeypatch.setattr(tts_server.subprocess, "Popen", lambda command, **_k: calls.append(command) or _Child())
    monkeypatch.setattr(tts_server.time, "sleep", lambda _s: None)

    result = tts_server.ensure("http://127.0.0.1:7788", wait_sec=5)

    assert result == {"ok": True, "started": True}
    command = calls[0]
    assert command[1:3] == ["-m", "alture_jarvis.tts_server"], "포장본에는 Scripts\\supertonic.exe 가 없다"
    assert "127.0.0.1" in command, "남의 PC 에 깔리는 판이 스스로 포트를 열면 안 된다"
    assert "7788" in command


def test_a_build_without_the_voice_code_says_so_instead_of_guessing(monkeypatch: Any) -> None:
    monkeypatch.setattr(tts_server, "answering", lambda *_a, **_k: False)
    monkeypatch.setattr(tts_server, "available", lambda: False)
    monkeypatch.setattr(tts_server.subprocess, "Popen", lambda *a, **k: pytest.fail("없는 것을 띄우려 들면 안 된다"))

    assert tts_server.ensure("http://127.0.0.1:7788") == {"ok": False, "error": "supertonic_not_bundled"}


def test_the_voice_button_falls_back_to_starting_it_ourselves(monkeypatch: Any, tmp_path: Any) -> None:
    """★ 고치는 길이 하나뿐이면 포장본에서는 고칠 방법이 없다 — 스케줄러가 안 되면 우리가 띄운다."""
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.events import EventBus
    from alture_jarvis.self_care import SelfCare

    care = SelfCare(JarvisConfig(runtime_root=tmp_path), EventBus())

    class _Ran:
        returncode = 1  # 포장본에는 그 작업이 없다
        stdout = "ERROR: The system cannot find the file specified."

    monkeypatch.setattr(care_module := __import__("alture_jarvis.self_care", fromlist=["x"]),
                        "subprocess", type("S", (), {"run": staticmethod(lambda *a, **k: _Ran())}))
    monkeypatch.setattr(care_module, "time", type("T", (), {"sleep": staticmethod(lambda _s: None)}))
    monkeypatch.setattr(tts_server, "ensure", lambda *_a, **_k: {"ok": True, "started": True})
    monkeypatch.setattr(tts_server, "answering", lambda *_a, **_k: False)

    result = care._restart_tts()

    assert result["bundled_start"] == {"ok": True, "started": True}


def test_the_runtime_starts_it_when_warming_up() -> None:
    """켤 때 음성이 준비되는 자리에서 서버도 챙긴다 — 사람이 말을 걸기 전에."""
    import inspect

    from alture_jarvis import runtime

    source = inspect.getsource(runtime.JarvisRuntime._warm_tts)
    assert "tts_server.ensure" in source and "answering" in source
