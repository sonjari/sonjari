"""역할 모델이 Ollama 에 **없으면** 대화 모델로 대신하고, 그 사실을 상태에 남긴다 (2026-09-20 이 PC 실측).

운영 PC 의 이미지 역할이 `plopfit-gemma4:latest` 를 가리켰는데 그 태그는 **이미 지워져 있었다**(사고 P — 문제은행 태그와
QAT 태그가 서로 밀어내서 QAT 하나로 합치고 비QAT 를 지웠다. 이미지 역할 설정 한 줄만 옛 이름에 남았다).
`/api/show` 404. 사진을 붙여 물으면 없는 모델을 부른다. 게다가 `/health` 의 `model_available` 은 대화 모델만 봐서 「정상」이었다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient


def _client(tmp_path: Path, installed: list[str] | None) -> OllamaClient:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o", control_token="t")
    config.model_roles = {"chat": "plopfit-gemma4-qat", "code": "qwen3.8:27b-mtp-q4_K_M", "vision": "plopfit-gemma4:latest"}
    client = OllamaClient(config)
    client._installed_models = lambda: installed  # type: ignore[method-assign]
    return client


INSTALLED = ["plopfit-gemma4-qat:latest", "qwen3.8:27b-mtp-q4_K_M", "bge-m3:latest"]


def test_a_missing_vision_model_uses_the_chat_model(tmp_path: Path) -> None:
    client = _client(tmp_path, INSTALLED)
    assert client._selected_model(role="vision") == "plopfit-gemma4-qat"
    assert client.missing_roles() == {"vision": "plopfit-gemma4:latest"}


def test_an_installed_role_model_is_used_as_is(tmp_path: Path) -> None:
    client = _client(tmp_path, INSTALLED)
    assert client._selected_model(role="code") == "qwen3.8:27b-mtp-q4_K_M"
    assert "code" not in client.missing_roles()


def test_an_explicit_model_is_never_swapped(tmp_path: Path) -> None:
    """호출부가 이름을 찍어 부르면 그대로 — 없으면 그 호출이 실패하는 게 맞다(조용히 다른 모델이 답하면 안 된다)."""
    client = _client(tmp_path, INSTALLED)
    assert client._selected_model("some-other:7b", role="vision") == "some-other:7b"


def test_when_the_list_is_unknown_nothing_is_swapped(tmp_path: Path) -> None:
    """Ollama 에 못 닿아 목록을 모르면 바꾸지 않는다 — 모르는 것을 없다고 치지 않는다."""
    client = _client(tmp_path, None)
    assert client._selected_model(role="vision") == "plopfit-gemma4:latest"
    assert client.missing_roles() == {}
