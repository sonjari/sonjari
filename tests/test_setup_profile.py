"""첫 실행 1단계 — PC 를 재고 모델을 계산한다 (전략안 §43, P1).

추천은 **순수 함수**라 PC 없이 시험할 수 있다. 사양이 다른 PC 다섯 대를 지문으로 둔다.
이 저장소 규칙대로 양쪽을 본다 — 들어가는 것을 안 들어간다고 하면 사용자가 떠나고,
안 들어가는 것을 들어간다고 하면 첫 부탁에서 멈춘다.
"""

from __future__ import annotations

from alture_jarvis import setup_profile as sp
from alture_jarvis.model_catalog import CATALOG


def _profile(name: str, vram_gb: float, *, display: bool, installed=(), ram=32.0, disk=200.0, **extra):
    return {
        "gpus": [{
            "index": 0, "name": name, "vram_total_gb": vram_gb, "vram_used_gb": 0.5,
            "driver": "580.00", "display_active": display,
        }],
        "gpu_error": "",
        "ram_gb": ram,
        "disk_free_gb": disk,
        "ollama": {"reachable": True, "installed": list(installed), "vulkan_enabled": False},
        **extra,
    }


def test_nvidia_smi_output_is_parsed() -> None:
    cards = sp.parse_nvidia_smi(
        "0, NVIDIA GeForce RTX 3090, 24576, 17640, 580.97, Disabled\n"
        "1, NVIDIA GeForce RTX 3060, 12288, 2443, 580.97, Enabled\n"
    )
    assert [c["name"] for c in cards] == ["NVIDIA GeForce RTX 3090", "NVIDIA GeForce RTX 3060"]
    assert cards[0]["vram_total_gb"] == 24.0 and cards[1]["display_active"] is True


def test_a_24gb_desktop_card_gets_the_27b_we_measured_and_an_open_alternative() -> None:
    """★ 2026-10-08 대표 결정: 24GB 급의 첫 추천은 Swift 27B(같은 바깥 코드 과제 12/12). 그 전엔 Gemma 26B 였다.

    조사해서 문서까지 만드는 우리 벤치는 이 모델로 **아직 안 돌렸다** — 그래서 믿음은 「메모리만 잼」이고 이유에도 그렇게 적힌다.
    라이선스에 조건이 있으니, 조건 없는 대안(같은 바탕의 일반 압축판)이 같이 나온다.
    """
    rec = sp.recommend(_profile("RTX 3090", 24.0, display=False))
    assert rec["mode"] == "local"
    assert rec["model_key"] == "qwen3.8-27b-swift" and rec["num_ctx"] == 131072
    assert rec["confidence"] == "memory_only"
    assert any("아직 안 쟀습니다" in line for line in rec["reasons"])
    picks = {p["kind"]: p for p in rec["picks"]}
    assert picks["verified"]["license_open"] is False and picks["verified"]["license_url"].startswith("https://")
    # ★ 2026-10-28 밤 대표 결정: 둘째 칸은 같은 바탕의 일반 압축판이 아니라 Qwen3.6 2비트 — 「3.8 똑똑함 · 3.6 빠름」.
    alternative = picks["open_alternative"]
    assert alternative["model_key"] == "qwen3.6-35b-iq2m" and alternative["license_open"] is True
    assert (picks["verified"]["role"], alternative["role"]) == ("smart", "fast")
    assert any("똑똑함" in line and "빠름" in line for line in rec["reasons"])
    assert any("조건이 없습니다" in line for line in rec["reasons"])


def test_an_open_licence_first_pick_brings_no_alternative() -> None:
    """★ 좋은 표본 — 첫 추천의 라이선스가 자유로우면 대안 칸이 없다(12GB 급은 9B 하나)."""
    rec = sp.recommend(_profile("RTX 4070", 12.0, display=False))
    assert rec["model_key"] == "qwen3.5-9b"
    assert "open_alternative" not in {p["kind"] for p in rec["picks"]}
    assert not any("조건 없는 대안" in line for line in rec["reasons"])


