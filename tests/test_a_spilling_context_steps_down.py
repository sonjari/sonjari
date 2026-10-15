"""창이 새면 같은 모델을 **한 칸 줄여** 다시 잰다 — 3.6 교체 거절 (2026-09-29 밤).

## 무슨 일이 있었나

대표가 모델 고르개에서 3.8 27B → 3.6 35B 로 바꾸자 「그래픽카드에 다 올라가지 않아 바꾸지 않았습니다」.
Ollama 로그: 3.6 을 `-c 131072`(128K)로 올려 40초 → 0.08초짜리 요청(keep_alive 0)으로 내림 → 아무 모델도 없음.
대표는 「손자리가 모델을 올렸다 내렸다 난리」로 봤다.

고르개는 카탈로그의 `largest_fitting_ctx`(VRAM 표 **추정**으로 128K)를 보냈다. 이 PC 에서 3.6·128K 는
7.5% 가 CPU 로 샌다(09-23 실측). `_measure_and_save` 는 새면 **작은 모델**로만 넘어갔고, 3.6 엔 작은 모델
목록이 없어 곧장 거절했다. 64K 면 다 올라가는데 재 보지도 않았다.

## 규칙 (대표 09-29: 「새면 그 전 단계로」)

32K 보다 큰 창이 새면 같은 모델을 128K → 64K → 32K 로 한 칸씩 내려 잰다.
32K 이하에서 새면 예전 그대로 — 창을 더 깎기 전에 작은 모델을 32K 에서 잰다(8GB 노트북 규칙).
"""
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import SetupService, read_selection


class Rig:
    """창 크기에 따라 GPU 에 올라가는 몫이 다른 PC."""

    def __init__(self, share_by_ctx):
        self.share_by_ctx = share_by_ctx
        self.calls = []
        self.current = ("", 0)

    def post(self, url, body, timeout):
        self.calls.append(dict(body))
        if body.get("keep_alive") == 0:
            self.current = ("", 0)
            return {}
        self.current = (body["model"], int((body.get("options") or {}).get("num_ctx") or 0))
        return {"response": "1, 2, 3", "eval_count": 64, "eval_duration": 1_000_000_000}

    def get(self, url):
        model, ctx = self.current
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.6:35b-a3b"}]}
        share = self.share_by_ctx.get(ctx, 1.0)
        return {"models": [{"name": model, "size": 10000, "size_vram": int(10000 * share)}] if model else []}

    def stream(self, url, body):
        yield {"status": "success"}


def _service(tmp_path, rig):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.model_roles = {"chat": "qwen3.8:27b-mtp-q4_K_M", "vision": "qwen3.8:27b-mtp-q4_K_M"}
    events = []
    service = SetupService(config, post=rig.post, get=rig.get, stream=rig.stream,
                           publish=lambda e, p: events.append((e, p)))
    return service, events


def _tried(rig):
    return [(c["model"], c["options"]["num_ctx"]) for c in rig.calls if c.get("prompt") and c.get("keep_alive") != 0]


def test_128k_spills_so_the_same_model_is_tried_at_64k(tmp_path: Path) -> None:
    rig = Rig({131072: 0.925, 65536: 1.0})
    setup, _ = _service(tmp_path, rig)
    result = setup.apply_tag("qwen3.6:35b-a3b", 131072)
    assert result["ok"], result
    saved = read_selection(setup.config.data_dir)
    assert (saved["chat_model"], saved["num_ctx"]) == ("qwen3.6:35b-a3b", 65536)
    assert _tried(rig) == [("qwen3.6:35b-a3b", 131072), ("qwen3.6:35b-a3b", 65536)]
    assert any("64K" in w for w in result.get("warnings") or []), result.get("warnings")


def test_it_keeps_stepping_down_to_32k(tmp_path: Path) -> None:
    rig = Rig({131072: 0.8, 65536: 0.95, 32768: 1.0})
    setup, _ = _service(tmp_path, rig)
    assert setup.apply_tag("qwen3.6:35b-a3b", 131072)["ok"]
    assert read_selection(setup.config.data_dir)["num_ctx"] == 32768


def test_a_fitting_window_is_not_touched(tmp_path: Path) -> None:
    rig = Rig({})
    setup, _ = _service(tmp_path, rig)
    assert setup.apply_tag("qwen3.6:35b-a3b", 65536)["ok"]
    assert _tried(rig) == [("qwen3.6:35b-a3b", 65536)]


def test_nothing_fits_keeps_the_previous_model(tmp_path: Path) -> None:
    rig = Rig({131072: 0.5, 65536: 0.6, 32768: 0.7})
    setup, events = _service(tmp_path, rig)
    result = setup.apply_tag("qwen3.6:35b-a3b", 131072)
    assert not result["ok"] and result["error"] == "model_not_fully_on_gpu"
    assert read_selection(setup.config.data_dir) is None
    assert not any(e == "setup_model_applied" for e, _ in events)


def test_a_failed_switch_warms_the_previous_model_back(tmp_path: Path) -> None:
    """실패하면 옛 모델을 도로 올린다 — 안 그러면 다음 질문이 70~90초 기다린다(09-29 밤 네 번)."""
    import threading

    rig = Rig({131072: 0.5, 65536: 0.6, 32768: 0.7})
    setup, _ = _service(tmp_path, rig)
    assert not setup.apply_tag("qwen3.6:35b-a3b", 131072)["ok"]
    for thread in threading.enumerate():
        if thread.name == "setup-rewarm-previous":
            thread.join(5)
    rewarm = [c for c in rig.calls if c.get("model") == "qwen3.8:27b-mtp-q4_K_M" and c.get("prompt") == ""]
    assert rewarm and rewarm[-1]["keep_alive"] == setup.config.ollama_keep_alive
    assert rig.current[0] == "qwen3.8:27b-mtp-q4_K_M"


def test_one_empty_ps_read_is_not_a_failure(tmp_path: Path) -> None:
    """★ 2026-09-30: 3.8 이 생성까지 했는데 바로 뒤 `/api/ps` 가 비어 `gpu_measurement_unavailable` 로 세 번 거절됐다.
    상한 재기처럼 다시 읽어야 한다 — 한 번 비었다고 교체를 버리지 않는다."""
    rig = Rig({32768: 1.0})
    empty_reads = {"left": 1}
    real_get = rig.get

    def flaky_get(url):
        if url.endswith("/api/ps") and empty_reads["left"]:
            empty_reads["left"] -= 1
            return {"models": []}
        return real_get(url)

    rig.get = flaky_get
    setup, _ = _service(tmp_path, rig)
    setup._reread_sec = 0
    result = setup.apply_tag("qwen3.6:35b-a3b", 32768)

    assert result["ok"], result
    assert read_selection(setup.config.data_dir)["chat_model"] == "qwen3.6:35b-a3b"
