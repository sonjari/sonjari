"""첫 실행 화면 리허설 표본 `ui/src/setup/fixturePcs.json` 을 **진짜 추천 함수로** 다시 뽑는다.

    python scripts/make_setup_fixtures.py

화면용으로 지어낸 추천이 섞이면 리허설과 실제가 갈린다. 여기서는 PC 사양(프로필)만 사람이 적고,
추천·갤러리·이미 받은 모델 칸은 `setup_profile.recommend` · `catalog_view` 출력 그대로 둔다.

이미 받은 모델의 `capabilities` 는 2026-09-15 이 PC Ollama `/api/show` 가 실제로 돌려준 값이다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alture_jarvis.model_catalog import by_tag  # noqa: E402
from alture_jarvis.setup_profile import annotate_gpus, catalog_view, recommend  # noqa: E402

OUT = ROOT / "ui" / "src" / "setup" / "fixturePcs.json"

#: 2026-09-15 이 PC `/api/show` 실측.
CAPABILITIES = {
    "gemma4:26b-a4b-it-qat": ["completion", "vision", "tools", "thinking"],
    "qwen3.5:9b": ["completion", "vision", "tools", "thinking"],
    "translategemma:4b": ["completion", "vision"],
    "bge-m3:latest": ["embedding"],
}
SIZES = {"gemma4:26b-a4b-it-qat": 14.56, "qwen3.5:9b": 6.14, "translategemma:4b": 3.1, "bge-m3:latest": 1.1}


def _nvidia(name: str, vram: float, *, display: bool) -> dict:
    return {"index": 0, "name": name, "vram_total_gb": vram, "vram_used_gb": 0.4, "driver": "610.88",
            "display_active": display, "vendor": "nvidia", "backend": "cuda", "integrated": False, "source": "nvidia-smi"}


def _other(index: int, name: str, vram: float, *, vendor: str, integrated: bool, backend: str = "vulkan") -> dict:
    return {"index": index, "name": name, "vram_total_gb": vram, "vram_used_gb": None, "driver": "",
            "display_active": True, "vendor": vendor, "backend": backend, "integrated": integrated, "source": "registry"}


def _profile(gpus: list[dict], *, ram: float, disk: float, installed: list[str], error: str = "") -> dict:
    return {
        "measured_at": "2026-09-15T18:00:00", "os": "Windows-11", "cpu": "x86_64", "ram_gb": ram,
        "gpus": annotate_gpus(gpus), "gpu_error": error, "disk_free_gb": disk, "models_dir": "C:\\Users\\me\\.ollama\\models",
        "ollama": {"reachable": True, "version": "0.34.0", "installed": installed, "vulkan_enabled": False, "vulkan_setting": ""},
    }


PCS = {
    "3090": _profile([_nvidia("NVIDIA GeForce RTX 3090", 24.0, display=False),
                      _other(1, "Intel(R) UHD Graphics 770", 2.0, vendor="intel", integrated=True)],
                     ram=64.0, disk=180.0, installed=["gemma4:26b-a4b-it-qat", "translategemma:4b", "bge-m3:latest"]),
    "4080-laptop": _profile([_nvidia("NVIDIA GeForce RTX 4080 Laptop GPU", 12.0, display=True)],
                            ram=32.0, disk=400.0, installed=[]),
    "4060-8gb": _profile([_nvidia("NVIDIA GeForce RTX 4060", 8.0, display=True)], ram=32.0, disk=300.0, installed=[]),
    "3050-laptop": _profile([_nvidia("NVIDIA GeForce RTX 3050 6GB Laptop GPU", 6.0, display=True)],
                            ram=16.0, disk=120.0, installed=[]),
    "rx7800xt": _profile([_other(0, "AMD Radeon RX 7800 XT", 16.0, vendor="amd", integrated=False, backend="rocm"),
                          _other(1, "AMD Radeon(TM) Graphics", 0.5, vendor="amd", integrated=True)],
                         ram=32.0, disk=500.0, installed=["qwen3.5:9b"], error="nvidia_smi_missing"),
    "gtx1650": _profile([_nvidia("NVIDIA GeForce GTX 1650", 4.0, display=True)], ram=16.0, disk=200.0, installed=[]),
    "no-gpu": _profile([_other(0, "Intel(R) Iris(R) Xe Graphics", 1.0, vendor="intel", integrated=True)],
                       ram=16.0, disk=200.0, installed=[], error="nvidia_smi_missing"),
}


def installed_rows(profile: dict) -> list[dict]:
    rows = []
    for name in profile["ollama"]["installed"]:
        caps = CAPABILITIES.get(name, [])
        catalog = by_tag(name)
        rows.append({"name": name, "size_gb": SIZES.get(name, 0.0), "capabilities": caps, "tools": "tools" in caps,
                     "embedding_only": "embedding" in caps and "completion" not in caps,
                     "catalog_key": catalog.key if catalog else "", "status": catalog.status if catalog else "unlisted"})
    return rows


def main() -> None:
    out = {name: {"profile": profile, "recommendation": recommend(profile), "models": catalog_view(profile),
                  "installed_models": installed_rows(profile)}
           for name, profile in PCS.items()}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for name, bundle in out.items():
        rec = bundle["recommendation"]
        print(f"{name:12s} {rec['mode']:9s} tier={rec.get('tier_gb')} picks={[(p['kind'], p['model_key']) for p in rec['picks']]}")


if __name__ == "__main__":
    main()