def test_a_16gb_card_gets_the_small_27b_first_and_9b_as_the_alternative() -> None:
    """★ 2026-10-10 대표 결정: 16GB 급의 첫 추천은 27B 작은 판. 「실제 체급을 사용자는 더 좋아한다 — 대안은 카드로 띄워 주면 된다」.

    그 전에는 9B 였다(이 자리의 시험 이름이 `…gets_9b_not_26b` 였다). 9B 는 사라지지 않는다 — 27B 의 라이선스에 조건이 있어
    「조건 없는 대안」 칸으로 같이 나온다. 그날 잰 조사 세 판(한 판에서 한 줄 틀림)은 사슬 벤치가 아니므로 믿음은 「메모리만 잼」이다.
    """
    for display in (True, False):
        rec = sp.recommend(_profile("RTX 4080", 16.0, display=display))
        # ★ 2026-10-12 대표 결정: 같은 모델의 **글만 읽기 · 창 64K** 가 먼저다(그 전엔 그림 있는 48K).
        assert rec["model_key"] == "qwen3.8-27b-swift-iq3xxs" and rec["num_ctx"] == 65536, display
        assert rec["text_only"] is True
        assert rec["confidence"] == "memory_only"
        picks = {p["kind"]: p for p in rec["picks"]}
        assert picks["verified"]["license_open"] is False and picks["verified"]["text_only"] is True
        assert picks["verified"]["vram_gb"] == 13.8, "그림 부속을 뗀 채 잰 값이어야 한다(그림 있는 64K 는 14.6)"
        assert any("그림 읽기를 끄고" in line and "읽지 못합니다" in line for line in rec["reasons"]), "내주는 것을 같이 말한다"
        # ★ 2026-10-26 대표: 「16GB 기본은 Swift, 안 들어가면 Qwen3.6 2비트」 — 조건 없는 대안도 9B 128K 에서 2비트(Apache 2.0 ·
        #   글만 읽기 64K · 코드 10/12 대 9B 5/12)로 바뀌었다. 사슬 벤치가 아니라 믿음은 「메모리만 잼」이다.
        alt = picks["open_alternative"]
        assert (alt["model_key"], alt["num_ctx"], alt["text_only"]) == ("qwen3.6-35b-iq2m", 65536, True)
        assert alt["vram_gb"] == 12.4 and alt["license_open"] is True
        assert (picks["verified"]["role"], alt["role"]) == ("smart", "fast")
        assert any("똑똑함" in line and "빠름" in line for line in rec["reasons"])


def test_smart_and_fast_only_when_the_first_pick_is_swift() -> None:
    """양방향: 「똑똑함 · 빠름」은 첫 추천이 Swift 일 때만. 12GB(9B 하나) · 8GB(9B 3비트)에는 역할 칸이 없다."""
    for name, vram in (("RTX 4070", 12.0), ("RTX 4060", 8.0)):
        rec = sp.recommend(_profile(name, vram, display=False))
        assert all("role" not in p for p in rec["picks"]), name
        assert not any("똑똑함" in line for line in rec["reasons"]), name


def test_text_only_is_recommended_only_on_the_rung_that_says_so() -> None:
    """양방향: 「글만 읽기」는 그 칸(16GB 급 · 2026-10-14 부터 8GB · 6GB 급)에서만 추천된다. 다른 급의 추천은 그림을 읽는 채로다."""
    for name, vram in (("RTX 3060", 12.0), ("RTX 3090", 24.0)):
        rec = sp.recommend(_profile(name, vram, display=True))
        assert rec["text_only"] is False, name
        assert not any("그림 읽기를 끄고" in line for line in rec["reasons"]), name
    for name, vram in (("RTX 4080 Laptop", 16.0), ("RTX 4060", 8.0), ("RTX 3050 Laptop", 6.0)):
        rec = sp.recommend(_profile(name, vram, display=True))
        assert rec["text_only"] is True, name
        assert any("그림 읽기를 끄고" in line for line in rec["reasons"]), name
    # 못 올렸을 때 권하는 「한 단계 작은 모델」에는 그림을 끄라는 칸을 섞지 않는다 — 그 답에는 그 뜻을 실을 자리가 없다.
    small = sp.smaller_that_fits(15.0, "qwen3.8-27b-swift")
    assert small is not None and (small[0].key, small[1]) != ("qwen3.8-27b-swift-iq3xxs", 65536)


def test_a_tight_fit_is_called_tight_not_comfortable() -> None:
    """15GB 에 14.2GB 를 올리면서 「여유 있게 들어갑니다」라고 말하고 있었다(2026-10-10).
    2026-10-12: 13.8GB(남는 것 1.2GB)에서도 빠듯하다고 말한다 — 화면 쪽이 1.8GB 를 쓰는 PC 를 그날 쟀다."""
    tight = sp.recommend(_profile("RTX 4080 Laptop", 16.0, display=True))
    assert any("빠듯합니다" in line for line in tight["reasons"])
    assert not any("여유 있게" in line for line in tight["reasons"])
    roomy = sp.recommend(_profile("RTX 3090", 24.0, display=False))
    assert any("여유 있게" in line for line in roomy["reasons"])
    assert not any("빠듯합니다" in line for line in roomy["reasons"])


