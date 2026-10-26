"""첫 글자 전 기다림의 **까닭**을 보인다 · 재기 전에 다른 앱이 올린 모델을 내린다 (2026-10-25 대표).

- 「질문하니 도구가 바뀐 건지 또 느리다 — 모델 재적재 때처럼 도구 바꾸는 중이라고 알려 달라」
- 사용자 PC: 파일럿 앱이 같은 Ollama 에 번역 모델(3.3GB)을 올려 두면 27B 상한이 모자라게 잴 수 있다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.first_token_wait import wait_message
from alture_jarvis.model_setup import SetupService
from alture_jarvis.ollama import reread_reason, request_shape


def _body(model: str = "m", tools: tuple[str, ...] = ("a", "b"), system: str = "지침") -> dict:
    return {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": "q"}],
            "tools": [{"function": {"name": name}} for name in tools]}


def test_the_reason_comes_from_comparing_with_the_last_call() -> None:
    work = request_shape(_body(tools=tuple(f"t{i}" for i in range(133)), system="긴 일 지침"))
    chat = request_shape(_body(tools=("t0", "t1"), system="짧은 대화 지침"))
    assert reread_reason(None, work) == "first"
    assert reread_reason(work, work) == ""
    assert reread_reason(work, chat) == "both"
    assert reread_reason(work, request_shape(_body(tools=("x",), system="긴 일 지침"))) == "tools"
    assert reread_reason(work, request_shape(_body(model="other", tools=tuple(f"t{i}" for i in range(133)),
                                                  system="긴 일 지침"))) == "model"


def test_the_message_says_why_in_korean_and_english() -> None:
    ko = wait_message(42_000, 12.4, reason="both")
    assert ko.startswith("도구 목록과 지침이 지난번과 달라") and "약 4.2만 토큰" in ko and "12초째" in ko
    en = wait_message(42_000, 12.4, english=True, reason="tools")
    assert en.startswith("the tool list changed") and not any("가" <= ch <= "힣" for ch in en)
    # 까닭을 모르면 예전 문장 그대로.
    assert wait_message(42_000, 7, reason="") == "모델이 앞의 기록(약 4.2만 토큰)을 읽는 중 · 첫 글자 전 7초째"


class _Ollama:
    def __init__(self, loaded: list[dict]) -> None:
        self.loaded = loaded
        self.unloaded: list[str] = []

    def post(self, url, body, timeout):
        if body.get("keep_alive") == 0:
            self.unloaded.append(body["model"])
            self.loaded = [row for row in self.loaded if row["name"] != body["model"]]
        return {}

    def get(self, url):
        if url.endswith("/api/ps"):
            return {"models": list(self.loaded)}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "swift:27b", "details": {"family": "qwen35", "parameter_size": "27B",
                                                                 "quantization_level": "Q4_K_M"}}]}
        return {}


def _service(tmp_path: Path, fake: _Ollama) -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.model_roles = {"chat": "swift:27b"}
    return SetupService(config, post=fake.post, get=fake.get)


def test_other_apps_models_are_unloaded_but_ours_is_kept(tmp_path: Path) -> None:
    fake = _Ollama([
        {"name": "translategemma:4b", "details": {"family": "gemma3", "parameter_size": "4B", "quantization_level": "Q4_K_M"}},
        # 같은 파일을 다른 이름으로 올린 것(우리 모델의 별명)은 남긴다.
        {"name": "swift-alias:latest", "details": {"family": "qwen35", "parameter_size": "27B", "quantization_level": "Q4_K_M"}},
    ])
    assert _service(tmp_path, fake)._unload_others("swift:27b") == ["translategemma:4b"]
    assert fake.unloaded == ["translategemma:4b"]


def test_when_ps_cannot_be_read_nothing_is_unloaded(tmp_path: Path) -> None:
    fake = _Ollama([])

    def broken(url):
        raise OSError("down")

    service = _service(tmp_path, fake)
    service._get = broken
    assert service._unload_others("swift:27b") == []
