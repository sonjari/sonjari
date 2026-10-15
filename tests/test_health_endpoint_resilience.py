"""헬스체크는 "앱이 죽음"과 "한 군데가 아픔"을 구별해야 한다.

2026-08-08 실측: 자비스 `/health` 가 500 을 돌려주고 있었다. `/` · `/v1/state` ·
`/v1/tools` 는 전부 200 이었고, MCP 브리지로 실제 검색까지 됐다 — **앱은 멀쩡했다.**
헬스체크만 죽어 있었고, 그 둘은 워치독에게 같은 얼굴이다.

사고 P 의 거울상이다. 그때는 워치독이 `/api/tags` 만 봐서 **얼어붙은 것을 살았다고**
읽었다. 이번엔 반대로 **멀쩡한 것을 죽었다고** 읽는다. 방향만 다르고 같은 고장이다.

원인이 둘이었다.

**하나 — PATH 가 부를 때마다 자랐다.** `_configure_cuda_dll_paths()` 가 CUDA 경로를
`PATH` 앞에 **그대로 덧붙였다.** 이 함수는 `dependency_status()` 가 부르고 그건
`/health` 가 부른다. 즉 헬스체크를 부를 때마다 PATH 가 길어져, 윈도우 상한(32767자)에
닿는 순간 `ValueError` 로 터진다. 시간이 지나야 터지는 종류라 처음엔 멀쩡해 보인다.

**둘 — 한 칸이 터지면 전체가 500.** `health()` 는 20여 개 하위 시스템을 부르는데
격리가 없었다. STT 하나 때문에 나머지 19개의 상태도 같이 사라졌다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from alture_jarvis import voice as voice_module


# ---- 하나: PATH 누수 ---------------------------------------------------------

def _fake_cuda_tree(tmp_path: Path) -> Path:
    root = tmp_path / "Lib" / "site-packages" / "nvidia"
    for name in ("cuda_runtime", "cublas", "cudnn"):
        (root / name / "bin").mkdir(parents=True)
    return tmp_path


def test_repeated_calls_do_not_grow_path(tmp_path: Path, monkeypatch) -> None:
    """같은 경로를 두 번 넣지 않는다 — 이게 32767자 상한을 만들던 것이다."""
    if os.name != "nt":
        return  # 이 고장은 윈도우 전용이다
    monkeypatch.setattr(voice_module.sys, "prefix", str(_fake_cuda_tree(tmp_path)))
    monkeypatch.setattr(voice_module, "_DLL_HANDLES", [])
    monkeypatch.setattr(voice_module.os, "add_dll_directory", lambda p: None, raising=False)
    monkeypatch.setenv("PATH", "C:\\Windows")

    voice_module._configure_cuda_dll_paths()
    after_first = os.environ["PATH"]
    for _ in range(30):
        voice_module._configure_cuda_dll_paths()

    assert os.environ["PATH"] == after_first, (
        "부를 때마다 PATH 가 자라면 헬스체크를 부르는 것만으로 언젠가 반드시 터진다"
    )


def test_the_paths_are_actually_added_once(tmp_path: Path, monkeypatch) -> None:
    # 누수를 막느라 아예 안 넣으면 CUDA 를 못 찾는다 — 반대 방향도 잠근다.
    if os.name != "nt":
        return
    monkeypatch.setattr(voice_module.sys, "prefix", str(_fake_cuda_tree(tmp_path)))
    monkeypatch.setattr(voice_module, "_DLL_HANDLES", [])
    monkeypatch.setattr(voice_module.os, "add_dll_directory", lambda p: None, raising=False)
    monkeypatch.setenv("PATH", "C:\\Windows")

    added = voice_module._configure_cuda_dll_paths()

    assert len(added) == 3
    for path in added:
        assert path in os.environ["PATH"].split(os.pathsep)


# ---- 둘: 한 칸이 아파도 나머지는 보인다 ---------------------------------------

def _probe():
    """`_probe` 만 떼어 온다 — 진짜 런타임을 세우면 하드웨어가 딸려 온다.

    모듈 최상단이 아니라 함수 안에서 가져오는 것은 일부러다. 최상단에서 없는 속성을
    건드리면 **수집 단계에서 파일 전체가 죽어**, 같은 파일의 다른 테스트(PATH 누수)가
    아예 돌지도 않는다 — 고치기 전 코드로 역검증할 때 그게 드러났다.
    """
    from alture_jarvis.runtime import JarvisRuntime
    return JarvisRuntime._probe


def test_a_sick_subsystem_becomes_an_entry_not_an_exception() -> None:
    def boom() -> Any:
        raise ValueError("the environment variable is longer than 32767 characters")

    result = _probe()("stt", boom)

    assert result["ok"] is False
    assert result["probe"] == "stt"
    assert "32767" in result["error"], "무엇이 아픈지 안 적으면 짚어 줄 수가 없다"


def test_a_healthy_subsystem_is_passed_through_untouched() -> None:
    payload = {"ok": True, "enabled": True, "model_loaded": False}

    assert _probe()("stt", lambda: payload) == payload


def test_one_broken_probe_does_not_hide_the_others() -> None:
    """STT 하나 때문에 나머지 19개 상태가 같이 사라지던 것이 이번 사고였다."""
    def boom() -> Any:
        raise RuntimeError("cuda gone")

    report = {
        "ollama": _probe()("ollama", lambda: {"ok": True}),
        "stt": _probe()("stt", boom),
        "browser": _probe()("browser", lambda: {"ok": True, "started": True}),
    }

    assert report["ollama"]["ok"] is True
    assert report["browser"]["started"] is True
    assert report["stt"]["ok"] is False