def test_the_small_27b_is_not_offered_where_it_cannot_fit_or_where_the_big_one_does() -> None:
    """양방향: 12GB 에는 안 권하고(안 들어간다), 24GB 에서는 큰 크기가 먼저다."""
    assert sp.recommend(_profile("RTX 3060", 12.0, display=True))["model_key"] == "qwen3.5-9b"
    assert sp.recommend(_profile("RTX 3090", 24.0, display=True))["model_key"] == "qwen3.8-27b-swift"
    # 16GB 인데 다른 프로그램이 3GB 를 쓰고 있어도 추천은 카드 크기로 한다 — 실제로 다 올라가는지는 적용 단계가 재고,
    # 안 되면 화면이 닫을 프로그램과 9B 를 보여 준다(`model_setup.way_out`).
    from alture_jarvis.model_setup import way_out

    out = way_out("qwen3.8-27b-swift-iq3xxs", snapshot={"gpus": [{"total_gb": 16.0, "used_gb": 3.2, "apps": ["chrome"]}]})
    assert out["smaller"]["model_key"] == "qwen3.5-9b"
    assert out["close"]["would_fit"] is True


def test_a_12gb_card_with_display_gets_9b_at_65k_and_says_success_rate_is_unmeasured() -> None:
    rec = sp.recommend(_profile("RTX 3060", 12.0, display=True))
    assert rec["model_key"] == "qwen3.5-9b"
    assert rec["num_ctx"] in (131072, 65536)
    if rec["num_ctx"] != 131072:
        assert rec["confidence"] == "memory_only"
        assert any("안 쟀습니다" in line for line in rec["reasons"])


def test_a_6gb_laptop_gets_the_4b_3bit_text_only() -> None:
    """3050 6GB 노트북 — ★ 2026-10-14 밤 대표 결정: 첫 추천은 4B 3비트의 글만 읽기 · 창 48K.

    그 전에는 그림 있는 공식 4B 32K 였는데, 6GB 노트북(Ollama 0.35)에서 34층 중 30층만 올라가 마법사가 2B 로 내려갔고
    그 2B 는 가격 조사가 0 이었다. 4B 3비트 글만 읽기는 48K 도 카드에 전부(4,011MiB) · 10/63(고치기 전 판).
    9B 는 6GB 에 억지로 넣지 않는다(예전 시험의 뜻 그대로).
    """
    rec = sp.recommend(_profile("RTX 3050 Laptop", 6.0, display=True))
    assert rec["mode"] == "local" and rec["tier_gb"] == 6
    assert (rec["model_key"], rec["num_ctx"], rec["text_only"]) == ("qwen3.5-4b-q3", 49152, True)
    assert not str(rec["model_key"]).startswith("qwen3.5-9b")
    assert any("그림 읽기를 끄고" in line for line in rec["reasons"])


def test_no_gpu_is_said_honestly_without_a_dead_end() -> None:
    """그래픽카드가 없으면 「준비 중」 대신 이유와 권장 사양. CPU 경로는 만들지 않는다(사용자님 결정 09-15)."""
    rec = sp.recommend({"gpus": [], "gpu_error": "nvidia_smi_missing", "ollama": {}})
    assert rec["mode"] == "no_gpu" and rec["picks"] == []
    assert not any("준비 중" in line for line in rec["reasons"])
    assert any("8GB" in line for line in rec["reasons"])


def _card(name: str, vram: float, *, vendor: str, integrated: bool = False, backend: str = "vulkan", display=True):
    return {"name": name, "vram_total_gb": vram, "vendor": vendor, "integrated": integrated,
            "backend": backend, "display_active": display}


