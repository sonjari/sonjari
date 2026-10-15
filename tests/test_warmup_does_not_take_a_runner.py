"""백엔드가 뜰 때 예열은 **이미 올라가 있는 러너를 빼앗지 않는다**.

★ 2026-09-28 헤르메스 대결: 예열이 `force_preferred` 로 설정값(128K)을 밀어 넣어, 다른 앱(헤르메스)이 쓰던 32K 러너를 백엔드 재기동마다
다시 올렸다(Ollama 적재 기록 13:02 세 번 · 13:29 · 13:37). 128K 는 이 PC 에서 8% 가 CPU 로 샌다.
"""

from __future__ import annotations

from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient


class _Response:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_a_resident_runner_is_left_alone(monkeypatch, tmp_path) -> None:
    posts: list[str] = []

    class _Client:
        def __init__(self, **kwargs) -> None: ...
        def __enter__(self): return self
        def __exit__(self, *args) -> None: return None
        def get(self, url: str) -> _Response:
            return _Response({"models": [{"name": "qwen3.6:35b-a3b", "context_length": 32768}]})
        def post(self, url: str, json: dict) -> _Response:
            posts.append(url)
            return _Response({})

    monkeypatch.setattr("alture_jarvis.ollama.httpx.Client", _Client)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")

    result = OllamaClient(config).warmup()

    assert result["skipped"] == "resident"
    assert posts == [], "예열이 남의 러너를 내리거나 다시 올렸다"
