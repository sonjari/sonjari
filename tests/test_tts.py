from __future__ import annotations

from alture_jarvis.config import JarvisConfig
from alture_jarvis.tts import SupertonicTTS


class _Response:
    content = b"RIFF-fast-audio"
    headers = {"X-Audio-Duration": "1.250"}
    status_code = 200

    def raise_for_status(self) -> None:
        return None


class _Client:
    requests: list[dict] = []

    def __init__(self, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def post(self, _url: str, *, json: dict):
        self.requests.append(json)
        return _Response()


def test_fast_tts_settings_and_cache_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("alture_jarvis.tts.httpx.Client", _Client)
    _Client.requests.clear()
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        tts_steps=4,
        tts_speed=1.08,
    )
    tts = SupertonicTTS(config)

    first = tts.synthesize("안녕하세요.")
    second = tts.synthesize("안녕하세요.")

    assert first == second
    assert len(_Client.requests) == 1
    assert _Client.requests[0]["steps"] == 4
    assert _Client.requests[0]["speed"] == 1.08
    assert tts.last_metrics["cached"] is True


def test_warmup_always_executes_inference(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("alture_jarvis.tts.httpx.Client", _Client)
    _Client.requests.clear()
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
    )
    tts = SupertonicTTS(config)

    tts.warmup()
    tts.warmup()

    assert len(_Client.requests) == 2
