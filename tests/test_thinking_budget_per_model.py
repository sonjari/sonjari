"""생각 예산은 **모델마다** 다르다 (2026-09-20 이 PC · Qwen 3.6 35B-A3B).

8천 자 예산은 Gemma 4 기준이었다 — Gemma 는 턴당 생각이 2천 자 안팎이라 거의 안 걸렸다. Qwen 3.6 은 코워크 한 판(254초)에서
5턴 중 **4턴이 8천 자에서 끊겼고**(턴당 약 32초 생각), 끊은 뒤 생각 없이 다시 물으면 **4번 다 1~2초 만에** 제대로 된
다음 걸음을 냈다. 긴 생각이 거의 일을 안 했다. 그래서 모델 이름 앞부분으로 예산을 따로 준다(첫 값은 이 한 판의 증거 —
`thinking_budget_hits`·`model_time` 로 다시 잴 것).
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient


def test_qwen36_gets_a_shorter_budget_than_the_default(tmp_path: Path) -> None:
    client = OllamaClient(JarvisConfig(runtime_root=tmp_path))
    assert client._thinking_budget_for("qwen3.6:35b-a3b") == 3000
    assert client._thinking_budget_for("plopfit-gemma4-qat") == 8000


def test_the_override_is_read_from_the_environment_too(tmp_path: Path, monkeypatch) -> None:
    """★ 값이 사는 자리가 둘이다(dataclass·로더) — 한쪽만 고치면 헛돈다(사고 Q)."""
    monkeypatch.setenv("JARVIS_OLLAMA_THINKING_BUDGET_BY_MODEL", "qwen3.6=2000;gemma4=5000")
    config = JarvisConfig.from_env()
    client = OllamaClient(config)
    assert client._thinking_budget_for("qwen3.6:35b-a3b") == 2000
    assert client._thinking_budget_for("gemma4:26b-a4b-it-qat") == 5000


def test_the_stream_uses_the_model_budget_when_none_is_given() -> None:
    import inspect

    source = inspect.getsource(OllamaClient.chat_messages_stream)
    assert "self._thinking_budget_for(selected)" in source


def test_qwen36_is_in_the_catalog_with_what_we_measured() -> None:
    """목록에 없으면 사용자는 「직접 적기(고급)」로만 바꿀 수 있다 — 실제로 오늘 그랬다."""
    from alture_jarvis.model_catalog import by_tag

    model = by_tag("qwen3.6:35b-a3b")
    assert model is not None and model.status == "verified"
    assert model.vram_gb == {131072: 21.3}, "128K 한 칸만 잰다 — 안 잰 칸을 지어내지 않는다"
    assert "vision" in model.roles and model.memory_device.startswith("RTX 3090")
