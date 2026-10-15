"""켤 때 자기 점검은 **떠 있는 러너를 갈아 끼우지 않는다**.

★ 2026-09-28 헤르메스 대결 재측정: 점검이 설정값 131072 로 모델을 실제로 돌려, 다른 앱(헤르메스)이 쓰던 32K 러너를 백엔드 재기동 1분 뒤마다
128K 로 바꿨다. 재기동 직후 첫 판에서만 러너가 바뀌던 이유였다(계측기에는 우리 요청이 32K 로 찍혀 원인이 안 보였다).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.self_care import SelfCare


def _care(tmp_path: Path, resident: list[dict], monkeypatch) -> tuple[SelfCare, list[int]]:
    benched: list[int] = []

    class _Response:
        content = b"{}"

        def json(self) -> dict:
            return {"models": resident}

    class _Client:
        def __init__(self, **kwargs) -> None: ...
        def __enter__(self): return self
        def __exit__(self, *args) -> None: return None
        def get(self, url: str) -> _Response: return _Response()
        def post(self, url: str, json: dict) -> _Response: return _Response()

    def _bench(base: str, model: str, ctx: int, *, keep_alive: str, post: Any) -> dict:
        benched.append(ctx)
        return {}

    monkeypatch.setattr("alture_jarvis.self_care.httpx.Client", _Client)
    monkeypatch.setattr("alture_jarvis.setup_profile.micro_bench", _bench)
    config = JarvisConfig(runtime_root=tmp_path, ollama_num_ctx=131072)
    for item in resident:
        item["name"] = item["name"].replace("OURS", config.ollama_model)
    return SelfCare(config, EventBus(), tts=lambda: None, browser=lambda: None, google=lambda: None), benched


def test_our_model_is_measured_at_the_size_it_is_running(tmp_path: Path, monkeypatch) -> None:
    care, benched = _care(tmp_path, [{"name": "OURS", "context_length": 32768}], monkeypatch)

    care._check_model()

    assert benched == [32768], "점검이 설정값으로 재서 러너를 128K 로 갈아 끼운다"


def test_another_apps_model_is_left_alone(tmp_path: Path, monkeypatch) -> None:
    care, benched = _care(tmp_path, [{"name": "someone-elses-model:7b", "context_length": 32768}], monkeypatch)

    organ = care._check_model()

    assert benched == [], "다른 앱이 쓰는 모델을 내리고 우리 모델을 올려 쟀다"
    assert organ["state"] == "unknown"
