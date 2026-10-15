"""메모리가 모자란 것은 설치가 덜 된 것이 아니다 (2026-10-01 밤 베타 테스터 노트북 RTX 3050 6GB).

마법사가 Qwen 3.5 4B · 32K(4.2GB)를 권해 적용하자 Ollama 가
「HTTP 500: llama-server startup failed after projector CPU offload retry: … cudaMalloc failed: out of memory」를 줬다.
`why_apply_failed` 는 「llama-server」 낱말만 보고 「Ollama 설치가 덜 됐습니다」로 갈라 **다시 설치**를 돌렸다 —
다시 깔아도 메모리는 그대로다. 그리고 4B 다음 후보(2B)를 재 보지도 않고 곧장 그만뒀다.
"""
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import SetupService, gpu_users, read_selection, why_apply_failed

SEEN = ("RuntimeError: HTTP 500: llama-server startup failed after projector CPU offload retry: llama-server "
        "reported out-of-memory during startup: cudaMalloc failed: out of memory al")


def test_out_of_memory_is_named_as_such() -> None:
    assert why_apply_failed({"error": SEEN}) == "model_out_of_memory"


def test_a_missing_runner_is_still_a_missing_runner() -> None:
    assert why_apply_failed({"error": "error starting llama-server: llama-server binary not found"}) == "ollama_runner_missing"


def test_another_llama_server_failure_does_not_send_people_to_reinstall() -> None:
    assert why_apply_failed({"error": "llama-server startup failed: exit status 0xc0000409"}) == "model_load_failed"


class Rig:
    """4B 는 메모리가 모자라 못 올리고 2B 는 올라가는 6GB 노트북."""

    def __init__(self, fails: set[str]):
        self.fails = fails
        self.calls: list[dict] = []
        self.current = ""

    def post(self, url, body, timeout):
        self.calls.append(dict(body))
        if body.get("keep_alive") == 0:
            self.current = ""
            return {}
        if body.get("model") in self.fails and body.get("prompt"):
            raise RuntimeError(SEEN)
        self.current = body.get("model") or ""
        return {"response": "1, 2, 3", "eval_count": 64, "eval_duration": 1_000_000_000, "capabilities": ["tools"]}

    def get(self, url):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:4b"}, {"name": "qwen3.5:2b"}]}
        return {"models": [{"name": self.current, "size": 1000, "size_vram": 1000}] if self.current else []}

    def stream(self, url, body):
        yield {"status": "success"}


def _service(tmp_path: Path, rig: Rig) -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.model_roles = {"chat": "", "vision": ""}
    return SetupService(config, post=rig.post, get=rig.get, stream=rig.stream, publish=lambda e, p: None)


def test_out_of_memory_tries_the_smaller_model(tmp_path: Path) -> None:
    rig = Rig({"qwen3.5:4b"})
    setup = _service(tmp_path, rig)
    result = setup.apply_tag("qwen3.5:4b", 32768)
    assert result["ok"], result
    assert read_selection(setup.config.data_dir)["chat_model"] == "qwen3.5:2b"
    assert any("메모리가 모자라" in w for w in result.get("warnings") or []), result.get("warnings")


def test_when_nothing_fits_it_says_memory_and_who_uses_the_card(tmp_path: Path, monkeypatch) -> None:
    import alture_jarvis.model_setup as ms

    monkeypatch.setattr(ms, "gpu_users", lambda: {"used_gb": 3.1, "total_gb": 6.0, "apps": ["ollama"]})
    rig = Rig({"qwen3.5:4b", "qwen3.5:2b"})
    result = _service(tmp_path, rig).apply_tag("qwen3.5:4b", 32768)
    assert not result["ok"]
    assert result["error"] == "model_out_of_memory"
    assert result["gpu_users"]["apps"] == ["ollama"]


def test_gpu_users_keeps_other_ollamas_visible() -> None:
    shot = {"gpus": [{"index": 0, "total_gb": 6.0, "used_gb": 3.1, "apps": ["ollama", "llama-server", "ollama"]}]}
    assert gpu_users(shot) == {"used_gb": 3.1, "total_gb": 6.0, "apps": ["ollama", "llama-server"]}
    assert gpu_users({"gpus": []}) == {}
