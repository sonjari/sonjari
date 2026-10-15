"""Ollama 는 **알아서** 켜져 있어야 한다 (2026-09-20 사용자 요청 · 노트북 실측).

노트북 실측: 앱 창은 곧바로 뜨는데 백엔드가 Ollama 를 켜기까지 14초가 걸렸다. 그 사이 화면은
「로컬 AI 엔진(Ollama)에 닿지 않습니다」를 띄웠다 — 사용자에게는 고장이다(「사용자는 당황한다」).
그리고 켜기는 **백엔드 시작 때 딱 한 번**이었다. 도중에 Ollama 가 죽거나 트레이에서 끄면 다시 안 켰다.

그래서: 상태를 물을 때마다(화면이 몇 초마다 묻는다) 꺼져 있으면 우리가 깐 Ollama 를 다시 켠다.
켜는 중이면 「켜는 중」이라고 말하고, **연달아 실패했을 때만** 고장이라고 말한다(거짓 「준비 중」 금지).
"""

from __future__ import annotations

import threading
from pathlib import Path

from alture_jarvis.ollama_install import OllamaKeeper


class _Installer:
    def __init__(self, *, installed: bool = True, results: list[dict] | None = None, block: threading.Event | None = None):
        self.installed = installed
        self.results = list(results or [{"ok": True}])
        self.calls = 0
        self.block = block

    def bundled_exe(self):
        return Path("C:/x/ollama.exe") if self.installed else None

    def serve(self, wait_sec: float = 30.0):
        self.calls += 1
        if self.block is not None:
            self.block.wait(5)
        return self.results.pop(0) if self.results else {"ok": True}


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _keeper(installer, clock=None):
    return OllamaKeeper(installer, clock=clock or _Clock(), retry_sec=20.0, give_up_after=3, run=lambda f: f())


def test_a_down_engine_is_started_and_reported_as_starting_not_broken() -> None:
    installer = _Installer(block=threading.Event())
    keeper = OllamaKeeper(installer, clock=_Clock(), retry_sec=20.0, give_up_after=3)  # 진짜 스레드
    status = keeper.annotate({"ok": False, "error": "connection refused"})
    assert status["starting"] is True, "켜는 중인데 「닿지 않습니다」로 보이면 사용자는 고장으로 본다"
    # 켜는 중에 다시 물어도 두 번 켜지 않는다.
    again = keeper.annotate({"ok": False, "error": "connection refused"})
    assert again["starting"] is True
    installer.block.set()
    keeper.join(5)
    assert installer.calls == 1


def test_an_engine_that_died_later_is_started_again() -> None:
    """예전에는 시작할 때 한 번만 켰다 — 도중에 죽으면 끝이었다."""
    clock = _Clock()
    installer = _Installer(results=[{"ok": True}, {"ok": True}])
    keeper = _keeper(installer, clock)
    keeper.annotate({"ok": False})
    assert keeper.annotate({"ok": True})["ok"] is True
    clock.now += 600  # 한참 뒤 Ollama 가 죽었다
    status = keeper.annotate({"ok": False})
    assert status["starting"] is True and installer.calls == 2


def test_a_running_engine_is_left_alone() -> None:
    installer = _Installer()
    status = _keeper(installer).annotate({"ok": True, "model": "qwen3.5:4b"})
    assert installer.calls == 0 and "starting" not in status


def test_repeated_failure_is_reported_honestly_not_as_starting_forever() -> None:
    clock = _Clock()
    installer = _Installer(results=[{"ok": False, "error": "serve_exited:1"}] * 5)
    keeper = _keeper(installer, clock)
    for _ in range(3):
        keeper.annotate({"ok": False})
        clock.now += 21
    status = keeper.annotate({"ok": False})
    assert status["starting"] is False, "세 번 실패했는데 계속 「켜는 중」이면 거짓말이다"
    assert "serve_exited:1" in status["autostart_error"]


def test_without_our_install_there_is_nothing_to_start() -> None:
    """설치 안 된 PC — 켤 것이 없다. 첫 실행 화면으로 보내는 기존 안내가 맞다."""
    installer = _Installer(installed=False)
    status = _keeper(installer).annotate({"ok": False})
    assert status["starting"] is False and installer.calls == 0


def test_the_runtime_uses_the_keeper_for_health_and_at_start() -> None:
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    assert "ollama_keeper.annotate" in inspect.getsource(JarvisRuntime.health)
    start = inspect.getsource(JarvisRuntime.start)
    assert "ollama_keeper.annotate" in start or "ollama_keeper.ensure" in start
    assert "target=self.ollama_installer.serve" not in start, "한 번만 켜는 옛 길이 남으면 두 길이 겹쳐 두 번 켠다"
