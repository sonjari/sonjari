"""「무엇이 올라가 있나」를 못 물어봤으면 **없다고 읽지 않는다**.

★ 2026-09-28 헤르메스 대결 재측정: 백엔드 재기동 직후 첫 판에서 `/api/ps` 질문이 1.5초 제한에 걸려 0 을 돌려줬고, 에이전트 호출이 설정값
131072 로 나가 32K 로 떠 있던 러너를 128K 로 갈아 끼웠다(계측기: `resident: 0` · 그 순간 실제로는 32768). 128K 는 이 PC 에서 8% 가 CPU 로 샌다.
"""

from __future__ import annotations

import httpx

from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"models": [{"name": "qwen3.6:35b-a3b", "context_length": 32768}]}


def test_a_failed_question_uses_the_runner_seen_moments_ago(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("alture_jarvis.ollama._RESIDENT_SEEN", {})
    answers: list[object] = [_Response(), httpx.ReadTimeout("slow")]

    class _Client:
        def __init__(self, **kwargs) -> None: ...
        def __enter__(self): return self
        def __exit__(self, *args) -> None: return None
        def get(self, url: str):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setattr("alture_jarvis.ollama.httpx.Client", _Client)
    client = OllamaClient(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"))

    assert client._resident_context("qwen3.6:35b-a3b") == 32768
    assert client._resident_context("qwen3.6:35b-a3b") == 32768, "못 물어본 것을 「없다」로 읽어 128K 로 갈아 끼운다"


def test_never_seen_and_cannot_ask_is_still_zero(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("alture_jarvis.ollama._RESIDENT_SEEN", {})
    class _Client:
        def __init__(self, **kwargs) -> None: ...
        def __enter__(self): return self
        def __exit__(self, *args) -> None: return None
        def get(self, url: str):
            raise httpx.ConnectError("down")

    monkeypatch.setattr("alture_jarvis.ollama.httpx.Client", _Client)
    client = OllamaClient(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"))

    assert client._resident_context("qwen3.6:35b-a3b") == 0


def test_an_empty_list_right_after_a_request_is_not_trusted(monkeypatch, tmp_path) -> None:
    """14:38:50 실측: 첫 걸음이 끝나는 찰나 `/api/ps` 가 빈 목록 — 러너는 떠 있었는데 128K 로 갈아 끼웠다."""
    monkeypatch.setattr("alture_jarvis.ollama._RESIDENT_SEEN", {})

    class _Empty(_Response):
        def json(self) -> dict:
            return {"models": []}

    answers: list[object] = [_Response(), _Empty()]

    class _Client:
        def __init__(self, **kwargs) -> None: ...
        def __enter__(self): return self
        def __exit__(self, *args) -> None: return None
        def get(self, url: str):
            return answers.pop(0)

    monkeypatch.setattr("alture_jarvis.ollama.httpx.Client", _Client)
    client = OllamaClient(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"))

    assert client._resident_context("qwen3.6:35b-a3b") == 32768
    assert client._resident_context("qwen3.6:35b-a3b") == 32768
