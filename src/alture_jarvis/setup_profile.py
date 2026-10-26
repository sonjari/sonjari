"""첫 실행 1단계 — **이 PC 를 재고, 맞는 모델을 계산한다.**

## 왜 (2026-09-13, 전략안 §43)

공개 제품은 사용자가나 Claude 가 옆에 붙어 깔아 주지 않아도 돼야 한다. 그러려면
「이 PC 에 무엇을 올려야 하나」를 자비스가 스스로 답해야 한다.

## 세 가지 규율

1. **추천은 코드가 계산한다.** 설치 중엔 대화할 모델이 아직 없다. 화면의 어시스턴트는
   여기서 나온 `reasons` 를 말로 옮길 뿐이다 — 「판정은 코드가, 말은 모델이」.
2. **사양표만으로 끝내지 않는다.** 모델이 이미 있으면 **실제로 토큰을 생성**시켜 속도를
   잰다(`micro_bench`). 이 저장소가 겪은 고장(드라이버 탈락 · Vulkan 선택 · 태그 갈림)은
   전부 사양표로는 안 보였다.
3. **안 잰 것은 안 쟀다고 말한다.** 9B 의 16K·32K 는 VRAM 만 쟀고 일 성공률은 131K 에서만
   쟀다. 그 자리의 추천은 `confidence: "memory_only"` 로 나간다.

## 하지 않는 것

- 아무것도 설치·변경하지 않는다. 읽기와(있으면) 짧은 생성 한 번뿐이다.
- 비밀을 읽지 않는다. 환경변수는 `OLLAMA_VULKAN` · `OLLAMA_MODELS` 두 개만 본다.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .model_catalog import CATALOG, EXTERNAL_BY_TIER, CatalogModel, by_key, tier_for, is_open_license, text_only_need

#: 화면 출력이 물린 GPU 는 창·바탕화면이 VRAM 을 나눠 쓴다. 노트북에서 특히 크다.
DISPLAY_RESERVE_GB = 1.0
#: 출력이 안 물린 GPU 도 드라이버·CUDA 문맥이 조금 먹는다.
BASE_RESERVE_GB = 0.5
#: 이보다 느리면 문서 한 건이 몇 분씩 걸린다 — 경고한다.
SLOW_TOKENS_PER_SEC = 15.0
#: 모델을 받고도 남아야 할 디스크.
DISK_MARGIN_GB = 2.0
#: 시스템 메모리가 이보다 적으면 모델을 올리다 스왑으로 느려진다.
#: ★ 16.0 이 아니라 15.0 (2026-10-01 AWS). **16GB PC 는 윈도우에 15.3~15.9GB 로 보인다**(펌웨어·내장 그래픽 몫) —
#:   16.0 기준이면 멀쩡한 16GB PC 마다 「16GB 보다 적으면 느려질 수 있습니다」가 떴다(AWS g4dn 15.7GB, 09-29·10-01 두 번).
#:   경고가 겨누는 것은 12GB·8GB 급이다.
LOW_RAM_GB = 15.0
#: 스토어 최소 사양·안내 문구에 같이 쓰는 권장 그래픽카드 메모리.
MIN_RECOMMENDED_VRAM_GB = 8


# ── 1. 재기 ───────────────────────────────────────────────────────────────────
_NVIDIA_QUERY = "index,name,memory.total,memory.used,driver_version,display_active"


def parse_nvidia_smi(csv_text: str) -> list[dict[str, Any]]:
    """`nvidia-smi --query-gpu=… --format=csv,noheader,nounits` 출력 → 카드 목록."""
    cards: list[dict[str, Any]] = []
    for line in (csv_text or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            cards.append({
                "index": int(parts[0]),
                "name": parts[1],
                "vram_total_gb": round(int(float(parts[2])) / 1024, 2),
                "vram_used_gb": round(int(float(parts[3])) / 1024, 2),
                "driver": parts[4],
                "display_active": parts[5].lower() in {"enabled", "yes", "1", "on"},
            })
        except ValueError:
            continue
    return cards


def annotate_gpus(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """카드마다 **예약분과 쓸 수 있는 메모리**를 붙인다.

    화면(메모리 자)이 이 값을 그대로 그린다. 화면이 「화면 출력은 1GB」를 따로 적으면
    두 벌이 되고 갈린다 — 규칙은 여기 한 곳이다.
    """
    for card in gpus:
        reserve = DISPLAY_RESERVE_GB if card.get("display_active") else BASE_RESERVE_GB
        card["reserve_gb"] = reserve
        card["usable_gb"] = round(max(0.0, float(card.get("vram_total_gb") or 0) - reserve), 2)
    return gpus


#: 첫 질문이 실패하면 쓰는 최소 질문. 앞 네 칸만 있으면 카드를 셀 수 있다(나머지는 빈 값으로 채운다).
_NVIDIA_QUERY_MINIMAL = "index,name,memory.total,memory.used"

#: 마지막 `nvidia-smi` 실패의 원문 — 화면 문구가 아니라 진단용이다(`detect` 가 프로필에 싣는다).
last_nvidia_smi_detail = ""


def _run_nvidia_smi(run: Callable[..., Any] = subprocess.run) -> tuple[list[dict[str, Any]], str]:
    """★ 2026-09-16 밤 노트북(RTX 5050 Laptop) 첫 설치: 카드는 레지스트리로 멀쩡히 보이는데 이 호출만 실패해서
    「드라이버가 응답하지 않습니다 — 드라이버를 다시 설치해야 할 수 있습니다」가 떴다. 카드가 보이는데 재설치를
    권하는 것은 틀린 조언이다. 그래서 (1) 칸을 줄인 질문으로 한 번 더 묻고 (2) 실패 원문을 남긴다.
    """
    global last_nvidia_smi_detail
    last_nvidia_smi_detail = ""
    failure = ""
    for query in (_NVIDIA_QUERY, _NVIDIA_QUERY_MINIMAL):
        try:
            out = run(
                ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=20, check=False,
            )
        except FileNotFoundError:
            return [], "nvidia_smi_missing"
        except Exception as exc:  # noqa: BLE001 — 못 잰 것도 결과다
            failure = f"nvidia_smi_failed:{type(exc).__name__}"
            last_nvidia_smi_detail = str(exc)[:300]
            continue
        if out.returncode != 0:
            # ★ 드라이버가 떨어지면 여기로 온다(윈도우 업데이트가 3090 을 떨어뜨린 날).
            #   「GPU 없음」과 「GPU 가 안 보임」은 다음에 할 일이 다르다.
            failure = "nvidia_smi_error"
            last_nvidia_smi_detail = (f"exit {out.returncode}: " + ((out.stderr or "") + (out.stdout or "")).strip())[:300]
            continue
        text = out.stdout if query == _NVIDIA_QUERY else "\n".join(
            line + ", , Enabled" for line in (out.stdout or "").splitlines() if line.strip())
        cards = parse_nvidia_smi(text)
        if cards:
            return annotate_gpus(cards), ""
        failure = failure or "nvidia_smi_error"
    return [], failure


# ── 1-1. 드라이버 상태 — 「없다」와 「업데이트 뒤 망가졌다」를 가른다 (2026-09-17 제품 요청) ─────────────
#
# 노트북 첫 설치에서 `nvidia-smi` 한 번 실패로 「드라이버를 다시 설치해야 할 수 있다」가 떴다. 드라이버는 한 번 깔리면
# 지워지는 일이 거의 없고, 대개 **윈도우 업데이트가 바꾸는 중**이거나 **바꾼 뒤 한쪽만 된** 것이다(2026-08 이 PC 의 3090 도
# 그랬다 — Error 31·카드별 버전 갈림). 사람이 할 일이 전부 다르다: 설치 · 재시작 · 장치 켜기 · 그냥 진행.
# 판정은 `nvidia-smi` 가 아니라 **윈도우가 장치마다 매기는 오류 코드**(Win32_VideoController.ConfigManagerErrorCode)로 한다.

_NVIDIA_VENDOR = "VEN_10DE"
#: 장치 관리자 오류 코드 → 뜻. https://learn.microsoft.com/windows-hardware/drivers/install/device-manager-error-messages
_MISSING_CODES = {28, 1, 18}          # 드라이버 없음 · 구성 안 됨 · 다시 설치 필요
_BROKEN_CODES = {10, 31, 43, 39, 37, 12, 14, 21}   # 시작 못 함 · 제대로 안 됨 · 장치가 문제 보고 · 로드 실패 · 재시작 필요 등
_DISABLED_CODES = {22}


def classify_driver(controllers: list[dict[str, Any]], *, reboot_pending: bool, smi_error: str) -> dict[str, Any]:
    """**순수 함수.** 비디오 컨트롤러 목록 → 드라이버 상태 하나와 그 근거.

    state: ok · missing · broken · disabled · reboot_pending · mismatch · smi_only · no_nvidia · unknown
    """
    nvidia = [row for row in controllers if _NVIDIA_VENDOR in str(row.get("PNPDeviceID") or "").upper()]
    cards = [{"name": str(row.get("Name") or ""), "code": int(row.get("ConfigManagerErrorCode") or 0),
              "driver": str(row.get("DriverVersion") or "")} for row in nvidia]
    base = {"cards": cards, "reboot_pending": bool(reboot_pending), "smi_error": smi_error}
    if not controllers:
        return {**base, "state": "unknown"}
    if not nvidia:
        return {**base, "state": "no_nvidia"}
    basic = [c for c in cards if "basic display" in c["name"].lower() or "기본 디스플레이" in c["name"]]
    if basic or any(c["code"] in _MISSING_CODES for c in cards) or all(not c["driver"] for c in cards):
        return {**base, "state": "missing"}
    if any(c["code"] in _DISABLED_CODES for c in cards):
        return {**base, "state": "disabled"}
    broken = [c for c in cards if c["code"] in _BROKEN_CODES or c["code"] not in (0, *_DISABLED_CODES)]
    if broken:
        return {**base, "state": "reboot_pending" if reboot_pending else "broken",
                "code": broken[0]["code"]}
    if len({c["driver"] for c in cards if c["driver"]}) > 1:
        return {**base, "state": "reboot_pending" if reboot_pending else "mismatch"}
    if smi_error == "nvidia_smi_error":
        return {**base, "state": "reboot_pending" if reboot_pending else "smi_only"}
    return {**base, "state": "ok"}


def _video_controllers() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
             "Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID,ConfigManagerErrorCode,DriverVersion "
             "| ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads(done.stdout or "[]")
    except Exception:  # noqa: BLE001 — 못 읽으면 판정을 안 한다(unknown)
        return []
    return [data] if isinstance(data, dict) else [row for row in data if isinstance(row, dict)]


def _reboot_pending() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        for path in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
                     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"):
            try:
                winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path))
                return True
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        return False
    return False


#: 드라이버 상태 → 사람이 할 일 한 줄. 화면이 이 문장을 그대로 쓴다.
DRIVER_ADVICE: dict[str, str] = {
    "missing": "NVIDIA 그래픽카드는 있는데 드라이버가 설치돼 있지 않습니다 — NVIDIA 공식 드라이버(nvidia.com/drivers)를 "
               "설치한 뒤 다시 확인해 주세요.",
    "disabled": "NVIDIA 그래픽카드가 장치 관리자에서 꺼져 있습니다 — 장치 관리자 › 디스플레이 어댑터에서 「디바이스 사용」을 "
                "누른 뒤 다시 확인해 주세요.",
    "reboot_pending": "윈도우 업데이트가 그래픽 드라이버를 바꾸는 중입니다 — PC 를 다시 시작한 뒤 다시 확인해 주세요. "
                      "드라이버를 새로 설치할 필요는 없습니다.",
    "broken": "그래픽카드 드라이버가 오류 상태입니다(장치 관리자 코드 {code}) — 윈도우 업데이트 직후라면 먼저 PC 를 다시 "
              "시작하고, 그래도 같으면 NVIDIA 드라이버를 다시 설치해 주세요.",
    "mismatch": "그래픽카드마다 드라이버 버전이 다릅니다(업데이트가 한쪽만 된 상태) — PC 를 다시 시작하고, 그래도 같으면 "
                "NVIDIA 드라이버를 다시 설치해 주세요.",
    "smi_only": "그래픽카드와 드라이버는 정상인데 세부 정보(nvidia-smi)만 못 읽었습니다 — 그대로 진행합니다. 모델을 받은 뒤 "
                "실제로 한 번 돌려서 그래픽카드에서 도는지 확인합니다.",
}


# ── 1-2. NVIDIA 밖의 카드 (M1, 2026-09-15) ──────────────────────────────────────
# 전 세계 PC 는 NVIDIA 만이 아니다. `nvidia-smi` 만 보면 AMD·인텔 사용자는 첫 화면에서 막힌다.
#
# ★ 메모리는 `Win32_VideoController.AdapterRAM` 을 쓰면 안 된다 — 32비트라 4GB 에서 잘린다(24GB 카드도 4GB).
#   드라이버가 레지스트리 표시장치 클래스 키에 적는 `HardwareInformation.qwMemorySize`(64비트)를 읽는다.
# ★ Ollama 공식 문서(2026-09-15 확인, docs.ollama.com/gpu): Windows AMD ROCm 은 RX 7900 XTX·7900 XT·7900 GRE·
#   7800 XT·7700 XT·7600 XT·7600 · PRO W7900~W7500, 그 밖의 카드는 **기본으로 켜진 Vulkan** 으로 돈다.
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_VENDORS = {"10de": "nvidia", "1002": "amd", "8086": "intel"}
_AMD_ROCM_WINDOWS = ("7900 xtx", "7900 xt", "7900 gre", "7800 xt", "7700 xt", "7600 xt", "rx 7600",
                     "w7900", "w7800", "w7700", "w7600", "w7500")
#: 이보다 작은 전용 메모리는 내장 그래픽으로 본다(인텔 UHD·AMD APU 는 수백 MB~2GB 를 보고한다).
INTEGRATED_BELOW_GB = 2.5


def parse_adapters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """레지스트리 표시장치 항목 → 카드 목록. 순수 함수 — 시험은 여기에 건다."""
    cards: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("DriverDesc") or "").strip()
        device = str(row.get("MatchingDeviceId") or "").lower()
        if not name or "microsoft basic" in name.lower() or "remote" in name.lower():
            continue
        vendor = next((v for code, v in _VENDORS.items() if f"ven_{code}" in device), "other")
        raw = row.get("HardwareInformation.qwMemorySize")
        if raw is None:
            raw = row.get("HardwareInformation.MemorySize")
        if isinstance(raw, (bytes, bytearray)):
            raw = int.from_bytes(bytes(raw)[:8], "little")
        try:
            vram = round(int(raw or 0) / 2**30, 2)
        except (TypeError, ValueError):
            vram = 0.0
        if vendor == "other" and vram <= 0:
            # 이 PC 실측: 가상 디스플레이·원격 드라이버가 메모리 0 으로 잡혔다(SudoMaker Virtual Display 등).
            continue
        lowered = name.lower()
        backend = {"nvidia": "cuda", "amd": "rocm" if any(m in lowered for m in _AMD_ROCM_WINDOWS) else "vulkan"}.get(
            vendor, "vulkan")
        cards.append({
            "name": name, "vendor": vendor, "vram_total_gb": vram,
            "integrated": vram < INTEGRATED_BELOW_GB, "backend": backend, "source": "registry",
        })
    return cards


def _registry_adapters() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return []
    rows: list[dict[str, Any]] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS)
    except OSError:
        return []
    with root:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if not sub.isdigit():
                continue
            row: dict[str, Any] = {}
            try:
                with winreg.OpenKey(root, sub) as key:
                    for value in ("DriverDesc", "MatchingDeviceId", "HardwareInformation.qwMemorySize",
                                  "HardwareInformation.MemorySize"):
                        try:
                            row[value] = winreg.QueryValueEx(key, value)[0]
                        except OSError:
                            pass
            except OSError:
                continue
            rows.append(row)
    return parse_adapters(rows)


def merge_gpus(nvidia: list[dict[str, Any]], adapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """nvidia-smi 카드(더 정확)를 앞에, 레지스트리에서만 보이는 NVIDIA 밖의 카드를 뒤에 붙인다."""
    cards = [{**card, "vendor": "nvidia", "backend": "cuda", "integrated": False, "source": "nvidia-smi"}
             for card in nvidia]
    for adapter in adapters:
        if adapter["vendor"] == "nvidia" and nvidia:
            continue  # 같은 카드를 두 번 세지 않는다
        cards.append({**adapter, "index": len(cards), "vram_used_gb": None, "driver": "",
                      # 레지스트리로는 화면 출력 여부를 모른다 — 보수적으로 1GB 를 비워 둔다.
                      "display_active": True})
    return annotate_gpus(cards)


def _ram_gb() -> float | None:
    if os.name != "nt":
        return None

    class _Status(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _Status()
    status.dwLength = ctypes.sizeof(_Status)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except Exception:  # noqa: BLE001
        return None
    return round(status.ullTotalPhys / 2**30, 1)


def _models_dir() -> Path:
    raw = os.environ.get("OLLAMA_MODELS", "").strip()
    return Path(raw) if raw else Path.home() / ".ollama" / "models"


def _disk_free_gb(path: Path) -> float | None:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return round(shutil.disk_usage(probe).free / 2**30, 1)
    except OSError:
        return None


def _vulkan_setting() -> str:
    """`OLLAMA_VULKAN` 을 사람이 어떻게 적었나 — `on` / `off` / ``(안 적음 = Ollama 기본값, 지금은 켜짐)."""
    value = os.environ.get("OLLAMA_VULKAN", "")
    if not value and os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value = str(winreg.QueryValueEx(key, "OLLAMA_VULKAN")[0])
        except OSError:
            value = ""
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return "on"
    if value in {"0", "false", "no", "off"}:
        return "off"
    return ""


def _vulkan_enabled() -> bool:
    """★ 부팅 직후 Ollama 가 CUDA 대신 내장 그래픽(Vulkan)을 잡아 적재가 통째로 실패했다."""
    value = os.environ.get("OLLAMA_VULKAN", "")
    if not value and os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value = str(winreg.QueryValueEx(key, "OLLAMA_VULKAN")[0])
        except OSError:
            value = ""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_json(url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — 안 떠 있는 것도 결과다
        return None


def detect(ollama_base_url: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    """이 PC 를 **읽기만** 해서 잰다."""
    nvidia, gpu_error = _run_nvidia_smi()
    gpus = merge_gpus(nvidia, _registry_adapters())
    driver = classify_driver(_video_controllers(), reboot_pending=_reboot_pending(), smi_error=gpu_error)
    models_dir = _models_dir()
    version = _get_json(f"{ollama_base_url}/api/version")
    tags = _get_json(f"{ollama_base_url}/api/tags") or {}
    return {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "os": platform.platform(),
        "cpu": platform.processor() or "",
        "ram_gb": _ram_gb(),
        "gpus": gpus,
        "gpu_error": gpu_error,
        "gpu_error_detail": last_nvidia_smi_detail,
        "gpu_driver": driver,
        "disk_free_gb": _disk_free_gb(models_dir),
        "models_dir": str(models_dir),
        "ollama": {
            "reachable": version is not None,
            "version": (version or {}).get("version", ""),
            "installed": sorted(str(m.get("name") or "") for m in tags.get("models") or []),
            "vulkan_enabled": _vulkan_enabled(),
            "vulkan_setting": _vulkan_setting(),
        },
    }


# ── 2. 실제로 돌려 보기 ───────────────────────────────────────────────────────
def micro_bench(
    ollama_base_url: str,
    model_tag: str,
    num_ctx: int,
    *,
    keep_alive: str = "30m",
    post: Callable[[str, dict[str, Any], float], dict[str, Any]] | None = None,
    extra_options: dict[str, Any] | None = None,
    num_predict: int = 64,
    prompt: str = "",
) -> dict[str, Any]:
    """토큰을 **실제로** 생성시켜 속도를 잰다.

    `extra_options`·`num_predict`·`prompt` 는 같은 모델을 **설정만 바꿔** 견줄 때 쓴다(미리 내다보기 끔·켬).

    ★ `num_ctx` 는 **자비스가 쓸 값과 같아야 한다.** 다르면 Ollama 가 러너를 새로 띄워
      이미 올라간 모델을 쫓아낸다(자비스가 몇 분씩 멈춘 사고의 원인 하나).
    ★ `think: false` — 젬마·큐원은 생각 모델이라 안 끄면 예산을 생각에 다 쓰고 답이 빈다.
    ★ `keep_alive` 를 짧게 주지 않는다 — 짧게 찌르는 검사가 모델을 내리는 주범이었다.
    """
    body = {
        "model": model_tag,
        "prompt": prompt or "1부터 30까지 숫자를 쉼표로 이어서 적어라.",
        "stream": False,
        "think": False,
        "keep_alive": keep_alive,
        "options": {"num_predict": int(num_predict), "num_ctx": int(num_ctx), "temperature": 0, **(extra_options or {})},
    }
    started = time.monotonic()
    try:
        reply = (post or _post_json)(f"{ollama_base_url}/api/generate", body, 180.0)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}", "model": model_tag}
    eval_count = int(reply.get("eval_count") or 0)
    eval_ns = int(reply.get("eval_duration") or 0)
    text = str(reply.get("response") or "")
    if eval_count <= 0 or eval_ns <= 0 or not text.strip():
        # 200 이 왔는데 글자가 없으면 성공이 아니다(생존 검사는 실제 왕복으로).
        return {"ok": False, "error": "empty_generation", "model": model_tag}
    return {
        "ok": True,
        "model": model_tag,
        "num_ctx": int(num_ctx),
        "tokens_per_sec": round(eval_count / (eval_ns / 1e9), 1),
        "load_sec": round(int(reply.get("load_duration") or 0) / 1e9, 1),
        "wall_sec": round(time.monotonic() - started, 1),
    }


def _post_json(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # ★ 2026-09-18: Ollama 는 **왜 안 되는지를 본문에 적어 보낸다**
        #   (`{"error":"error starting llama-server: llama-server binary not found ..."}`).
        #   본문을 안 읽으면 남는 것은 「HTTP Error 500」뿐이라, 설치가 반쪽인 것을 드라이버 탓으로 보게 된다.
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
            detail = str(payload.get("error") or "")[:400]
        except Exception:  # noqa: BLE001 — 본문이 JSON 이 아니면 상태 코드만 남는다
            detail = ""
        raise RuntimeError(f"HTTP {exc.code}: {detail}" if detail else f"HTTP {exc.code}") from exc


# ── 3. 추천 계산 ──────────────────────────────────────────────────────────────
#: 선호 순서. 앞에 있을수록 먼저 고른다. (모델, 컨텍스트, 여유 GB)
_LADDER: tuple[tuple[str, int, float], ...] = (
    # ★ 2026-10-08 대표 결정(전략안 §55-24 덧붙임): 24GB 급의 첫 추천은 Swift 27B — 같은 바깥 코드 과제 12개에서 12/12 ·
    #   가운데값 119초 · 실패 걸음 0(일반 압축판 11/12 · Ornith 35B 9/12). 라이선스에 조건이 있어, 조건 없는 대안
    #   (바로 아래 일반 압축판)을 같이 보여 준다. (그때는 「16GB 급은 그대로다」였다 — 10-10 에 바뀌었다, 아래.)
    ("qwen3.8-27b-swift", 131072, 2.0),
    ("qwen3.8-27b-swift", 65536, 1.5),
    ("qwen3.8-27b-gsq", 131072, 2.0),
    ("qwen3.8-27b-gsq", 65536, 1.5),
    ("gemma4-26b-qat", 131072, 2.0),
    # ★ 2026-10-10 대표 결정: 16GB 급의 첫 추천은 27B 작은 판(3비트 작게). 「실제 체급을 사용자는 더 좋아한다 — 대안은 카드로」.
    #   라이선스에 조건이 있어 조건 없는 대안(바로 아래 9B)이 같이 나온다. 창은 그날 잰 48K 가 먼저, 안 들어가면 32K.
    #   여유를 0.5GB 로 작게 잡았다 — 16GB 에서 빠듯한 것을 알고 올린다. 실제로 다 올라가는지는 적용 단계가 잰다.
    #   24GB 급은 위의 큰 크기가 먼저 걸려 그대로다. 근거와 잰 값은 목록의 그 항목 주석(`model_catalog.py`).
    # ★ 2026-10-12 대표 결정: 16GB 급의 첫 추천은 같은 모델의 **글만 읽기 · 창 64K**(`_TEXT_ONLY_RUNGS`). 그림 부속을 떼면
    #   1.1GB 가 비고, 그 자리에 창을 넓혀도 그림 있는 48K 보다 덜 쓴다(13.8 ↔ 14.2GB · 3090 실측). 같은 날 가격 조사 세 과제는
    #   글만 읽기 64K 가 온전한 줄 8/9, 48K 가 5/9 였다(각 1판). 내주는 것: 붙인 사진 · 그림으로 된 글 · 만든 화면을 눈으로 보는
    #   검사 — 모델 카드의 「그림 읽기」에서 되돌린다. 실제 16GB 카드에서 64K 가 다 올라가는지는 적용 단계가 잰다.
    ("qwen3.8-27b-swift-iq3xxs", 65536, 0.5),
    # ★ 2026-10-26 대표 결정: 16GB 기본(위 Swift)이 안 들어가면 Qwen3.6 35B 2비트 · 글만 읽기 · 64K(12.4GB) — 9B 보다 먼저.
    #   근거와 잰 값은 목록의 그 항목 주석(`model_catalog.py` · 2026-10-23 밤 실측).
    ("qwen3.6-35b-iq2m", 65536, 0.5),
    ("qwen3.8-27b-swift-iq3xxs", 49152, 0.5),
    ("qwen3.8-27b-swift-iq3xxs", 32768, 0.5),
    ("qwen3.5-9b", 131072, 1.0),
    ("qwen3.5-9b", 65536, 0.8),
    ("qwen3.5-9b", 32768, 0.6),
    # ★ 2026-10-14 대표 결정(「느려도 그게 맞다」): 8GB 급의 첫 추천은 9B 3비트의 **글만 읽기 · 창 48K**, 안 들어가면 32K.
    #   같은 노트북의 4B 보다 가격 조사 온전한 줄이 많았다(37/63 대 24/63 · 각 7판). 근거와 잰 메모리는 목록의 그 항목 주석.
    ("qwen3.5-9b-q3", 49152, 0.5),
    ("qwen3.5-9b-q3", 32768, 0.5),
    # ★ 2026-10-14 밤 대표 결정: 6GB 급의 첫 추천은 4B 3비트의 **글만 읽기 · 창 48K**, 안 들어가면 32K. 그림 있는 공식 4B 32K 는
    #   6GB 노트북에서 다 안 올라가 마법사가 2B 로 내려갔고, 그 2B 는 가격 조사가 0 이었다. 근거와 잰 메모리는 목록의 그 항목 주석.
    ("qwen3.5-4b-q3", 49152, 0.5),
    ("qwen3.5-4b-q3", 32768, 0.5),
    ("qwen3.5-4b", 32768, 0.5),
    ("qwen3.5-2b", 32768, 0.5),
    ("qwen3.5-9b", 16384, 0.3),
)


#: 사다리의 이 칸은 **그림 부속을 뗀 채**(「글만 읽기」) 올리는 칸이다 — (모델, 창). 메모리는 `text_only_need` 로 본다.
_TEXT_ONLY_RUNGS: frozenset[tuple[str, int]] = frozenset({("qwen3.8-27b-swift-iq3xxs", 65536), ("qwen3.6-35b-iq2m", 65536),
                                                          ("qwen3.5-9b-q3", 49152), ("qwen3.5-9b-q3", 32768),
                                                          ("qwen3.5-4b-q3", 49152), ("qwen3.5-4b-q3", 32768)})


def _ctx_label(ctx: int) -> str:
    return f"{ctx // 1024}K"


#: 올린 뒤 남는 자리가 이보다 적으면 「여유 있게」가 아니라 「빠듯하다」고 말한다.
# ★ 2026-10-12: 1.0 → 1.5. 16GB 급에 13.8GB 를 올리며(남는 것 1.2GB) 다시 「여유 있게」라고 말하게 됐다. 그날 이 PC 에서
#   화면 쪽(모니터 둘 · 창들)이 그래픽 메모리 1.8GB 를 쓰는 것을 쟀다 — 우리가 비워 두는 1GB 보다 크다. 1.5GB 가 안 남으면 빠듯하다.
TIGHT_FIT_SPARE_GB = 1.5

#: 외부 추천(추정 메모리)에 두는 여유. 추정이라 검증 모델보다 덜 믿는다.
EXTERNAL_HEADROOM_GB = 0.5
EXTERNAL_CTX = 32768


def _discrete(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """AI 모델을 올릴 수 있는 카드만. 내장 그래픽은 전용 메모리가 없어 뺀다."""
    return [g for g in profile.get("gpus") or [] if g.get("vram_total_gb") and not g.get("integrated")]


def _budget(card: dict[str, Any]) -> float:
    reserve = DISPLAY_RESERVE_GB if card.get("display_active") else BASE_RESERVE_GB
    return round(float(card["vram_total_gb"]) - reserve, 2)


def smaller_that_fits(free_gb: float | None, failed_key: str) -> tuple[CatalogModel, int, float] | None:
    """고른 모델을 못 올렸을 때 **지금 들어가는 한 단계 작은 모델** — (모델, 창, 필요한 메모리). 없으면 None.

    추천 사다리(`_LADDER`)를 위에서부터 훑어, 못 올린 모델보다 작고 지금 빈 메모리에 여유(`headroom`)까지 들어가는 첫 칸.
    같은 모델의 작은 창은 권하지 않는다 — 적용할 때 이미 한 칸씩 줄여 재 봤다(`_measure_and_save`).
    빈 메모리를 모르면(`free_gb` None) 권하지 않는다 — 들어간다고 말할 근거가 없다.
    """
    failed = by_key(failed_key)
    if free_gb is None or failed is None or not failed.vram_gb:
        return None
    smallest_failed = min(failed.vram_gb.values())
    for key, ctx, headroom in _LADDER:
        model = by_key(key)
        if model is None or key == failed_key or model.status != "verified" or ctx not in model.vram_gb:
            continue
        if (key, ctx) in _TEXT_ONLY_RUNGS:
            continue      # 이 함수의 답에는 「그림을 끈다」를 실을 칸이 없다 — 그림 있는 칸만 권한다
        need = model.vram_gb[ctx]
        if need >= smallest_failed:
            continue
        if free_gb >= need + headroom:
            return model, ctx, need
    return None


def smaller_choice(free_gb: float | None, failed_key: str) -> tuple[CatalogModel, int, float, bool] | None:
    """`smaller_that_fits` 에 **글만 읽기 칸도** 넣은 판 — (모델, 창, 필요한 메모리, 글만 읽기인가). 없으면 None.

    ★ 2026-10-26 대표 결정 「16GB 기본은 Swift, 안 들어가면 Qwen3.6 2비트」: 그 2비트는 글만 읽기 칸(12.4GB)이라
      그림 있는 칸만 보던 `smaller_that_fits` 로는 영영 안 나오고 9B 로 내려갔다. 화면이 「그림을 끄고」 적용하도록 네 번째 값을 준다.
    """
    failed = by_key(failed_key)
    if free_gb is None or failed is None or not failed.vram_gb:
        return None
    smallest_failed = min(list(failed.vram_gb.values()) + list(failed.text_only_vram_gb.values()))
    for key, ctx, headroom in _LADDER:
        model = by_key(key)
        if model is None or key == failed_key or model.status != "verified":
            continue
        text_only = (key, ctx) in _TEXT_ONLY_RUNGS
        need = text_only_need(model, ctx) if text_only else model.vram_gb.get(ctx)
        if need is None or need >= smallest_failed:
            continue
        if free_gb >= need + headroom:
            return model, ctx, need, text_only
    return None


def usable_budget_gb(profile: dict[str, Any]) -> float:
    """이 PC 가 모델에 쓸 수 있는 그래픽 메모리. 카드가 없으면 0.

    ★ 목록 밖 모델(사람이 직접 받은 것)도 **같은 자를 써야** 한다. 여기를 안 내놓으면
      화면이 제 나름의 기준으로 「가능」을 계산하게 되고, 규칙이 두 벌이면 갈린다
      (사고 Q 와 같은 가족 — 같은 것을 재는 자리가 둘이면 낮은 쪽만 일한다).
    """
    gpus = _discrete(profile)
    return _budget(max(gpus, key=lambda g: float(g["vram_total_gb"]))) if gpus else 0.0


def _external_pick(tier: int, budget: float, installed: set[str]) -> dict[str, Any] | None:
    for key in EXTERNAL_BY_TIER.get(tier, ()):
        model = by_key(key)
        if model is None or model.status != "external" or EXTERNAL_CTX not in model.vram_gb:
            continue
        need = model.vram_gb[EXTERNAL_CTX]
        if budget >= need + EXTERNAL_HEADROOM_GB:
            return {
                "kind": "external", "model_key": model.key, "name": model.name, "ollama_tag": model.ollama_tag,
                "num_ctx": EXTERNAL_CTX, "vram_estimate_gb": need, "download_gb": model.download_gb,
                "installed": model.ollama_tag in installed, "license": model.license,
                "evidence": list(model.evidence), "caution": model.caution,
                "links": [{"label": label, "url": url} for label, url in model.links],
                "checked_at": model.checked_at,
            }
    return None


def recommend(profile: dict[str, Any], bench: dict[str, Any] | None = None) -> dict[str, Any]:
    """프로필 → 추천. **순수 함수**다 — 같은 입력이면 같은 답. 시험은 여기에 건다.

    등급(카드 전체 메모리 6·8·12·16·24GB)마다 **검증 1 + 외부 1** 을 `picks` 로 준다(2026-09-15 큐레이션).
    검증 칸은 우리가 잰 모델 중 실제로 들어가는 것, 외부 칸은 등급 후보 중 추정 메모리로 들어가는 첫 모델.
    둘 다 없으면 막다른 「준비 중」 대신 이유와 권장 사양을 정직하게 말한다(CPU 경로는 만들지 않는다).
    """
    gpus = _discrete(profile)
    all_cards = [g for g in profile.get("gpus") or [] if g.get("vram_total_gb") is not None]
    warnings: list[str] = []
    ollama = profile.get("ollama") or {}
    installed = set(ollama.get("installed") or [])

    driver_state = str((profile.get("gpu_driver") or {}).get("state") or "")
    if driver_state in DRIVER_ADVICE:
        # 드라이버 판정이 있으면 그것이 먼저다 — 「없다·업데이트 중·고장·버전 갈림·smi 만 실패」는 할 일이 다르다.
        warnings.append(DRIVER_ADVICE[driver_state].format(code=(profile.get("gpu_driver") or {}).get("code", "?")))
    elif profile.get("gpu_error") == "nvidia_smi_error":
        if any(g.get("vendor") == "nvidia" for g in gpus):
            # 카드는 레지스트리로 보인다 — 드라이버 재설치를 권하면 틀린 조언이다(2026-09-16 노트북 실측).
            # 판단은 실제로 돌려 보는 적용 단계(`/api/ps` 의 그래픽카드 비율)가 한다.
            warnings.append("그래픽카드는 보이지만 세부 정보를 읽지 못했습니다. 모델을 받은 뒤 한 번 실제로 돌려서 "
                            "그래픽카드에서 도는지 확인합니다.")
        else:
            warnings.append("그래픽카드 드라이버가 응답하지 않습니다 — 윈도우 업데이트 뒤라면 드라이버를 다시 설치해야 할 수 있습니다.")
    has_nvidia = any(g.get("vendor", "nvidia") == "nvidia" for g in gpus)
    has_integrated = any(g.get("integrated") for g in all_cards)
    # ★ Vulkan 경고는 NVIDIA 카드가 있는 PC 에서만 맞다(내장 그래픽을 잡아 적재 실패 — 이 PC 실측).
    #   AMD·인텔 카드는 Vulkan 으로 **도는 것**이라, 그 사용자에게 끄라고 하면 틀린 조언이다.
    fixes: list[str] = []
    if has_nvidia and ollama.get("vulkan_setting") != "on" and (
            ollama.get("vulkan_enabled") or (has_integrated and ollama.get("vulkan_setting") != "off")):
        # ★ 2026-09-16: 예전엔 「OLLAMA_VULKAN=0 을 권합니다」라고 **말만** 했다. 이제 마법사가 모델을 올리기 전에
        #   `fixes` 를 보고 직접 맞춘다(`OllamaInstaller.fix_gpu_selection`). 사람이 켜 둔 값은 안 건드린다.
        fixes.append("ollama_gpu_only")
        warnings.append("NVIDIA 카드와 내장 그래픽이 같이 있습니다 — 모델을 올리기 전에 Ollama 가 NVIDIA 카드만 쓰도록 "
                        "Sonjari가 맞춥니다.")
    ram = profile.get("ram_gb")
    if isinstance(ram, (int, float)) and ram < LOW_RAM_GB:
        warnings.append(f"시스템 메모리가 {ram:g}GB 입니다 — 16GB 급보다 적으면 모델을 올릴 때 느려질 수 있습니다.")

    if not gpus:
        integrated = [g for g in all_cards if g.get("integrated")]
        reasons = ([f"{integrated[0]['name']} 은 내장 그래픽이라 AI 모델을 올릴 전용 메모리가 없습니다."]
                   if integrated else ["AI 모델을 올릴 그래픽카드가 보이지 않습니다."])
        reasons.append(f"Sonjari는 그래픽카드에서 도는 로컬 AI 가 필요합니다 — 그래픽카드 메모리 {MIN_RECOMMENDED_VRAM_GB}GB 이상을 권합니다.")
        return {"mode": "no_gpu", "model_key": None, "num_ctx": None, "confidence": "hardware",
                "reasons": reasons, "warnings": warnings, "fixes": fixes, "alternatives": [], "budget_gb": 0.0,
                "tier_gb": None, "picks": [], "card": None}

    card = max(gpus, key=lambda g: float(g["vram_total_gb"]))
    budget = _budget(card)
    tier = tier_for(float(card["vram_total_gb"]))
    card_info = {"name": card["name"], "vendor": card.get("vendor", "nvidia"), "backend": card.get("backend", "cuda"),
                 "vram_total_gb": card["vram_total_gb"]}

    fits: list[tuple[CatalogModel, int, float, float]] = []
    for key, ctx, headroom in _LADDER:
        model = by_key(key)
        if model is None or model.status != "verified" or ctx not in model.vram_gb:
            continue
        if float(card["vram_total_gb"]) + 0.5 < model.minimum_vram_gb:
            continue
        need = model.vram_gb[ctx]
        if (key, ctx) in _TEXT_ONLY_RUNGS:
            lean = text_only_need(model, ctx)
            if lean is None:
                continue
            need = lean
        if budget >= need + headroom:
            fits.append((model, ctx, need, headroom))
    external = _external_pick(tier, budget, installed)

    if not fits and external is None:
        return {"mode": "too_small", "model_key": None, "num_ctx": None, "confidence": "hardware",
                "reasons": [
                    f"{card['name']} 의 쓸 수 있는 메모리가 약 {budget:g}GB 입니다.",
                    "Sonjari가 권하는 가장 작은 모델도 여유 있게 안 들어갑니다.",
                    f"그래픽카드 메모리 {MIN_RECOMMENDED_VRAM_GB}GB 이상을 권합니다.",
                ],
                "warnings": warnings, "fixes": fixes, "alternatives": [], "budget_gb": budget, "tier_gb": tier,
                "picks": [], "card": card_info}

    reasons = [
        f"{card['name']} · 쓸 수 있는 메모리 약 {budget:g}GB"
        + (" (화면 출력이 같은 카드라 1GB 를 비워 둡니다)" if card.get("display_active") else ""),
    ]
    if card_info["vendor"] != "nvidia":
        engine = "ROCm" if card_info["backend"] == "rocm" else "Vulkan"
        reasons.append(f"이 카드는 Ollama 가 {engine} 으로 돌립니다 — 받은 뒤 실제로 돌려 그래픽카드에 올라가는지 확인합니다.")

    picks: list[dict[str, Any]] = []
    disk = profile.get("disk_free_gb")
    if fits:
        model, ctx, need, _headroom = fits[0]
        primary_text_only = (model.key, ctx) in _TEXT_ONLY_RUNGS
        primary_installed = model.ollama_tag in installed
        confidence = "measured" if model.chain and model.chain_ctx == ctx else "memory_only"
        if budget - need >= TIGHT_FIT_SPARE_GB:
            reasons.append(f"{model.name} · 컨텍스트 {_ctx_label(ctx)} 는 올리면 {need:g}GB 입니다 — 여유 있게 들어갑니다.")
        else:
            # ★ 2026-10-10: 15GB 에 14.2GB 를 올리면서 「여유 있게」라고 말하고 있었다. 빠듯하면 빠듯하다고 말한다.
            reasons.append(f"{model.name} · 컨텍스트 {_ctx_label(ctx)} 는 올리면 {need:g}GB 입니다 — 들어가지만 빠듯합니다. "
                           "다른 프로그램이 그래픽카드를 쓰고 있으면 다 올라가지 않을 수 있습니다.")
        if primary_text_only:
            reasons.append("그림 읽기를 끄고 그만큼 창을 넓혔습니다 — 붙인 사진과 그림으로 된 글은 읽지 못합니다. "
                           "모델 카드의 「그림 읽기」에서 바꿀 수 있습니다(그러면 창이 줄어듭니다).")
        if model.chain and model.chain_ctx == ctx:
            reasons.append(f"조사해서 문서까지 만드는 우리 벤치에서 {model.chain[0]}/{model.chain[1]} 판을 해냈습니다.")
        else:
            reasons.append(f"메모리는 실제로 쟀지만, 컨텍스트 {_ctx_label(ctx)} 에서 일 성공률은 아직 안 쟀습니다.")
        picks.append({"kind": "verified", "model_key": model.key, "name": model.name, "ollama_tag": model.ollama_tag,
                      "num_ctx": ctx, "vram_gb": need, "download_gb": model.download_gb,
                      "installed": primary_installed, "confidence": confidence, "license": model.license,
                      "text_only": primary_text_only,
                      "license_open": is_open_license(model.license), "license_url": model.license_url,
                      "chain": ({"ok": model.chain[0], "total": model.chain[1], "ctx": model.chain_ctx}
                                if model.chain else None)})
        primary_key, primary_tag, primary_ctx, download = model.key, model.ollama_tag, ctx, model.download_gb
        if not is_open_license(model.license):
            # 첫 추천의 라이선스에 조건이 있으면 **조건 없는 대안**을 같이 준다 — 우리가 잰 모델 가운데 이 카드에 들어가는 다음 것.
            # 고르는 것은 사용자다. 매출을 묻지도 막지도 않는다(조건의 내용은 원문 링크가 말한다).
            for alt, alt_ctx, alt_need, _alt_headroom in fits[1:]:
                if alt.key == model.key or not is_open_license(alt.license):
                    continue
                reasons.append(f"{model.name} 의 라이선스에는 사용 조건이 있습니다 — 조건 없는 대안으로 {alt.name} 을 같이 보여 드립니다.")
                picks.append({"kind": "open_alternative", "model_key": alt.key, "name": alt.name, "ollama_tag": alt.ollama_tag,
                              "num_ctx": alt_ctx, "vram_gb": alt_need, "download_gb": alt.download_gb,
                              "installed": alt.ollama_tag in installed,
                              "confidence": "measured" if alt.chain and alt.chain_ctx == alt_ctx else "memory_only",
                              # 대안도 글만 읽기 칸일 수 있다(16GB 의 Qwen3.6 2비트 · 2026-10-26) — 화면이 그대로 그림을 끄고 적용한다.
                              "text_only": (alt.key, alt_ctx) in _TEXT_ONLY_RUNGS,
                              "license": alt.license, "license_open": True, "license_url": alt.license_url,
                              "chain": ({"ok": alt.chain[0], "total": alt.chain[1], "ctx": alt.chain_ctx} if alt.chain else None)})
                break
    else:
        assert external is not None
        primary_text_only = False
        confidence = "external"
        primary_installed = external["installed"]
        reasons.append("우리가 잰 모델 중 이 카드에 들어가는 것이 없습니다.")
        # 영문 이름은 받침을 알 수 없다 — 조사는 「모델」에 붙인다(「Qwen 3.5 4B 을」 실측).
        reasons.append(f"외부 평가가 좋은 모델({external['name']})을 권합니다 — Sonjari가 직접 시험한 모델은 아닙니다.")
        primary_key, primary_tag, primary_ctx, download = (external["model_key"], external["ollama_tag"],
                                                           external["num_ctx"], external["download_gb"])
    if external is not None:
        picks.append(external)

    if isinstance(disk, (int, float)) and not primary_installed and disk < download + DISK_MARGIN_GB:
        warnings.append(f"디스크 여유가 {disk:g}GB 입니다 — 받는 데 {download:g}GB 와 여유 2GB 가 필요합니다.")

    if bench and bench.get("ok") and bench.get("model") == primary_tag:
        speed = float(bench.get("tokens_per_sec") or 0)
        reasons.append(f"이 PC 에서 실제로 돌려 보니 초당 {speed:g} 토큰입니다.")
        if speed < SLOW_TOKENS_PER_SEC:
            warnings.append(f"초당 {speed:g} 토큰은 느린 편입니다 — 문서 한 건에 몇 분씩 걸릴 수 있습니다.")
    elif bench and not bench.get("ok"):
        warnings.append(f"모델을 실제로 돌려 보지 못했습니다: {bench.get('error', '')}")

    alternatives = [
        {"model_key": alt.key, "num_ctx": alt_ctx, "vram_gb": alt_need}
        for alt, alt_ctx, alt_need, _ in fits[1:]
        if (alt.key, alt_ctx) != (primary_key, primary_ctx)
    ]
    return {
        "mode": "local", "model_key": primary_key, "ollama_tag": primary_tag, "num_ctx": primary_ctx,
        "installed": primary_installed, "confidence": confidence, "reasons": reasons, "warnings": warnings, "fixes": fixes,
        "alternatives": alternatives, "budget_gb": budget, "tier_gb": tier, "picks": picks, "card": card_info,
        # 추천이 「그림 부속을 뗀 채」 올리라는 것인가 — 화면이 이 값으로 「글만 읽기」를 골라 두고 그렇게 적용한다.
        "text_only": primary_text_only,
    }


def _card_budget(profile: dict[str, Any]) -> float:
    gpus = _discrete(profile)
    return _budget(max(gpus, key=lambda g: float(g["vram_total_gb"]))) if gpus else 0.0


def _text_only_fitting(model: CatalogModel, budget: float) -> list[int]:
    """글만 읽기로 이 PC 에 들어가는 창들(큰 것부터)."""
    if not model.vision:
        return []
    return [ctx for ctx in sorted(set(model.vram_gb) | set(model.text_only_vram_gb), reverse=True)
            if (lean := text_only_need(model, ctx)) is not None and budget >= lean]


def pictures_too_tight(model: CatalogModel, ctx: int, profile: dict[str, Any]) -> bool:
    """이 창을 **그림을 켠 채로는 빠듯하고**(남는 자리 < `TIGHT_FIT_SPARE_GB`) 글만 읽기로는 들어가는가.

    ★ 2026-10-15 사무실 6GB 노트북: 설정 화면이 「4B 3비트 · 48K · 4.9GB — 가능」이라 해 놓고 그림을 단 채 올려 카드에 70.7% 만
      올라갔다. 그림 있는 값은 잰 것이 아니라 글만 읽기 + 부속 크기로 어림한 것이었고, Ollama 0.35 는 부속이 붙은 모델을 올릴 때
      「부속 무게 + 1GiB」를 따로 비워 둔다 — 그 1GiB 가 어림에 없다. 빠듯하면 마법사처럼 글만 읽기로 간다.
    """
    need = model.vram_gb.get(ctx)
    lean = text_only_need(model, ctx)
    if not model.vision or need is None or lean is None:
        return False
    budget = _card_budget(profile)
    return budget - need < TIGHT_FIT_SPARE_GB and budget >= lean


def catalog_view(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """갤러리용 — 모델마다 **이 PC 에 들어가는지**를 붙여 준다. 헤비 유저는 이걸 보고 고른다.

    그림을 켜도 넉넉한 창이 없고 글만 읽기로는 들어가면 그 칸은 「글만 읽기」다(`text_only` · `pictures_too_tight`) —
    화면은 그 창과 메모리를 보이고, 적용도 글만 읽기로 한다(2026-10-15).
    """
    budget = _card_budget(profile)
    installed = set((profile.get("ollama") or {}).get("installed") or [])
    view = []
    for model in CATALOG:
        fitting = [ctx for ctx, need in sorted(model.vram_gb.items(), reverse=True) if budget >= need]
        roomy = [ctx for ctx in fitting if budget - model.vram_gb[ctx] >= TIGHT_FIT_SPARE_GB]
        lean = _text_only_fitting(model, budget)
        text_only = bool(lean) and not roomy
        ctx = lean[0] if text_only else (fitting[0] if fitting else None)
        view.append({
            **model.public(),
            "installed": model.ollama_tag in installed,
            "fits": bool(fitting) or text_only,
            "largest_fitting_ctx": ctx,
            "text_only": text_only,
            "text_only_need_gb": text_only_need(model, ctx) if text_only and ctx else None,
        })
    return view
