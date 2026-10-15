"""노트북 첫 설치에서 잡힌 그래픽카드 두 가지 (2026-09-16 밤, RTX 5050 Laptop).

1. 카드는 레지스트리로 멀쩡히 보이는데 `nvidia-smi` 한 번이 실패해서 「드라이버를 다시 설치해야 할 수 있다」가 떴다.
   → 칸을 줄여 한 번 더 묻고, 카드가 보이면 재설치를 권하지 않는다.
2. NVIDIA + 내장 그래픽 PC 에 「OLLAMA_VULKAN=0 을 권합니다」라고 **말만** 했다(사람이 환경변수를 만질 수 없다).
   → 마법사가 모델을 올리기 전에 직접 맞춘다. 사람이 켜 둔 값은 안 덮는다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from alture_jarvis import setup_profile as sp
from alture_jarvis.ollama_install import OllamaInstaller


def _smi(returns):
    calls = []

    def run(args, **_kwargs):
        calls.append(args[1])
        return returns.pop(0)

    return run, calls


def test_a_failing_full_query_is_retried_with_the_minimal_one() -> None:
    run, calls = _smi([
        SimpleNamespace(returncode=2, stdout="", stderr='Field "display_active" is not a valid field to query.'),
        SimpleNamespace(returncode=0, stdout="0, NVIDIA GeForce RTX 5050 Laptop GPU, 8151, 300\n", stderr=""),
    ])

    cards, error = sp._run_nvidia_smi(run)

    assert error == "" and len(calls) == 2
    assert cards[0]["name"].endswith("RTX 5050 Laptop GPU") and cards[0]["vram_total_gb"] == 7.96
    assert cards[0]["display_active"] is True  # 모르면 화면용 1GB 를 비워 두는 쪽으로


def test_a_failure_keeps_its_original_words_for_diagnosis() -> None:
    run, _ = _smi([SimpleNamespace(returncode=9, stdout="", stderr="NVIDIA-SMI has failed")] * 2)

    cards, error = sp._run_nvidia_smi(run)

    assert cards == [] and error == "nvidia_smi_error"
    assert "NVIDIA-SMI has failed" in sp.last_nvidia_smi_detail


def _laptop(**ollama):
    return {"gpus": [{"name": "NVIDIA GeForce RTX 5050 Laptop GPU", "vram_total_gb": 7.96, "vendor": "nvidia",
                      "integrated": False, "backend": "cuda", "display_active": True, "source": "registry"},
                     {"name": "Intel(R) Graphics", "vram_total_gb": 2.0, "vendor": "intel", "integrated": True,
                      "backend": "vulkan", "display_active": True, "source": "registry"}],
            "gpu_error": "nvidia_smi_error", "ram_gb": 16.0, "disk_free_gb": 200.0,
            "ollama": {"installed": [], "vulkan_enabled": False, "vulkan_setting": "", **ollama}}


def test_a_visible_card_is_not_told_to_reinstall_its_driver() -> None:
    rec = sp.recommend(_laptop())
    assert not any("다시 설치" in line for line in rec["warnings"])
    assert any("실제로 돌려서" in line for line in rec["warnings"])


def test_no_card_at_all_still_mentions_the_driver() -> None:
    rec = sp.recommend({"gpus": [], "gpu_error": "nvidia_smi_error", "ollama": {}})
    assert any("드라이버" in line for line in rec["warnings"])


def test_nvidia_plus_integrated_becomes_a_fix_not_advice() -> None:
    rec = sp.recommend(_laptop())
    assert rec["fixes"] == ["ollama_gpu_only"]
    assert not any("OLLAMA_VULKAN" in line for line in rec["warnings"]), "사람에게 환경변수 이름을 보여 주지 않는다"
    for setting in ("off", "on"):
        assert sp.recommend(_laptop(vulkan_setting=setting))["fixes"] == [], setting


def _installer(tmp_path: Path, versions: list[str]) -> tuple[OllamaInstaller, list]:
    launched: list = []
    installer = OllamaInstaller(install_root=tmp_path, popen=lambda cmd, **kw: launched.append((cmd, kw)))
    installer.running_version = lambda: versions.pop(0) if versions else "0.32.14"  # type: ignore[method-assign]
    return installer, launched


def test_the_fix_does_not_overwrite_what_the_person_turned_on(tmp_path: Path) -> None:
    installer, launched = _installer(tmp_path, [])
    wrote: list = []

    result = installer.fix_gpu_selection(vulkan_setting=lambda: "on", write_setting=lambda: wrote.append(1) or True)

    assert result == {"ok": False, "error": "user_set_vulkan_on"} and wrote == [] and launched == []


def test_an_external_ollama_is_stopped_then_restarted_with_nvidia_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_VULKAN", raising=False)
    # 켜져 있음 → (끄고 나서) 꺼짐 확인 → 새로 켠 뒤 응답
    installer, launched = _installer(tmp_path, ["0.32.14", "", "", "0.32.14"])
    killed: list[int] = []
    rows = [{"pid": "11", "name": "ollama app.exe", "path": r"C:\Users\u\AppData\Local\Programs\Ollama\ollama app.exe"},
            {"pid": "12", "name": "ollama.exe", "path": r"C:\Users\u\AppData\Local\Programs\Ollama\ollama.exe"}]

    result = installer.fix_gpu_selection(vulkan_setting=lambda: "", write_setting=lambda: True,
                                         find_processes=lambda: rows, kill=killed.append, wait_sec=2)

    assert result["ok"] and result["restarted"] == "external" and result["setting_written"]
    assert killed == [11, 12]
    command, kwargs = launched[0]
    assert command == [rows[0]["path"]], "트레이 앱으로 다시 켜야 사람이 평소 보던 Ollama 그대로다"
    assert kwargs["env"]["OLLAMA_VULKAN"] == "0"


def test_a_setting_that_could_not_be_written_is_not_reported_as_done(tmp_path: Path) -> None:
    installer, launched = _installer(tmp_path, ["0.32.14"])

    result = installer.fix_gpu_selection(vulkan_setting=lambda: "", write_setting=lambda: False)

    assert result == {"ok": False, "error": "setting_not_written"} and launched == []



# ── 드라이버 상태: 「없다」와 「업데이트 뒤 망가졌다」를 가른다 (2026-09-17 제품 요청) ─────────────
def _vc(name: str, code: int = 0, driver: str = "32.0.16.1088", vendor: str = "VEN_10DE") -> dict:
    return {"Name": name, "PNPDeviceID": f"PCI\\{vendor}&DEV_2204", "ConfigManagerErrorCode": code, "DriverVersion": driver}


INTEL = _vc("Intel(R) UHD Graphics 770", vendor="VEN_8086", driver="32.0.101.7082")


def test_driver_states_are_told_apart_by_windows_error_codes() -> None:
    cases = {
        "ok": ([_vc("NVIDIA GeForce RTX 3090"), INTEL], False, ""),
        "missing": ([_vc("Microsoft Basic Display Adapter", code=0, driver="10.0.26100.1"), INTEL], False, "nvidia_smi_missing"),
        "missing ": ([_vc("NVIDIA GeForce RTX 5050 Laptop GPU", code=28, driver="")], False, "nvidia_smi_missing"),
        "broken": ([_vc("NVIDIA GeForce RTX 3090", code=31)], False, "nvidia_smi_error"),
        "reboot_pending": ([_vc("NVIDIA GeForce RTX 3090", code=31)], True, "nvidia_smi_error"),
        "disabled": ([_vc("NVIDIA GeForce RTX 3090", code=22)], False, "nvidia_smi_error"),
        "mismatch": ([_vc("NVIDIA GeForce RTX 3090"), _vc("NVIDIA GeForce RTX 3060", driver="32.0.15.6094")], False, ""),
        "smi_only": ([_vc("NVIDIA GeForce RTX 5050 Laptop GPU"), INTEL], False, "nvidia_smi_error"),
        "no_nvidia": ([INTEL], False, "nvidia_smi_missing"),
        "unknown": ([], False, ""),
    }
    for expected, (rows, reboot, smi) in cases.items():
        assert sp.classify_driver(rows, reboot_pending=reboot, smi_error=smi)["state"] == expected.strip(), expected


def test_this_pcs_real_readout_is_ok() -> None:
    """이 PC 실측(2026-09-17): 가상 디스플레이·인텔·3060·3090 전부 코드 0, NVIDIA 두 장 같은 버전."""
    rows = [{"Name": "SudoMaker Virtual Display Adapter", "PNPDeviceID": r"ROOT\DISPLAY\0000", "ConfigManagerErrorCode": 0,
             "DriverVersion": "1.10.9.289"}, INTEL, _vc("NVIDIA GeForce RTX 3060"), _vc("NVIDIA GeForce RTX 3090")]
    assert sp.classify_driver(rows, reboot_pending=False, smi_error="")["state"] == "ok"


def test_each_driver_state_becomes_one_plain_instruction_not_a_reinstall_by_default() -> None:
    laptop = _laptop()
    laptop["gpu_driver"] = sp.classify_driver([_vc("NVIDIA GeForce RTX 5050 Laptop GPU"), INTEL],
                                              reboot_pending=False, smi_error="nvidia_smi_error")
    warnings = sp.recommend(laptop)["warnings"]
    assert any("그대로 진행" in w for w in warnings) and not any("다시 설치" in w for w in warnings)

    laptop["gpu_driver"] = {"state": "reboot_pending"}
    warnings = sp.recommend(laptop)["warnings"]
    assert any("다시 시작" in w for w in warnings) and any("새로 설치할 필요는 없습니다" in w for w in warnings)

    laptop["gpu_driver"] = {"state": "broken", "code": 43}
    assert any("코드 43" in w for w in sp.recommend(laptop)["warnings"])


def test_a_16gb_pc_is_not_warned_about_memory() -> None:
    """16GB PC 는 윈도우에 15.7GB 로 보인다 — 「16GB 보다 적으면 느려질 수 있습니다」가 멀쩡한 PC 에 떴다(2026-10-01 AWS g4dn)."""
    rec = sp.recommend({**_laptop(), "ram_gb": 15.7})
    assert not any("시스템 메모리" in line for line in rec["warnings"])


def test_a_12gb_pc_is_still_warned() -> None:
    rec = sp.recommend({**_laptop(), "ram_gb": 11.7})
    assert any("시스템 메모리가 11.7GB" in line for line in rec["warnings"])


def test_a_restarted_ollama_gets_the_persons_card_limit_back(tmp_path: Path, monkeypatch) -> None:
    """2026-10-01 밤: 컨텍스트를 적용하며 다시 켠 Ollama 가 손자리 자신의 GPU 설정(모든 카드)을 물려받아 3090 + 3060 에
    모델을 나눠 올렸다. 다시 켤 때는 사용자가 Ollama 를 위해 정해 둔 `CUDA_VISIBLE_DEVICES=0` 을 돌려준다."""
    from alture_jarvis.gpu_policy import INHERITED_KEY, INHERITED_ORDER_KEY

    monkeypatch.delenv("OLLAMA_VULKAN", raising=False)
    monkeypatch.setenv(INHERITED_KEY, "0")
    monkeypatch.setenv(INHERITED_ORDER_KEY, "PCI_BUS_ID")
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)  # 손자리 자신은 모든 카드를 본다(gpu_policy)
    installer, launched = _installer(tmp_path, ["0.32.14", "", "", "0.32.14"])
    rows = [{"pid": "11", "name": "ollama app.exe", "path": r"C:\Users\u\AppData\Local\Programs\Ollama\ollama app.exe"}]
    installer.fix_gpu_selection(vulkan_setting=lambda: "", write_setting=lambda: True,
                                find_processes=lambda: rows, kill=lambda pid: None, wait_sec=2)
    env = launched[0][1]["env"]
    assert env["CUDA_VISIBLE_DEVICES"] == "0" and env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    assert INHERITED_KEY not in env
