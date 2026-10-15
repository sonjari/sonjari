"""첫 실행 2단계 — 모델 받기·적용 (전략안 §43, P2).

이 저장소가 이미 겪은 사고 셋을 시험으로 막는다:

    1. 같은 모델을 두 이름으로 부르면 서로 GPU 에서 쫓아낸다
    2. Ollama 는 스스로 모델을 안 바꾼다 — 옛 것을 먼저 내려야 한다
    3. 「받았다」·200 은 증거가 아니다 — 목록에 있고 실제로 생성돼야 한다
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import (
    SetupService,
    apply_selection_to_config,
    read_selection,
    resolve_tag,
    write_selection,
)

INSTALLED = [
    {"name": "plopfit-gemma4-qat:latest", "digest": "sha-gemma"},
    {"name": "gemma4:26b-a4b-it-qat", "digest": "sha-gemma"},
    {"name": "qwen3.5:9b", "digest": "sha-qwen"},
]


def _config(tmp_path: Path, chat: str = "plopfit-gemma4-qat") -> JarvisConfig:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.model_roles = {"chat": chat, "vision": chat, "code": "qwen3.8:27b-mtp-q4_K_M"}
    return config


class _FakeOllama:
    def __init__(self, *, generates: bool = True, installed=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.generates = generates
        self.installed = list(INSTALLED if installed is None else installed)
        self.current = ""

    def post(self, url, body, timeout):
        self.calls.append((url, dict(body)))
        if body.get("keep_alive") == 0:
            return {}
        self.current = body.get("model", "")
        if not self.generates:
            return {"response": "", "eval_count": 0}
        return {"response": "1, 2, 3", "eval_count": 64, "eval_duration": 1_000_000_000,
                "load_duration": 2_000_000_000}

    def get(self, url):
        if url.endswith("/api/ps"):
            return {"models": [{"name": self.current, "size": 100, "size_vram": 100}]}
        return {"models": self.installed}


# ── 1. 태그 갈림 ─────────────────────────────────────────────────────────────
def test_the_same_file_under_our_existing_name_keeps_our_name() -> None:
    """본체는 26B 를 `plopfit-gemma4-qat` 로 부른다. 추천 이름으로 바꾸면 두 이름이 서로를 내린다."""
    tag = resolve_tag("gemma4:26b-a4b-it-qat", INSTALLED, ["plopfit-gemma4-qat"])
    assert tag == "plopfit-gemma4-qat"


def test_a_different_file_is_not_mistaken_for_ours() -> None:
    assert resolve_tag("qwen3.5:9b", INSTALLED, ["plopfit-gemma4-qat"]) == "qwen3.5:9b"


# ── 2·3. 적용 ────────────────────────────────────────────────────────────────
def test_apply_unloads_the_old_model_first_then_really_generates_then_saves(tmp_path: Path) -> None:
    config = _config(tmp_path)
    fake = _FakeOllama()
    service = SetupService(config, post=fake.post, get=fake.get)

    result = service.apply("qwen3.5-9b", 65536)

    assert result["ok"] is True
    # 옛 모델 내리기가 **맨 먼저**이고, 그 뒤 첫 생성이 고른 모델·고른 창으로 돈다. (사이에 파일 정보를 묻는 호출이 낄 수 있다 —
    # 2026-10-08 부터 미리 내다보기를 켤지 보려고 `/api/show` 를 한 번 묻는다. 자리로 세지 않고 첫 생성을 찾는다.)
    unload = fake.calls[0]
    generate = next(call for call in fake.calls[1:] if call[1].get("options"))
    assert unload[1] == {"model": "plopfit-gemma4-qat", "keep_alive": 0, "prompt": ""}
    assert generate[1]["model"] == "qwen3.5:9b" and generate[1]["options"]["num_ctx"] == 65536
    saved = read_selection(config.data_dir)
    assert saved["chat_model"] == "qwen3.5:9b" and saved["num_ctx"] == 65536
    assert config.model_for("chat") == "qwen3.5:9b" and config.ollama_num_ctx == 65536
    # 9B 는 화면 읽기를 안 하므로 비전 역할은 그대로 둔다.
    assert config.model_for("vision") == "plopfit-gemma4-qat"


def test_a_model_that_does_not_generate_is_not_saved(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = SetupService(config, post=_FakeOllama(generates=False).post, get=_FakeOllama().get)
    result = service.apply("qwen3.5-9b", 65536)
    assert result["ok"] is False and result["error"] == "model_did_not_generate"
    assert read_selection(config.data_dir) is None
    assert config.model_for("chat") == "plopfit-gemma4-qat"


def test_an_unmeasured_context_is_refused(tmp_path: Path) -> None:
    """표의 가장 큰 창보다 **큰** 창은 받지 않는다 — 들어가는지 우리가 모른다.

    ★ 2026-09-29 밤 규칙 변경: 표보다 **작은** 창은 받는다(실제로 올려 보고 판정한다). 예전엔 이 시험이
      gemma·64K 를 거절하게 박아 두었는데, 그 규칙 때문에 3.6(표에 128K 하나)은 64K 를 골라도 128K 로
      올라 CPU 로 샜다 — `test_a_spilling_context_steps_down.py`.
    """
    service = SetupService(_config(tmp_path), post=_FakeOllama().post, get=_FakeOllama().get)
    result = service.apply("gemma4-26b-qat", 262144)
    assert result["error"] == "context_not_measured"
    smaller = service.apply("gemma4-26b-qat", 65536)
    assert smaller.get("error") != "context_not_measured"


def test_a_satellite_does_not_touch_models(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.jarvis_role = "satellite"
    service = SetupService(config, post=_FakeOllama().post, get=_FakeOllama().get)
    assert service.apply("qwen3.5-9b", 65536)["error"] == "satellite_uses_brain_models"
    assert service.start_pull("qwen3.5-9b")["error"] == "satellite_uses_brain_models"


# ── 3. 받기 ──────────────────────────────────────────────────────────────────
def _run_pull(tmp_path: Path, events: list[dict], installed: list[dict]) -> dict:
    fake = _FakeOllama(installed=installed)
    service = SetupService(
        _config(tmp_path), post=fake.post, get=fake.get,
        stream=lambda url, body: iter(events),
    )
    service._pulls["qwen3.5-9b"] = {"model_key": "qwen3.5-9b", "status": "pulling"}
    service._pull("qwen3.5-9b", "qwen3.5:9b")
    return service._pulls["qwen3.5-9b"]


def test_pull_progress_is_followed_and_confirmed_in_the_list(tmp_path: Path) -> None:
    state = _run_pull(tmp_path, [
        {"status": "pulling manifest"},
        {"status": "downloading", "total": 100, "completed": 40},
        {"status": "success"},
    ], INSTALLED)
    assert state["status"] == "done" and state["total"] == 100


def test_pull_that_says_success_but_is_not_in_the_list_is_a_failure(tmp_path: Path) -> None:
    state = _run_pull(tmp_path, [{"status": "success"}], installed=[])
    assert state["status"] == "failed"
    assert "missing" in state["detail"]


# ── 저장된 선택이 설정을 이긴다 — 그리고 어디서 왔는지 말한다 ──────────────────────
def test_a_saved_selection_is_layered_on_config_and_says_so(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert apply_selection_to_config(config) == "env"
    write_selection(config.data_dir, {"chat_model": "qwen3.5:9b", "vision_model": "", "num_ctx": 32768})
    assert apply_selection_to_config(config) == "setup"
    assert config.model_for("chat") == "qwen3.5:9b" and config.ollama_num_ctx == 32768


def test_a_broken_selection_file_does_not_stop_jarvis(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "model_selection.json").write_text("{깨짐", encoding="utf-8")
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    assert config.model_source == "env"


# ── 4. 목록 밖 모델 · 그래픽카드에 실제로 올라갔나 (M3, 2026-09-15) ────────────────
class _FakeWithShow(_FakeOllama):
    def __init__(self, *, caps: dict, ps: dict | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.caps = caps
        self.ps = ps or {"models": []}

    def post(self, url, body, timeout):
        if url.endswith("/api/show"):
            self.calls.append((url, dict(body)))
            if body["model"] not in self.caps:
                raise RuntimeError("model not found")
            return {"capabilities": self.caps[body["model"]]}
        return super().post(url, body, timeout)

    def get(self, url):
        if url.endswith("/api/ps"):
            return self.ps
        return super().get(url)


def test_installed_models_ask_ollama_whether_tools_work(tmp_path: Path) -> None:
    """★ 웹 요약은 Gemma 4 의 tools 를 빠뜨렸다 — 판정은 받은 모델의 capabilities 로."""
    installed = [{"name": "gemma4:26b-a4b-it-qat", "size": 15 * 2**30}, {"name": "translategemma:4b", "size": 3 * 2**30},
                 {"name": "bge-m3:latest", "size": 2**30}]
    fake = _FakeWithShow(installed=installed, caps={
        "gemma4:26b-a4b-it-qat": ["completion", "vision", "tools", "thinking"],
        "translategemma:4b": ["completion", "vision"], "bge-m3:latest": ["embedding"]})
    rows = {r["name"]: r for r in SetupService(_config(tmp_path), post=fake.post, get=fake.get).installed_models()["models"]}
    assert rows["gemma4:26b-a4b-it-qat"]["tools"] and rows["gemma4:26b-a4b-it-qat"]["status"] == "verified"
    assert rows["translategemma:4b"]["tools"] is False and rows["translategemma:4b"]["status"] == "unlisted"
    assert rows["bge-m3:latest"]["embedding_only"] is True


def test_a_model_without_tool_calling_is_refused(tmp_path: Path) -> None:
    config = _config(tmp_path)
    fake = _FakeWithShow(caps={"translategemma:4b": ["completion", "vision"]})
    result = SetupService(config, post=fake.post, get=fake.get).apply_tag("translategemma:4b")
    assert result == {"ok": False, "error": "no_tool_calling", "capabilities": ["completion", "vision"]}
    assert read_selection(config.data_dir) is None


def test_an_unlisted_tool_model_is_tried_then_saved_as_unlisted(tmp_path: Path) -> None:
    config = _config(tmp_path)
    fake = _FakeWithShow(caps={"mistral-small3.2:24b": ["completion", "tools"]},
                         ps={"models": [{"name": "mistral-small3.2:24b", "size": 100, "size_vram": 100}]})
    result = SetupService(config, post=fake.post, get=fake.get).apply_tag("mistral-small3.2:24b", 32768)
    assert result["ok"] and result["warnings"] == [] and result["offload"]["gpu_share"] == 1.0
    saved = read_selection(config.data_dir)
    assert saved["chat_model"] == "mistral-small3.2:24b" and saved["status"] == "unlisted" and saved["catalog_key"] == ""


def test_mostly_cpu_offload_is_warned_after_really_loading(tmp_path: Path) -> None:
    """AMD·인텔 카드가 지원 밖이거나 메모리가 모자라면 CPU 로 돈다 — 사양표로는 안 보이고 올린 뒤에만 보인다."""
    fake = _FakeWithShow(caps={}, ps={"models": [{"name": "qwen3.5:9b", "size": 100, "size_vram": 20}]})
    service = SetupService(_config(tmp_path), post=fake.post, get=fake.get,
                           stream=lambda *_: iter([{"error": "시험에서 네트워크 받기는 하지 않음"}]))
    result = service.apply("qwen3.5-9b", 32768)
    # 경고만 하고 CPU로 새는 모델을 저장하던 단언은 노트북 실측으로 반박됐다.
    assert not result["ok"] and result["attempts"][0]["offload"]["gpu_share"] == 0.2
    assert read_selection(service.config.data_dir) is None
    assert any("GPU에" in w for w in result["warnings"])


def test_typed_tags_are_shape_checked(tmp_path: Path) -> None:
    service = SetupService(_config(tmp_path), post=_FakeOllama().post, get=_FakeOllama().get)
    for bad in ("", "../evil", "a b", "x;rm", "C:\\model", "https://x/y"):
        assert service.start_pull_tag(bad)["error"] == "bad_tag", bad
        assert service.apply_tag(bad)["error"] == "bad_tag", bad


# ── 받기가 끝나면 **서버가** 적용한다 (2026-09-16 노트북 첫 설치) ────────────────────
def test_a_finished_download_is_applied_by_the_backend_even_if_the_screen_is_gone(tmp_path: Path) -> None:
    """마법사 화면이 받기 끝나기를 지켜보다 적용하던 때, 「받는 동안 다음으로」 → 마법사를 닫으니 적용이 안 됐다.
    제품 첫 화면이 「대화 모델이 이 PC 에 없습니다」였다. 화면이 없어도 끝나는 일은 서버가 끝낸다."""
    fake = _FakeOllama(installed=INSTALLED)
    service = SetupService(_config(tmp_path), post=fake.post, get=fake.get,
                           stream=lambda url, body: iter([{"status": "success"}]))
    service._pulls["qwen3.5-9b"] = {"model_key": "qwen3.5-9b", "status": "pulling"}

    service._pull("qwen3.5-9b", "qwen3.5:9b", lambda: service.apply("qwen3.5-9b", 32768))

    state = service._pulls["qwen3.5-9b"]
    assert state["status"] == "done" and state["applied"]["ok"]
    assert read_selection(tmp_path / "data")["catalog_key"] == "qwen3.5-9b"


def test_done_is_announced_only_after_the_apply_finished(tmp_path: Path) -> None:
    """done 을 먼저 알리면 화면이 그걸 보고 **또** 적용해 모델을 두 번 돌린다."""
    fake = _FakeOllama(installed=INSTALLED)
    seen: list[str] = []
    service = SetupService(_config(tmp_path), post=fake.post, get=fake.get,
                           stream=lambda url, body: iter([{"status": "success"}]))
    service._pulls["qwen3.5-9b"] = {"model_key": "qwen3.5-9b", "status": "pulling"}

    def apply() -> dict:
        seen.append(service._pulls["qwen3.5-9b"]["status"])
        return service.apply("qwen3.5-9b", 32768)

    service._pull("qwen3.5-9b", "qwen3.5:9b", apply)

    assert seen == ["pulling"]
