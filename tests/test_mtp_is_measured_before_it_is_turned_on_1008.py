"""미리 내다보기(MTP)는 이 PC 에서 재 보고 빠를 때만 켠다 (2026-10-08).

이 PC(RTX 3090)에서 잰 것: 27B 는 끔 40 → 켬 66 토큰/초. 그런데 파일에 표시가 없는 9B 는 99 → 68, 표시가 있는 35B A3B 도
141 → 101 로 **느려졌다.** Ollama 는 어느 쪽도 거절하지 않는다. 그래서 —

- 파일 정보에 `…nextn_predict_layers` 가 없으면 재지도 켜지도 않는다.
- 있으면 끔·켬을 재고, 뚜렷이 빠를 때만 그 모델의 **기본값**에 심는다(같은 이름으로 다시 만든다).
- 이미 값이 적혀 있으면 건드리지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import MTP_DRAFT_TOKENS, SetupService, parse_model_parameters

TAG = "hf.co/example/Model-27B-GGUF:Q3_K_XL"


class Rig:
    """가짜 Ollama — 파일 정보 · 끔/켬 속도 · 다시 만들기를 흉내 낸다."""

    def __init__(self, *, layers: int, off: float, on: float, parameters: str = "", create_ok: bool = True) -> None:
        self.layers, self.off, self.on, self.parameters, self.create_ok = layers, off, on, parameters, create_ok
        self.benches: list[int | None] = []
        self.created: list[dict[str, Any]] = []
        self.current = ("", 0)

    def post(self, url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        if url.endswith("/api/show"):
            info = {"qwen35.nextn_predict_layers": self.layers} if self.layers else {"qwen35.block_count": 64}
            return {"model_info": info, "parameters": self.parameters, "capabilities": ["tools", "completion"]}
        if url.endswith("/api/create"):
            self.created.append(dict(body))
            return {"status": "success"} if self.create_ok else {"error": "nope"}
        if body.get("keep_alive") == 0:
            self.current = ("", 0)
            return {}
        options = body.get("options") or {}
        self.current = (body["model"], int(options.get("num_ctx") or 0))
        draft = options.get("draft_num_predict")
        self.benches.append(draft)
        speed = self.on if draft else self.off
        return {"response": "하나, 둘, 셋", "eval_count": 200, "eval_duration": int(200 / speed * 1e9)}

    def get(self, url: str) -> dict[str, Any]:
        model, _ctx = self.current
        if url.endswith("/api/tags"):
            return {"models": [{"name": TAG}]}
        return {"models": [{"name": model, "size": 10000, "size_vram": 10000}] if model else []}

    def stream(self, url: str, body: dict[str, Any]):
        yield {"status": "success"}


def _service(tmp_path: Path, rig: Rig) -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    service = SetupService(config, post=rig.post, get=rig.get, stream=rig.stream)
    service._reread_sec = 0.0
    return service


def test_a_faster_model_gets_it_as_its_default(tmp_path: Path) -> None:
    rig = Rig(layers=1, off=40.0, on=66.0)

    record = _service(tmp_path, rig).settle_mtp(TAG, 32768)

    assert record["enabled"] is True and record["off_tps"] == 40.0 and record["on_tps"] == 66.0
    assert rig.benches == [0, MTP_DRAFT_TOKENS], "끔과 켬을 한 번씩 잰다"
    assert len(rig.created) == 1
    made = rig.created[0]
    assert made["model"] == TAG and made["from"] == TAG, "이름은 그대로 — 화면이 아는 이름과 깔린 이름이 갈리면 안 된다"
    assert made["parameters"]["draft_num_predict"] == MTP_DRAFT_TOKENS


def test_a_model_without_the_mark_is_never_touched(tmp_path: Path) -> None:
    """표시가 없는 모델은 재지도 않는다 — 켜면 느려질 뿐이다(9B 99 → 68)."""
    rig = Rig(layers=0, off=99.0, on=68.0)

    record = _service(tmp_path, rig).settle_mtp(TAG, 32768)

    assert record == {"supported": False}
    assert rig.benches == [] and rig.created == []


def test_a_marked_model_that_gets_slower_is_left_off(tmp_path: Path) -> None:
    """★ 표시가 있어도 느려지는 모델이 있다(35B A3B 141 → 101). 잰 뒤에 안 켠다."""
    rig = Rig(layers=1, off=141.0, on=101.0)

    record = _service(tmp_path, rig).settle_mtp(TAG, 65536)

    assert record["supported"] is True and record["enabled"] is False
    assert rig.created == []


def test_a_gain_inside_the_noise_is_not_enough(tmp_path: Path) -> None:
    rig = Rig(layers=1, off=100.0, on=104.0)

    assert _service(tmp_path, rig).settle_mtp(TAG, 32768)["enabled"] is False
    assert rig.created == []


def test_a_value_someone_already_set_is_respected(tmp_path: Path) -> None:
    rig = Rig(layers=1, off=40.0, on=66.0, parameters="temperature    1\ndraft_num_predict    2\n")

    record = _service(tmp_path, rig).settle_mtp(TAG, 32768)

    assert record == {"supported": True, "already": True, "draft_num_predict": 2}
    assert rig.benches == [] and rig.created == []


def test_the_other_defaults_of_the_model_are_kept(tmp_path: Path) -> None:
    """다시 만들 때 원래 기본값(온도·멈춤 낱말)을 같이 넘긴다 — 한 줄 심으려다 나머지를 잃지 않게."""
    rig = Rig(layers=1, off=40.0, on=66.0, parameters='temperature    0.7\nstop    "<|im_end|>"\nstop    "<|endoftext|>"\ntop_k    20\n')

    _service(tmp_path, rig).settle_mtp(TAG, 32768)

    sent = rig.created[0]["parameters"]
    assert sent["temperature"] == 0.7 and sent["top_k"] == 20
    assert sent["stop"] == ["<|im_end|>", "<|endoftext|>"]
    assert sent["draft_num_predict"] == MTP_DRAFT_TOKENS


def test_applying_a_model_records_what_was_measured(tmp_path: Path) -> None:
    """모델을 적용하는 길에서 한 번 재고, 그 기록이 이 PC 의 선택에 남는다."""
    rig = Rig(layers=1, off=40.0, on=66.0)
    service = _service(tmp_path, rig)

    result = service.apply_tag(TAG, 32768)

    assert result.get("ok"), result
    mtp = result["selection"]["mtp"]
    assert mtp["enabled"] is True and mtp["on_tps"] == 66.0
    assert rig.benches[:2] == [0, MTP_DRAFT_TOKENS]
    assert rig.benches[2:] == [None], "그 뒤 본 측정은 옵션 없이 — 모델 기본값(방금 심은 것)으로 돈다"


def test_parameters_text_parses_to_what_create_expects() -> None:
    assert parse_model_parameters('num_ctx    4096\nstop    "a b"\nrepeat_penalty    1.1\nmirostat    off') == {
        "num_ctx": 4096, "stop": "a b", "repeat_penalty": 1.1, "mirostat": "off",
    }
    assert parse_model_parameters("") == {}


# ── 목록: 같은 양자화에 MTP 파일이 같이 있으면 그 파일을 받게 한다 ──────────────────────────────────────────────

from alture_jarvis.hf_catalog import HfCatalog  # noqa: E402

REPO = "example/Model-27B-GSQ-GGUF"
TREE_WITH_MTP = [
    {"path": "Model-27B-GSQ-IQ3_S.gguf", "size": 12_300_000_000},
    {"path": "Model-27B-GSQ-IQ3_S-mtp.gguf", "size": 13_050_000_000},
    {"path": "Model-27B-GSQ-Q4_K_M.gguf", "size": 16_400_000_000},
    {"path": "Model-27B-GSQ-IQ2_XS-mtp.gguf", "size": 9_100_000_000},
    {"path": "mmproj-F16.gguf", "size": 870_000_000},
]


def _files(tree: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    catalog = HfCatalog(fetch=lambda url: tree if "/tree/main" in url else [])
    return {f["quant"]: f for f in catalog.files(REPO, 22.0)["files"]}


def test_the_mtp_file_is_the_one_that_gets_pulled() -> None:
    """같은 양자화에 둘이 있으면 MTP 파일 — 태그는 파일 이름 꼴이어야 Ollama 가 그 파일을 집는다."""
    files = _files(TREE_WITH_MTP)

    picked = files["IQ3_S"]
    assert picked["mtp_file"] is True
    assert picked["file"] == "Model-27B-GSQ-IQ3_S-mtp.gguf"
    assert picked["tag"] == f"hf.co/{REPO}:Model-27B-GSQ-IQ3_S-mtp.gguf"
    assert picked["file_gb"] == 13.05, "크기도 실제로 받을 파일 것"


def test_a_quant_without_an_mtp_file_is_listed_as_before() -> None:
    """★ 좋은 표본 — MTP 파일이 없는 양자화는 태그도 크기도 예전 그대로."""
    plain = _files(TREE_WITH_MTP)["Q4_K_M"]

    assert plain["mtp_file"] is False
    assert plain["tag"] == f"hf.co/{REPO}:Q4_K_M" and plain["file_gb"] == 16.4


def test_a_quant_that_exists_only_as_an_mtp_file_is_not_dropped() -> None:
    only = _files(TREE_WITH_MTP)["IQ2_XS"]

    assert only["mtp_file"] is True
    assert only["tag"] == f"hf.co/{REPO}:Model-27B-GSQ-IQ2_XS-mtp.gguf"


def test_a_quant_is_listed_once() -> None:
    catalog = HfCatalog(fetch=lambda url: TREE_WITH_MTP if "/tree/main" in url else [])

    quants = [f["quant"] for f in catalog.files(REPO, 22.0)["files"]]

    assert sorted(quants) == ["IQ2_XS", "IQ3_S", "Q4_K_M"]
