"""`/health` 는 손자리가 **쓸** 창 크기를 알린다 — 워치독이 그 값으로 깨워야 다음 질문이 러너를 안 갈아 끼운다 (2026-09-30).

이 PC 의 사용자 환경변수에 `JARVIS_OLLAMA_NUM_CTX=65536`·`JARVIS_OLLAMA_CODE_MODEL=qwen3.8` 이 남아 있었고, 손자리는
3.6·32768 이었다. 워치독은 환경변수를 믿었다. 아무것도 안 올라와 있을 때 65536 으로 깨우면 다음 질문은 32768 로 다시 올린다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from types import SimpleNamespace

import alture_jarvis.ollama as ollama_module
from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient


class _FakeHttp:
    def __init__(self, *_a, **_kw) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def get(self, url: str):
        body = {"models": [{"name": "qwen3.6:35b-a3b"}]} if url.endswith("/api/tags") else {"models": []}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)


def test_health_carries_the_context_sonjari_will_use(tmp_path: Path, monkeypatch) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o", control_token="t")
    config.model_roles = {"chat": "qwen3.6:35b-a3b", "code": "qwen3.6:35b-a3b"}
    monkeypatch.setattr(ollama_module.httpx, "Client", _FakeHttp)

    health = OllamaClient(config).health()

    assert health["ok"] is True
    assert health["num_ctx"] == {"chat": config.num_ctx_for("chat"), "code": config.num_ctx_for("code")}
    assert all(isinstance(v, int) and v > 0 for v in health["num_ctx"].values())


def test_the_watchdog_prefers_health_over_stale_environment() -> None:
    """워치독이 /health 의 roles·num_ctx 를 환경변수보다 먼저 쓴다 — 글자로 묶어 둔다(PS1 은 여기서 못 돌린다)."""
    # 워치독은 이 제품 폴더 밖(운영 저장소 뿌리)의 스크립트다 — 떼어 낸 공개판에는 없다. 없으면 건너뛴다.
    here = Path(__file__).resolve()
    watchdog = here.parents[3] / "scripts" / "watchdog_ollama.ps1" if len(here.parents) > 3 else None
    if watchdog is None or not watchdog.is_file():
        pytest.skip("운영 저장소의 워치독 스크립트가 없다(떼어 낸 공개판)")
    script = watchdog.read_text(encoding="utf-8-sig")

    assert "$h.num_ctx.chat" in script and "$h.roles.code" in script
    assert "llama-server" in script and "AddMinutes(-5)" in script  # 올리는 중이면 안 깨운다
    assert "다른 모델이 올라와 있다" in script  # 남의 모델이 있으면 안 깨운다
