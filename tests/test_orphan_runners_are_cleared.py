"""앱이 꺼질 때 모델 실행기(llama-server)가 **고아로 남아 그래픽 메모리를 쥐었다** (2026-09-20 노트북 실측).

RTX 5050 8GB · qwen3.5:4b. 업데이트 두 번(앱 강제 종료 두 번) 뒤:

    llama-server 25976   02:11 첫 실행    부모(Ollama) 죽음   4.5GB
    llama-server  7308   02:25 1차 업데이트 부모 죽음          0.2GB
    llama-server 26088   02:50 현재         부모 = 현재 Ollama  3.8GB   → 그래픽 메모리 7.76/8.15GB

현재 모델은 꽉 찬 메모리에 올라와 일부가 카드 밖에 얹혔다. 같은 1,265토큰 프롬프트 읽기가
**9.5~12.1초 → 고아 정리·모델 재적재 뒤 0.67초**, 생성 16 → 69 토큰/초. 온텔릭 답 20~48초의 정체가 이것이었다.

윈도우는 부모를 죽여도 자식을 안 죽인다. 앱이 강제로 꺼지면(업데이트 도우미의 `-ForceTargetApplicationShutdown`)
백엔드의 정리 코드는 돌지도 않는다. 그래서 **켤 때** 치운다 — 우리 엔진 폴더의 실행기 중 부모 Ollama 가
살아 있지 않은 것만. 사람이 따로 깐 Ollama 의 실행기는 경로가 달라 안 건드린다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.ollama_install import OllamaInstaller

ROOT = Path(r"C:\Users\u\Ontelic\engine\ollama")
OURS = str(ROOT / "v0.34.1" / "lib" / "ollama" / "llama-server.exe")
THEIRS = r"C:\Users\u\AppData\Local\Programs\Ollama\lib\ollama\llama-server.exe"


def _installer(rows: list[dict], killed: list[int]) -> OllamaInstaller:
    installer = OllamaInstaller(install_root=ROOT)
    installer._list_runners = lambda: rows  # type: ignore[method-assign]
    installer._kill = lambda pid: killed.append(pid)  # type: ignore[method-assign]
    return installer


def test_runners_whose_ollama_died_are_killed() -> None:
    killed: list[int] = []
    rows = [
        {"pid": 25976, "parent": 2960, "path": OURS, "parent_alive": False},
        {"pid": 7308, "parent": 30144, "path": OURS, "parent_alive": False},
        {"pid": 26088, "parent": 8352, "path": OURS, "parent_alive": True},
    ]
    assert _installer(rows, killed).clear_orphan_runners() == [25976, 7308]
    assert killed == [25976, 7308], "살아 있는 Ollama 의 실행기(지금 모델)까지 죽이면 그게 고장이다"


def test_someone_elses_ollama_is_never_touched() -> None:
    killed: list[int] = []
    rows = [{"pid": 11, "parent": 1, "path": THEIRS, "parent_alive": False}]
    assert _installer(rows, killed).clear_orphan_runners() == []
    assert killed == []


def test_serve_clears_orphans_before_starting(monkeypatch) -> None:
    calls: list[str] = []
    installer = OllamaInstaller(install_root=ROOT)
    monkeypatch.setattr(installer, "clear_orphan_runners", lambda: calls.append("clear") or [])
    monkeypatch.setattr(installer, "running_version", lambda: calls.append("probe") or "0.34.1")
    installer.serve()
    assert calls[0] == "clear", "고아를 먼저 치워야 새 모델이 카드에 온전히 올라간다"


def test_stop_takes_the_runner_down_with_ollama() -> None:
    """정상 종료 때도 `terminate()` 는 Ollama 만 죽였다 — 자식 실행기는 남았다."""
    import inspect

    source = inspect.getsource(OllamaInstaller.stop)
    assert "_kill(" in source or "taskkill" in source
