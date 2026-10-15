"""그림 읽는 부속이 없는 모델에는, 목록이 정해 준 부속을 따로 받아 붙인다 (2026-10-08).

24GB 급의 첫 추천이 된 Swift 27B 압축판은 저장소에 그림 부속이 없다. 그대로 권하면 사용자의 모델은 화면·사진을 못 읽는다.
Ollama 는 부속 파일만 따로 받을 수 있고(0.93GB), 두 파일을 넘겨 같은 이름으로 다시 만들면 그림 읽기가 생긴다 —
이 PC 에서 붙여 답을 아는 그림 셋을 맞게 읽었다.

- 이미 그림을 읽는 모델은 건드리지 않는다.
- 못 받거나 못 붙이면 그림 없이 간다(모델 적용을 막지 않는다) — 그리고 그 사실이 선택 기록에 남는다.
- 어느 부속이 맞는지는 규칙이 아니라 목록이 안다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_catalog import CATALOG, by_key, is_open_license
from alture_jarvis.model_setup import SetupService

MODEL = "hf.co/example/Model-27B-GGUF:Model-27B-IQ3_S-mtp.gguf"
PROJECTOR = "hf.co/example/Model-27B-plain-GGUF:mmproj-Model-27B-F16.gguf"
MODEL_BLOB, PROJECTOR_BLOB = "a" * 64, "b" * 64


class Rig:
    def __init__(self, *, vision: bool = False, pull_ok: bool = True, create_ok: bool = True) -> None:
        self.vision, self.pull_ok, self.create_ok = vision, pull_ok, create_ok
        self.pulled: list[str] = []
        self.created: list[dict[str, Any]] = []

    def post(self, url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        if url.endswith("/api/show"):
            if body["model"] == PROJECTOR:
                return {"modelfile": f"FROM D:\\\\models\\\\blobs\\\\sha256-{PROJECTOR_BLOB}\n", "capabilities": ["completion", "vision"]}
            lines = f"FROM D:\\\\models\\\\blobs\\\\sha256-{MODEL_BLOB}\n"
            if self.vision:
                lines += f"FROM D:\\\\models\\\\blobs\\\\sha256-{PROJECTOR_BLOB}\n"
            return {"modelfile": lines, "parameters": 'stop    "<|im_end|>"\ntemperature    0.7\n',
                    "capabilities": ["tools", "completion"] + (["vision"] if self.vision else [])}
        if url.endswith("/api/pull"):
            self.pulled.append(body["model"])
            return {"status": "success"} if self.pull_ok else {"error": "pull model manifest: 403"}
        if url.endswith("/api/create"):
            self.created.append(dict(body))
            if self.create_ok:
                self.vision = True
                return {"status": "success"}
            return {"error": "nope"}
        return {}


def _service(tmp_path: Path, rig: Rig) -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    return SetupService(config, post=rig.post, get=lambda url: {"models": []}, stream=lambda url, body: iter(()))


def test_the_projector_is_pulled_and_attached_under_the_same_name(tmp_path: Path) -> None:
    rig = Rig()

    result = _service(tmp_path, rig).ensure_projector(MODEL, PROJECTOR)

    assert result == {"attached": True, "vision": True}
    assert rig.pulled == [PROJECTOR], "부속 파일만 받는다"
    made = rig.created[0]
    assert made["model"] == MODEL, "이름은 그대로 — 화면이 아는 이름과 깔린 이름이 갈리면 안 된다"
    assert made["files"] == {"model.gguf": "sha256:" + MODEL_BLOB, "mmproj.gguf": "sha256:" + PROJECTOR_BLOB}
    assert made["parameters"] == {"stop": "<|im_end|>", "temperature": 0.7}, "원래 기본값을 잃지 않는다"


def test_a_model_that_already_reads_pictures_is_left_alone(tmp_path: Path) -> None:
    rig = Rig(vision=True)

    result = _service(tmp_path, rig).ensure_projector(MODEL, PROJECTOR)

    assert result == {"attached": False, "already": True, "vision": True}
    assert rig.pulled == [] and rig.created == []


def test_a_failed_download_leaves_the_model_usable_without_pictures(tmp_path: Path) -> None:
    """회사 망에서 허깅페이스가 막힌 PC — 그림은 포기하고 모델은 그대로 쓴다."""
    rig = Rig(pull_ok=False)

    result = _service(tmp_path, rig).ensure_projector(MODEL, PROJECTOR)

    assert result["attached"] is False and result["vision"] is False and result["error"] == "projector_download_failed"
    assert rig.created == []


def test_a_failed_attach_is_reported_not_hidden(tmp_path: Path) -> None:
    rig = Rig(create_ok=False)

    result = _service(tmp_path, rig).ensure_projector(MODEL, PROJECTOR)

    assert result["attached"] is False and result["vision"] is False and result["error"] == "attach_failed"


# ── 목록: 라이선스 표시 · 같은 모델의 크기 묶음 ─────────────────────────────────────────────────────────────────

def test_only_well_known_free_licences_count_as_open() -> None:
    assert is_open_license("Apache 2.0") and is_open_license("apache-2.0") and is_open_license("MIT")
    assert not is_open_license("Swift Open License v1.0")
    assert not is_open_license("")


def test_every_conditional_licence_in_the_catalog_carries_a_link() -> None:
    """조건이 붙은 라이선스는 「사용 조건 있음」과 **원문 주소**가 같이 나가야 한다 — 내용을 우리 말로 풀지 않는 대신."""
    for model in CATALOG:
        if model.license and not is_open_license(model.license):
            assert model.license_url.startswith("https://"), model.key


def test_the_catalog_tells_the_screen_what_it_needs() -> None:
    swift = by_key("qwen3.8-27b-swift").public()
    assert swift["license_open"] is False and swift["license_url"]
    assert swift["family"] == "swift-27b" and swift["family_name"] and swift["quant"] == "IQ3_S" and swift["quant_label"] == "3비트"
    plain = by_key("qwen3.8-27b-gsq").public()
    assert plain["license_open"] is True and plain["family"] == ""


def test_the_smaller_size_is_recommended_only_below_the_big_one() -> None:
    """둘째 크기는 큰 크기가 못 들어가는 카드에서만 추천된다.

    (10-08 에는 이 시험이 `…offered_but_never_recommended` 였다 — 「사용자가 고르는 길로만 나간다 · 16GB 카드에서 돌려 본 적이
    없다」. 2026-10-10 대표 결정으로 16GB 급의 첫 추천이 됐다: 「실제 체급을 사용자는 더 좋아한다 — 대안은 카드로 띄워 주면 된다」.
    실제 16GB 카드에서 돌려 본 적이 없다는 사실은 그대로다 — 목록 주석과 `memory_device` 가 그렇게 적고 있다.)
    """
    from alture_jarvis.setup_profile import _LADDER

    small = by_key("qwen3.8-27b-swift-iq3xxs")
    big = by_key("qwen3.8-27b-swift")
    assert small is not None and small.family == big.family and small.projector_tag == big.projector_tag
    assert all(small.vram_gb[ctx] < big.vram_gb[ctx] for ctx in big.vram_gb) and small.download_gb < big.download_gb
    assert small.weak_at and "조사" in small.weak_at, "조사 한 판에서 한 줄 틀린 것과 걸음·시간이 더 든 것을 숨기지 않는다"
    assert small.chain is None, "세 판은 사슬 벤치가 아니다 — 그 칸에 넣지 않는다(권한 판정이 같이 본다)"
    keys = [key for key, _ctx, _room in _LADDER]
    assert small.key in keys and keys.index(big.key) < keys.index(small.key), "큰 크기가 들어가는 카드에서는 큰 크기가 먼저다"
    assert small.minimum_vram_gb == 16.0 and big.minimum_vram_gb > 16.5


def test_members_of_a_family_share_one_name_and_differ_in_quant() -> None:
    families: dict[str, list] = {}
    for model in CATALOG:
        if model.family:
            families.setdefault(model.family, []).append(model)
    for members in families.values():
        assert len({m.family_name for m in members}) == 1
        assert len({m.quant for m in members}) == len(members)
        assert all(m.quant_label for m in members)