def test_each_tier_gets_one_verified_and_one_external_pick() -> None:
    """docs/모델_큐레이션_2026-09-15 표 그대로 — 카드 전체 메모리로 등급을 고르고, 들어가는 것만 준다."""
    expected = {
        # 2026-10-14 부터 9B 3비트 글만 읽기 48K(그 전: 4B 32K — 공식 9B 는 노트북에서 76% GPU 였다).
        8.0: ("qwen3.5-9b-q3", 49152, "granite4.1-8b"),
        12.0: ("qwen3.5-9b", 131072, "gemma4-12b-qat"),
        16.0: ("qwen3.8-27b-swift-iq3xxs", 65536, "gemma4-12b-qat"),  # 2026-10-12 부터 글만 읽기 64K(10-10~: 그림 있는 48K)
        24.0: ("qwen3.8-27b-swift", 131072, "gemma4-31b-qat"),  # 2026-10-08 부터 (그 전엔 gemma4-26b-qat)
    }
    for vram, (verified, ctx, external) in expected.items():
        rec = sp.recommend(_profile("RTX", vram, display=True))
        picks = {p["kind"]: p for p in rec["picks"]}
        assert (picks["verified"]["model_key"], picks["verified"]["num_ctx"]) == (verified, ctx), vram
        assert picks["external"]["model_key"] == external, vram
        assert picks["external"]["evidence"] and picks["external"]["links"] and picks["external"]["checked_at"]
        assert rec["model_key"] == verified  # 검증이 있으면 검증이 먼저다


def test_a_4gb_card_is_too_small_and_says_so() -> None:
    rec = sp.recommend(_profile("GTX 1650", 4.0, display=True))
    assert rec["mode"] == "too_small" and rec["picks"] == [] and rec["model_key"] is None


def test_amd_card_is_recommended_and_not_told_to_turn_vulkan_off() -> None:
    """AMD·인텔 카드는 Vulkan 으로 **도는 것**이다 — NVIDIA PC 에서 배운 「Vulkan 끄라」를 주면 틀린 조언."""
    profile = {"gpus": [_card("AMD Radeon RX 6800", 16.0, vendor="amd"),
                        _card("AMD Radeon(TM) Graphics", 0.5, vendor="amd", integrated=True)],
               "gpu_error": "nvidia_smi_missing", "ram_gb": 32.0, "disk_free_gb": 200.0,
               "ollama": {"installed": [], "vulkan_enabled": False, "vulkan_setting": ""}}
    rec = sp.recommend(profile)
    assert rec["mode"] == "local" and rec["card"]["vendor"] == "amd" and rec["tier_gb"] == 16
    assert any("Vulkan" in line for line in rec["reasons"])
    assert not any("OLLAMA_VULKAN" in line for line in rec["warnings"])


def test_nvidia_with_integrated_graphics_gets_the_vulkan_warning_unless_off() -> None:
    base = {"gpus": [_card("RTX 3090", 24.0, vendor="nvidia", backend="cuda", display=False),
                     _card("Intel(R) UHD Graphics 770", 2.0, vendor="intel", integrated=True)],
            "gpu_error": "", "ram_gb": 64.0, "disk_free_gb": 200.0,
            "ollama": {"installed": [], "vulkan_enabled": False, "vulkan_setting": ""}}
    assert sp.recommend(base)["fixes"] == ["ollama_gpu_only"]
    base["ollama"]["vulkan_setting"] = "off"
    assert sp.recommend(base)["fixes"] == []


def test_integrated_graphics_only_is_no_gpu() -> None:
    profile = {"gpus": [_card("Intel(R) Iris(R) Xe Graphics", 1.0, vendor="intel", integrated=True)],
               "gpu_error": "nvidia_smi_missing", "ollama": {}}
    rec = sp.recommend(profile)
    assert rec["mode"] == "no_gpu" and "내장 그래픽" in rec["reasons"][0]


def test_registry_adapters_read_64bit_memory_and_drop_virtual_ones() -> None:
    """`AdapterRAM` 은 4GB 에서 잘린다 — `qwMemorySize`(QWORD) 를 읽는다. 이 PC 실측 가상 장치는 뺀다."""
    rows = [
        {"DriverDesc": "AMD Radeon RX 7900 XTX", "MatchingDeviceId": r"PCI\VEN_1002&DEV_744C",
         "HardwareInformation.qwMemorySize": 24 * 2**30},
        {"DriverDesc": "Intel(R) Arc(TM) A770 Graphics", "MatchingDeviceId": r"PCI\VEN_8086&DEV_56A0",
         "HardwareInformation.qwMemorySize": 16 * 2**30},
        {"DriverDesc": "Intel(R) UHD Graphics 770", "MatchingDeviceId": r"PCI\VEN_8086&DEV_4680",
         "HardwareInformation.MemorySize": (2 * 2**30).to_bytes(4, "little")},
        {"DriverDesc": "SudoMaker Virtual Display Adapter", "MatchingDeviceId": r"ROOT\VDD"},
        {"DriverDesc": "Microsoft Basic Display Adapter", "MatchingDeviceId": r"ROOT\BASICDISPLAY"},
    ]
    cards = sp.parse_adapters(rows)
    assert [(c["name"], c["vendor"], c["vram_total_gb"], c["integrated"], c["backend"]) for c in cards] == [
        ("AMD Radeon RX 7900 XTX", "amd", 24.0, False, "rocm"),
        ("Intel(R) Arc(TM) A770 Graphics", "intel", 16.0, False, "vulkan"),
        ("Intel(R) UHD Graphics 770", "intel", 2.0, True, "vulkan"),
    ]


