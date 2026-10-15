"""Ollama 켜기는 한 번에 한 사람만 — 설치 직후 「설치하지 못했습니다 (serve_exited:1)」가 뜬 까닭 (2026-10-05).

AWS 영어 윈도우(Tesla T4) 새 PC 첫 실행. 「Install Ollama」를 누르자 화면이 이렇게 지나갔다:

    Couldn't install (serve_exited:1)            ← 실패라고 말함
    Ollama 0.35.1 is running — using it as is.   ← 곧바로: 멀쩡히 돌고 있음(그런데 「남의 것」이라고 함)

원격 기록: `current.json` 18:08:12 → 우리 폴더의 `ollama.exe serve` 하나가 18:08:15 부터 살아 있음(부모 = 백엔드).
설치가 끝나는 순간 설치 스레드와 지킴이(`OllamaKeeper` — 화면이 `/health` 를 물을 때 켠다)가 **같이** 켰고,
포트를 못 잡은 쪽이 코드 1로 죽으면서 실패 문구를 남기고 `_process` 를 덮어썼다.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from alture_jarvis.ollama_install import OllamaInstaller

CLOSED = "http://127.0.0.1:9"


class _Process:
    def __init__(self, pid: int, exit_code: int | None = None) -> None:
        self.pid, self.returncode = pid, exit_code

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout=None):
        return 0


def _installed(tmp_path: Path, popen) -> OllamaInstaller:
    root = tmp_path / "engine" / "ollama"
    (root / "v0.35.1" / "lib" / "ollama").mkdir(parents=True)
    (root / "v0.35.1" / "ollama.exe").write_bytes(b"MZ")
    (root / "v0.35.1" / "lib" / "ollama" / "llama-server.exe").write_bytes(b"MZ")
    (root / "current.json").write_text(json.dumps({"folder": "v0.35.1", "version": "v0.35.1"}), encoding="utf-8")
    installer = OllamaInstaller(install_root=root, base_url=CLOSED, popen=popen)
    installer.clear_orphan_runners = lambda: []  # type: ignore[method-assign]
    installer._kill = lambda pid: None  # type: ignore[method-assign]
    return installer


def test_two_callers_at_once_start_one_server(tmp_path: Path) -> None:
    started: list[_Process] = []
    both_looked = threading.Barrier(2)

    def popen(args, **kwargs):
        process = _Process(4000 + len(started))
        started.append(process)
        return process

    installer = _installed(tmp_path, popen)

    def running_version() -> str:
        # 둘이 **같은 순간에** 「안 돌고 있다」를 보게 한다 — 그게 원격에서 벌어진 일이다.
        if not started:
            try:
                both_looked.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass
        return "0.35.1" if started else ""

    installer.running_version = running_version  # type: ignore[method-assign]
    results: list[dict] = []
    threads = [threading.Thread(target=lambda: results.append(installer.serve(wait_sec=5))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert len(started) == 1, "설치 스레드와 지킴이가 같이 불러도 서버는 하나만 띄운다"
    assert [bool(r.get("ok")) for r in results] == [True, True]
    assert installer.status()["managed"] is True, "우리가 켠 것을 남의 것으로 알면 끌 때도 못 끈다"
    installer.stop()


def test_our_server_died_but_another_one_answers_is_not_a_failure(tmp_path: Path) -> None:
    installer = _installed(tmp_path, lambda args, **kwargs: _Process(4001, exit_code=1))
    answers = iter(["", ""] + ["0.35.1"] * 20)   # 켜기 전 확인 · 띄운 직후 → 그 뒤로는 누군가 답한다
    installer.running_version = lambda: next(answers)  # type: ignore[method-assign]

    result = installer.serve(wait_sec=5)

    assert result == {"ok": True, "already_running": True}
    assert installer._process is None, "죽은 손잡이를 쥐고 있지 않는다"


def test_our_server_died_and_nobody_answers_is_still_an_error(tmp_path: Path) -> None:
    installer = _installed(tmp_path, lambda args, **kwargs: _Process(4002, exit_code=1))
    installer.SERVE_TAKEOVER_GRACE_SEC = 0.0  # type: ignore[misc]
    installer.running_version = lambda: ""  # type: ignore[method-assign]

    assert installer.serve(wait_sec=5) == {"ok": False, "error": "serve_exited:1"}
