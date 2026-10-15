"""컨텍스트 감시 — 재지 않고 **보기만** 해서, 모델 카드에 붙은 프로그램이 바뀌면 다시 재 보기를 권한다 (2026-09-23).

처음 설계는 「늘어난 여유 GB → 올라갈 컨텍스트」를 추정했다. 그날 실측으로 틀렸다 — 뱀부 스튜디오가 3090 에
있을 때와 없을 때 64K 비율이 같았다(96.63%). 그래서 이름(누가 빠지고 들어왔나)만 말한다.
"""

from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis.context_watch import assess, gpu_snapshot, model_gpu, others, slope_gb_per_k

RECORD = {"ceiling": 40960, "gpu_uuid": "GPU-3090", "others_apps": ["python", "bambu-studio"],
          "measured_at": "2026-09-23T05:26:43"}


def _snap(apps: list[str], *, display: bool = False) -> dict:
    return {"gpus": [{"index": 0, "uuid": "GPU-3090", "used_gb": 21.0, "total_gb": 24.0, "display": display,
                      "apps": ["llama-server", *apps]}]}


def test_a_program_leaving_the_card_is_reported_by_name() -> None:
    seen = assess(RECORD, _snap(["python"]))

    assert seen["state"] == "changed" and seen["left"] == ["bambu-studio"] and seen["joined"] == []


def test_a_program_joining_the_card_is_reported_by_name() -> None:
    seen = assess(RECORD, _snap(["python", "bambu-studio", "blender"]))

    assert seen["state"] == "changed" and seen["joined"] == ["blender"]


def test_same_programs_mean_steady_whatever_the_memory_does() -> None:
    """★ 2026-09-23 역검증: 사용량 숫자는 Ollama 자신의 버퍼로 흔들린다 — 목록이 같으면 아무 말도 안 한다."""
    assert assess(RECORD, _snap(["python", "bambu-studio"]))["state"] == "steady"


def test_it_never_claims_how_many_gigabytes_were_freed() -> None:
    """추정 GB 는 틀렸다(뱀부 있을 때·없을 때 64K 비율이 같았다). 말하지 않는 것으로 막는다."""
    seen = assess(RECORD, _snap(["python"]))

    assert not any("gb" in key or key == "estimate" for key in seen)


def test_it_says_unknown_rather_than_guess_without_a_baseline() -> None:
    assert assess({"ceiling": 40960}, _snap([])) == {"state": "unknown"}


def test_slope_comes_from_rungs_that_fit_on_the_card() -> None:
    steps = [
        {"num_ctx": 8192, "passed": True, "size_gb": 20.0},
        {"num_ctx": 32768, "passed": True, "size_gb": 20.72},
        {"num_ctx": 65536, "passed": False, "size_gb": 22.0},  # 샌 칸은 무게가 다르게 잡힌다 — 안 쓴다
    ]
    assert abs(slope_gb_per_k(steps) - 0.03) < 1e-9


def test_snapshot_groups_programs_by_card() -> None:
    """★ 2026-09-23 실수: 카드 구분 없는 목록을 보고 「화면이 3090 을 쓴다」고 잘못 말했다. 카드 uuid 로 묶는다."""
    outputs = {
        "--query-gpu": "0, GPU-3090, 1471, 24576, Disabled\n1, GPU-3060, 1231, 12288, Enabled\n",
        "--query-compute-apps": (
            "GPU-3090, 40340, C:\\Python311\\python.exe\n"
            "GPU-3090, 22980, C:\\Ollama\\lib\\ollama\\llama-server.exe\n"
            "GPU-3060, 27716, C:\\Windows\\explorer.exe\n"
            "GPU-3060, 2244, [Insufficient Permissions]\n"
        ),
    }

    def run(args, **_kw):
        key = next(k for k in outputs if args[1].startswith(k))
        return SimpleNamespace(returncode=0, stdout=outputs[key])

    snap = gpu_snapshot(run)
    card = model_gpu(snap)

    assert card is not None and card["uuid"] == "GPU-3090" and card["display"] is False
    assert others(card) == ["python"]
    assert snap["gpus"][1]["display"] is True and others(snap["gpus"][1]) == ["explorer"]


def test_no_nvidia_smi_means_no_opinion() -> None:
    def run(args, **_kw):
        raise FileNotFoundError("nvidia-smi")

    assert gpu_snapshot(run) == {"gpus": []}


def test_sonjari_itself_is_not_someone_elses_program() -> None:
    """★ 2026-09-30 「새로: python」 — 화면을 찍은 백엔드 자신(python.exe)이 카드 목록에 들어가 남으로 셌다.
    PID 로 가른다: 우리 PID 는 빼고, 사용자의 다른 파이썬은 그대로 센다."""
    outputs = {
        "--query-gpu": "0, GPU-3090, 1471, 24576, Disabled\n",
        "--query-compute-apps": (
            "GPU-3090, 7840, C:\\Python311\\python.exe\n"
            "GPU-3090, 22980, C:\\Ollama\\lib\\ollama\\llama-server.exe\n"
            "GPU-3090, 5555, C:\\Users\\me\\comfy\\python.exe\n"
        ),
    }

    def run(args, **_kw):
        key = next(k for k in outputs if args[1].startswith(k))
        return SimpleNamespace(returncode=0, stdout=outputs[key])

    card = model_gpu(gpu_snapshot(run, ours={7840}))

    assert card is not None and others(card) == ["python"]
    assert model_gpu(gpu_snapshot(run, ours={7840, 5555})) is not None
    assert others(model_gpu(gpu_snapshot(run, ours={7840, 5555}))) == []


def test_own_pids_include_this_process() -> None:
    import os

    from alture_jarvis.context_watch import own_pids

    assert os.getpid() in own_pids()
