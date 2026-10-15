"""컨텍스트 상한은 **이 PC 에서 올려 보고** 정한다 (2026-09-23 사용자님 요청).

재시작하면 모델이 32K 로 올라왔다 — Ollama 기본값(VRAM 24~48GB → 32K, 24GB 미만 → 4K)이다.
그리고 우리가 고르던 컨텍스트는 우리 PC 에서 잰 표였다. 남의 PC 에선 추정이다.

가짜 Ollama 는 그래픽카드 메모리를 흉내 낸다: 모델 무게 + 컨텍스트에 비례하는 KV 캐시가 카드를 넘으면
넘친 만큼 CPU 로 새고(`size_vram < size`) 속도가 떨어진다. 같은 모델이 카드 크기에 따라 **다른 상한**을 내야 한다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import SetupService, read_ceilings

GB = 2**30


class _Card:
    """무게 `weights_gb` 모델, 컨텍스트 1K 당 `kv_gb_per_k` 를 먹는다. 카드는 `vram_gb`."""

    def __init__(self, vram_gb: float, *, weights_gb: float = 18.0, kv_gb_per_k: float = 0.03,
                 model_max: int = 262144, speed: float = 60.0, clamp_to: int = 0) -> None:
        self.vram_gb, self.weights_gb, self.kv = vram_gb, weights_gb, kv_gb_per_k
        self.model_max, self.speed, self.clamp_to = model_max, speed, clamp_to
        self.loaded: tuple[str, int] | None = None
        self.calls: list[dict] = []

    def _size(self, ctx: int) -> float:
        return self.weights_gb + self.kv * ctx / 1024

    def post(self, url, body, timeout):
        self.calls.append(dict(body))
        if url.endswith("/api/show"):
            return {"model_info": {"qwen35moe.context_length": self.model_max}, "capabilities": ["tools"]}
        if body.get("keep_alive") == 0:
            self.loaded = None
            return {}
        ctx = int(body["options"]["num_ctx"])
        if self.clamp_to:
            ctx = min(ctx, self.clamp_to)
        self.loaded = (body["model"], ctx)
        size = self._size(ctx)
        on_gpu = min(1.0, self.vram_gb / size)
        # CPU 로 샌 만큼 느려진다. 컨텍스트가 커지면 조금은 느려지는 것도 흉내 낸다.
        tps = self.speed * (0.95 if ctx >= 65536 else 1.0) * (1.0 if on_gpu >= 1.0 else on_gpu * 0.3)
        return {"response": "1, 2, 3", "eval_count": 64, "eval_duration": int(64 / tps * 1e9),
                "load_duration": 3_000_000_000}

    def get(self, url):
        if url.endswith("/api/ps"):
            if not self.loaded:
                return {"models": []}
            tag, ctx = self.loaded
            size = self._size(ctx)
            return {"models": [{"name": tag, "size": int(size * GB), "size_vram": int(min(size, self.vram_gb) * GB),
                                "context_length": ctx}]}
        return {"models": [{"name": "qwen3.6:35b-a3b"}]}


def _service(tmp_path: Path, card: _Card, patch=None) -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.model_roles = {"chat": "qwen3.6:35b-a3b"}
    service = SetupService(config, post=card.post, get=card.get, patch_settings=patch)
    # 진짜 nvidia-smi 를 부르지 않는다 — 카드 사정은 가짜 카드가 말한다.
    service.gpu_snapshot = lambda: {"gpus": [{"index": 0, "uuid": "GPU-fake", "total_gb": card.vram_gb,
                                              "used_gb": card._size(card.loaded[1]) + 1.0 if card.loaded else 1.0,
                                              "display": False, "apps": ["llama-server", "python"]}]}
    return service


def test_a_24gb_card_and_an_8gb_card_get_different_ceilings(tmp_path: Path) -> None:
    """같은 모델 모양인데 카드가 다르면 답이 달라야 한다 — 표를 옮겨 적으면 둘이 같게 나온다."""
    big = _service(tmp_path / "a", _Card(23.5)).measure_context_ceiling()
    small = _service(tmp_path / "b", _Card(7.5, weights_gb=3.4, kv_gb_per_k=0.05)).measure_context_ceiling()

    # ★ 09-29 부터 다섯 칸만 재고 새면 그 전 칸(24GB 는 256K 가 새서 128K, 8GB 는 128K 가 새서 64K).
    #   09-23 엔 사이를 좁혀 180K·80K 를 잡았다 — 칸마다 적재라 느려서 대표가 되돌렸다.
    assert big["ok"] and big["ceiling"] == 131072, big
    assert small["ok"] and small["ceiling"] == 65536, small


def test_it_climbs_the_five_rungs_and_stops_at_the_one_before_the_spill(tmp_path: Path) -> None:
    """★ 2026-09-29 밤 대표: 「16·32·64·128·256 까지만 측정하고 새면 그 전 단계로 — 너무 느리다」.
    (09-23 의 「실측 상한 자체를 잡자」 이분 탐색은 `CONTEXT_REFINE` 로 꺼 둠.)"""
    result = _service(tmp_path, _Card(23.5)).measure_context_ceiling()
    tried = [step["num_ctx"] for step in result["steps"]]

    assert tried == [16384, 32768, 65536, 131072, 262144], "사이를 좁히지 않는다 — 칸마다 모델을 새로 올린다"
    assert result["steps"][-1]["why"] == "not_fully_on_gpu"
    assert result["ceiling"] == 131072


def test_the_model_is_left_loaded_at_the_ceiling_not_at_the_failed_rung(tmp_path: Path) -> None:
    """떨어진 칸이 CPU 에 반쯤 걸친 채 남으면 다음 대화가 그걸 따라간다(온텔릭은 올라와 있는 컨텍스트를 쓴다)."""
    card = _Card(23.5)
    result = _service(tmp_path, card).measure_context_ceiling()

    assert card.loaded == ("qwen3.6:35b-a3b", result["ceiling"])


def test_it_never_climbs_past_what_the_model_file_supports(tmp_path: Path) -> None:
    result = _service(tmp_path, _Card(80.0, model_max=32768)).measure_context_ceiling()

    assert result["ceiling"] == 32768 and result["stopped"] == "model_limit"
    assert max(step["num_ctx"] for step in result["steps"]) == 32768


def test_a_context_ollama_silently_shrank_does_not_count(tmp_path: Path) -> None:
    """요청은 128K 인데 Ollama 가 32K 로 깎아 올렸다면, 128K 가 들어간다는 증거가 아니다."""
    result = _service(tmp_path, _Card(80.0, clamp_to=32768)).measure_context_ceiling()

    assert result["ceiling"] == 32768 and result["stopped"] == "context_clamped"


def test_it_refuses_while_other_work_is_running(tmp_path: Path) -> None:
    """재는 동안 모델을 내렸다 올린다 — 도는 일을 죽인다."""
    card = _Card(23.5)
    result = _service(tmp_path, card).measure_context_ceiling(busy=lambda: True)

    assert result == {"ok": False, "error": "busy"} and card.calls == []


def test_the_result_is_remembered_but_not_applied_until_asked(tmp_path: Path) -> None:
    patched: list[dict] = []
    service = _service(tmp_path, _Card(23.5), patch=lambda values: patched.append(values) or {"ok": True})

    service.measure_context_ceiling()
    assert patched == [], "재기만 했는데 저장했다 — 적용은 사람이 결과를 보고 누른다"
    assert read_ceilings(tmp_path / "data")["qwen3.6:35b-a3b"]["ceiling"] == 131072  # 09-29 부터 다섯 칸만(이분 탐색 끔) — 예전 184320

    applied = service.apply_context_ceiling()
    assert applied == {"ok": True, "model": "qwen3.6:35b-a3b", "num_ctx": 131072}
    assert patched == [{"ollama_num_ctx": 131072}]
    assert service.config.ollama_num_ctx == 131072


def test_an_unmeasured_value_is_not_applied(tmp_path: Path) -> None:
    service = _service(tmp_path, _Card(23.5), patch=lambda values: {"ok": True})

    assert service.apply_context_ceiling() == {"ok": False, "error": "not_measured"}


def test_any_measured_ceiling_is_a_value_the_settings_screen_accepts() -> None:
    """상한은 두 배 칸 사이 어디든 된다(예: 180K). 설정이 고정 선택지면 적용이 거절된다."""
    from alture_jarvis.model_setup import CONTEXT_LADDER, CONTEXT_STEP
    from alture_jarvis.settings import validate

    for ctx in (*CONTEXT_LADDER, 180 * 1024, 11 * CONTEXT_STEP):
        assert validate("ollama_num_ctx", ctx) == ctx


def test_a_context_saved_as_text_before_still_loads(tmp_path: Path) -> None:
    """선택지 시절 화면은 `"131072"`(문자열)로 저장했다. 숫자 칸으로 바꾼 뒤 그 값을 거절하면
    갱신하자마자 사용자가 고른 컨텍스트가 조용히 기본값으로 돌아간다."""
    import json

    from alture_jarvis.settings import apply_user_settings, validate

    assert validate("ollama_num_ctx", "65536") == 65536
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "settings.json").write_text(json.dumps({"values": {"ollama_num_ctx": "65536"}}), encoding="utf-8")
    applied = apply_user_settings(config)

    assert "ollama_num_ctx" in applied and config.ollama_num_ctx == 65536


def test_the_record_keeps_a_baseline_for_the_watcher(tmp_path: Path) -> None:
    """30분마다 보는 감시가 「그때와 붙은 프로그램이 달라졌나」를 볼 수 있게, 잴 때의 카드 사정을 같이 남긴다."""
    result = _service(tmp_path, _Card(23.5)).measure_context_ceiling()

    assert result["gpu_uuid"] == "GPU-fake" and result["others_apps"] == ["python"]
    assert abs(result["gb_per_k"] - 0.03) < 0.001
    assert "others_gb" not in result, "틀린 것으로 드러난 추정(남의 몫 GB)을 남기면 누군가 다시 쓴다"


def test_a_measured_rung_can_be_chosen_not_only_the_ceiling(tmp_path: Path) -> None:
    """09-29 대표 요청: 「64K 로 빠르게 · 128K 로 길게」를 칸별로 고른다. 잰 칸이면 CPU 로 샌 칸도 속도를 알고 고를 수 있다."""
    patched: list[dict] = []
    service = _service(tmp_path, _Card(23.5), patch=lambda values: patched.append(values) or {"ok": True})
    service.measure_context_ceiling()

    assert service.apply_context_ceiling(num_ctx=65536) == {"ok": True, "model": "qwen3.6:35b-a3b", "num_ctx": 65536}
    assert service.config.ollama_num_ctx == 65536
    spilled = service.apply_context_ceiling(num_ctx=262144)
    assert spilled["ok"] and spilled["num_ctx"] == 262144
    assert patched == [{"ollama_num_ctx": 65536}, {"ollama_num_ctx": 262144}]


def test_an_unmeasured_or_unloaded_rung_is_refused(tmp_path: Path) -> None:
    """자유 입력이 131070 같은 어중간한 값을 만든 적이 있다 — 잰 칸만 받는다."""
    import json

    from alture_jarvis.model_setup import CEILING_NAME

    service = _service(tmp_path, _Card(23.5), patch=lambda values: {"ok": True})
    service.measure_context_ceiling()
    assert service.apply_context_ceiling(num_ctx=131070) == {"ok": False, "error": "not_measured"}

    path = tmp_path / "data" / CEILING_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    for step in data["qwen3.6:35b-a3b"]["steps"]:
        if step["num_ctx"] == 262144:
            step["tokens_per_sec"] = 0.0
    path.write_text(json.dumps(data), encoding="utf-8")
    assert service.apply_context_ceiling(num_ctx=262144) == {"ok": False, "error": "rung_did_not_load"}


class _BlinkingCard(_Card):
    """올린 직후 `/api/ps` 를 한 번 비워 보내는 카드 — 09-29 이 PC 에서 40K 칸이 이렇게 떨어졌다."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.blink_next = False

    def post(self, url, body, timeout):
        answer = super().post(url, body, timeout)
        if body.get("options"):
            self.blink_next = True
        return answer

    def get(self, url):
        if url.endswith("/api/ps") and self.blink_next:
            self.blink_next = False
            return {"models": []}
        return super().get(url)


def test_one_blank_read_of_the_gpu_share_does_not_fail_the_rung(tmp_path: Path) -> None:
    """생성까지 한 칸을 비율 한 번 못 읽었다고 「떨어짐」으로 치면 상한이 거기서 멈춘다."""
    service = _service(tmp_path, _BlinkingCard(23.5))
    service._reread_sec = 0
    result = service.measure_context_ceiling()

    assert result["ceiling"] == 131072  # 09-29 부터 다섯 칸만 — 예전 184320
    assert all(step["why"] != "gpu_measurement_unavailable" for step in result["steps"])


def test_a_gpu_share_that_never_comes_says_what_ollama_showed(tmp_path: Path) -> None:
    card = _Card(23.5)
    service = _service(tmp_path, card)
    service._reread_sec = 0
    real_get = service._get
    service._get = lambda url: {"models": [{"name": "other:7b", "size": 1}]} if url.endswith("/api/ps") else real_get(url)
    result = service.measure_context_ceiling()

    first = result["steps"][0]
    assert first["why"] == "gpu_measurement_unavailable" and first["ps_seen"] == ["other:7b"]
