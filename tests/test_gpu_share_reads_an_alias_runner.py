"""같은 모델 파일을 다른 이름으로 가진 PC 에서도 GPU 비율을 읽는다 (2026-10-01 E2E autopilot_applied 실패).

실측: `plopfit-gemma4-qat`(별칭)가 먼저 떠 있으면 `gemma4:26b-a4b-it-qat` 은 그 러너로 0.7초 만에 답하고,
`/api/ps` 에는 별칭 이름만 보였다. 이름으로만 찾으면 「못 잼」이 되어 마법사가 멀쩡한 모델을 거절했다.
단, **다른 모델** 하나만 남은 것(우리 것이 밀려남)을 우리 비율로 읽으면 안 된다 — 같은 파일일 때만.
"""

from types import SimpleNamespace

from alture_jarvis.model_setup import SetupService

GEMMA = {"family": "gemma4", "parameter_size": "25.8B", "quantization_level": "Q4_0"}
TAGS = {"models": [
    {"name": "gemma4:26b-a4b-it-qat", "details": GEMMA},
    {"name": "plopfit-gemma4-qat:latest", "details": GEMMA},
    {"name": "qwen3.6:35b-a3b", "details": {"family": "qwen3moe", "parameter_size": "35B", "quantization_level": "Q4_K_M"}},
]}


def _service(ps_rows):
    service = SetupService.__new__(SetupService)
    service.config = SimpleNamespace(ollama_base_url="http://ollama")
    service._get = lambda url: TAGS if url.endswith("/api/tags") else {"models": ps_rows}
    return service


def _row(name, size=10, vram=10, details=None):
    return {"name": name, "size": size, "size_vram": vram, "context_length": 131072, "details": details}


def test_exact_name_still_wins():
    got = _service([_row("gemma4:26b-a4b-it-qat", 10, 9, GEMMA)]).gpu_offload("gemma4:26b-a4b-it-qat")
    assert got["gpu_share"] == 0.9 and "matched" not in got


def test_an_alias_of_the_same_file_is_read():
    got = _service([_row("plopfit-gemma4-qat:latest", 10, 10, GEMMA)]).gpu_offload("gemma4:26b-a4b-it-qat")
    assert got["gpu_share"] == 1.0
    assert got["matched"] == "same_file_alias" and got["resident_name"] == "plopfit-gemma4-qat:latest"


def test_a_different_model_alone_is_not_ours():
    qwen = TAGS["models"][2]["details"]
    got = _service([_row("qwen3.6:35b-a3b", details=qwen)]).gpu_offload("gemma4:26b-a4b-it-qat")
    assert got["gpu_share"] is None and got["seen"] == ["qwen3.6:35b-a3b"]


def test_with_several_runners_it_does_not_guess():
    got = _service([_row("a", details=GEMMA), _row("b", details=GEMMA)]).gpu_offload("gemma4:26b-a4b-it-qat")
    assert got["gpu_share"] is None and got["seen"] == ["a", "b"]


def test_nothing_resident_is_still_unknown():
    assert _service([]).gpu_offload("x")["gpu_share"] is None