def test_merge_does_not_count_an_nvidia_card_twice() -> None:
    nvidia = sp.parse_nvidia_smi("0, NVIDIA GeForce RTX 3090, 24576, 100, 580.97, Disabled\n")
    adapters = [{"name": "NVIDIA GeForce RTX 3090", "vendor": "nvidia", "vram_total_gb": 24.0, "integrated": False,
                 "backend": "cuda", "source": "registry"},
                {"name": "Intel(R) UHD Graphics 770", "vendor": "intel", "vram_total_gb": 2.0, "integrated": True,
                 "backend": "vulkan", "source": "registry"}]
    merged = sp.merge_gpus(nvidia, adapters)
    assert [c["name"] for c in merged] == ["NVIDIA GeForce RTX 3090", "Intel(R) UHD Graphics 770"]
    assert merged[0]["source"] == "nvidia-smi" and merged[1]["usable_gb"] == 1.0


def test_a_dropped_driver_is_not_reported_as_no_gpu() -> None:
    """윈도우 업데이트가 3090 드라이버를 떨어뜨린 날 — 「GPU 없음」과 할 일이 다르다."""
    rec = sp.recommend({"gpus": [], "gpu_error": "nvidia_smi_error", "ollama": {}})
    assert any("드라이버" in line for line in rec["warnings"])


def test_vulkan_low_ram_and_low_disk_are_warned() -> None:
    profile = _profile("RTX 3090", 24.0, display=False, ram=12.0, disk=10.0)
    profile["ollama"]["vulkan_enabled"] = True
    rec = sp.recommend(profile)
    joined = " ".join(rec["warnings"])
    assert rec["fixes"] == ["ollama_gpu_only"] and "NVIDIA 카드만" in joined and "메모리" in joined and "디스크" in joined


def test_an_installed_model_needs_no_disk_warning() -> None:
    profile = _profile("RTX 3090", 24.0, display=False, disk=3.0, installed=(sp.by_key("qwen3.8-27b-swift").ollama_tag,))
    rec = sp.recommend(profile)
    assert rec["installed"] is True
    assert not any("디스크" in line for line in rec["warnings"])


def test_a_real_run_that_is_slow_is_said_out_loud() -> None:
    profile = _profile("RTX 3090", 24.0, display=False)
    bench = {"ok": True, "model": sp.by_key("qwen3.8-27b-swift").ollama_tag, "tokens_per_sec": 9.0}
    rec = sp.recommend(profile, bench)
    assert any("초당 9" in line for line in rec["reasons"])
    assert any("느린" in line for line in rec["warnings"])


def test_micro_bench_counts_an_empty_reply_as_failure() -> None:
    """200 이 왔는데 글자가 없으면 성공이 아니다 — 생존 검사는 실제 왕복으로."""
    empty = sp.micro_bench("http://x", "qwen3.5:9b", 65536,
                           post=lambda url, body, timeout: {"response": "", "eval_count": 0})
    assert empty["ok"] is False and empty["error"] == "empty_generation"


def test_micro_bench_sends_the_same_context_and_turns_thinking_off() -> None:
    seen: dict = {}

    def fake(url, body, timeout):
        seen.update(body)
        return {"response": "1, 2, 3", "eval_count": 64, "eval_duration": 2_000_000_000,
                "load_duration": 3_000_000_000}

    result = sp.micro_bench("http://x", "qwen3.5:9b", 65536, post=fake)
    assert result["ok"] and result["tokens_per_sec"] == 32.0
    assert seen["options"]["num_ctx"] == 65536      # 다르면 러너를 새로 띄워 모델을 쫓아낸다
    assert seen["think"] is False                   # 안 끄면 생각에 예산을 다 쓰고 답이 빈다


def test_the_gallery_marks_what_fits_this_pc() -> None:
    view = sp.catalog_view(_profile("RTX 3060", 12.0, display=True, installed=("qwen3.5:9b",)))
    by = {row["key"]: row for row in view}
    assert by["qwen3.5-9b"]["fits"] and by["qwen3.5-9b"]["installed"]
    assert by["gemma4-26b-qat"]["fits"] is False
    assert len(view) == len(CATALOG)
