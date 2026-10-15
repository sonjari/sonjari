"""점검이 모델을 **올린 뒤에** GPU 자리를 본다 (2026-09-30 촬영 판).

아무 모델도 안 떠 있을 때 켜면 micro_bench 가 모델을 GPU 에 올린다. 그런데 VRAM 은 재기 **전에** 받아 둔 빈 목록으로 세서
0GB → 「모델이 GPU 에 안 올라가 있습니다(CPU 로 돌고 있습니다)」가 떴다. 그때 /api/ps 는 14.4GB 전부 VRAM 이었다.
앱을 처음 켠 사람이 제일 먼저 보는 빨간 줄이라, 틀리면 안 되는 경고다 — 진짜 CPU 판은 여전히 잡아야 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.self_care import SelfCare

GIB = 1024**3


def _care(tmp_path: Path, monkeypatch, *, vram_after: int) -> SelfCare:
    config = JarvisConfig(runtime_root=tmp_path)
    loaded = {"on": False}

    class _Response:
        def __init__(self, body: dict) -> None:
            self.body = body
            self.content = b"{}"

        def json(self) -> dict:
            return self.body

    class _Client:
        def __init__(self, **kwargs) -> None: ...
        def __enter__(self): return self
        def __exit__(self, *args) -> None: return None

        def get(self, url: str) -> _Response:
            models = [{"name": config.ollama_model, "context_length": 131072, "size_vram": vram_after}] if loaded["on"] else []
            return _Response({"models": models})

        def post(self, url: str, json: dict) -> _Response:
            return _Response({"eval_count": 64, "eval_duration": 1_000_000_000})

    def _bench(base: str, model: str, ctx: int, *, keep_alive: str, post: Any) -> dict:
        loaded["on"] = True  # 재는 동안 모델이 올라간다
        return post(f"{base}/api/generate", {}, 60)

    monkeypatch.setattr("alture_jarvis.self_care.httpx.Client", _Client)
    monkeypatch.setattr("alture_jarvis.setup_profile.micro_bench", _bench)
    return SelfCare(config, EventBus(), tts=lambda: None, browser=lambda: None, google=lambda: None)


def test_a_model_loaded_by_the_check_itself_is_not_called_cpu(tmp_path: Path, monkeypatch) -> None:
    organ = _care(tmp_path, monkeypatch, vram_after=int(14.4 * GIB))._check_model()

    assert "CPU" not in str(organ.get("detail") or ""), organ
    assert organ["evidence"]["vram_gb"] == 14.4


def test_a_model_really_on_the_cpu_is_still_caught(tmp_path: Path, monkeypatch) -> None:
    organ = _care(tmp_path, monkeypatch, vram_after=0)._check_model()

    assert organ["state"] == "down"
    assert "CPU" in str(organ.get("detail") or "")
