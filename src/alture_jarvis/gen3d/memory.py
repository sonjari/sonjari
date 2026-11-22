"""3D 를 굽는 동안 메모리를 무엇으로 재나 — 플랫폼마다 다르다 (2026-11-14).

| 기계 | 영수증 `vram_*_mib` 에 들어가는 값 | `memory_what` |
|---|---|---|
| 윈도우 + 엔비디아 | `nvidia-smi` 그 카드 전체 사용량 | 그래픽카드 전체 사용량 |
| 맥(Apple Silicon) | 통합 메모리 전체 사용량 = 전체 − 커널이 본 남은 양(`kern.memorystatus_level`) | 통합 메모리 전체 사용량 |

맥은 그래픽 메모리가 따로 없다(16GB 하나를 나눠 씀). 그래서 맥은 **실행기 프로세스 자신의 최대 실메모리**도 같이 잰다 —
`proc_pid_rusage` 의 `ri_lifetime_max_phys_footprint`(커널이 센 최댓값 · Metal 버퍼 포함). 1초마다 읽어 끝나기 직전 값이 남는다.
`vm_stat` 의 free+inactive 는 파일 캐시를 빼먹어 남은 양을 짜게 잡는다(11-14 맥: 그 셈 5.7GB · 커널 셈 11.0GB) — 그래서 커널 값을 쓴다.
못 재면 None — 지어내지 않는다.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def gpu_used_mib(gpu: int | None) -> int | None:
    """윈도우 · 엔비디아: 그 카드의 전체 사용량(다른 프로그램 몫 포함)."""
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", str(gpu or 0)]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW, check=False)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001 — nvidia-smi 가 없으면 메모리를 안 잰다(지어내지 않는다)
        return None


def gpu_list() -> list[dict]:
    """윈도우 · 엔비디아: 카드마다 번호 · 이름 · 남은 · 전체 메모리(MiB). nvidia-smi 가 없으면 빈 목록."""
    try:
        cmd = ["nvidia-smi", "--query-gpu=index,name,memory.free,memory.total", "--format=csv,noheader,nounits"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW, check=False)
        cards = []
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                cards.append({"index": int(parts[0]), "name": parts[1], "free_mib": int(parts[2]), "total_mib": int(parts[3])})
        return cards
    except Exception:  # noqa: BLE001
        return []


def pick_gpu(cards: list[dict] | None = None) -> dict | None:
    """남은 메모리가 가장 많은 카드(11-15: 번호를 안 주면 0번 3090 — Strata 가 21.7GB 쥐고 있었다 — 에서 돌았다)."""
    cards = gpu_list() if cards is None else cards
    return max(cards, key=lambda c: c["free_mib"]) if cards else None


def _sysctl_int(name: str) -> int | None:
    try:
        out = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5, check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return int(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def unified_total_mib() -> int | None:
    total = _sysctl_int("hw.memsize")
    return int(total / 1048576) if total else None


def unified_free_mib() -> int | None:
    """맥: 커널이 본 남은 메모리(MiB) — `memory_pressure` 의 「free percentage」와 같은 값."""
    total = unified_total_mib()
    level = _sysctl_int("kern.memorystatus_level")
    if not total or level is None:
        return None
    return int(total * level / 100)


def unified_used_mib(_gpu: int | None = None) -> int | None:
    """맥: 통합 메모리 전체 사용량(MiB). 카드 번호는 받지만 쓰지 않는다(카드가 하나뿐 · 메모리는 하나)."""
    total, free = unified_total_mib(), unified_free_mib()
    return None if total is None or free is None else total - free


class _RusageV4(ctypes.Structure):
    # rusage_info_v4: uuid[16] 다음 uint64 들. 7 = ri_phys_footprint, 28 = ri_lifetime_max_phys_footprint(11-14 맥에서 확인).
    _fields_ = [("uuid", ctypes.c_uint8 * 16), ("v", ctypes.c_uint64 * 40)]


def proc_peak_mib(pid: int | None) -> int | None:
    """맥: 그 프로세스가 지금까지 쓴 최대 실메모리(MiB). 다른 기계 · 끝난 프로세스면 None."""
    if sys.platform != "darwin" or not pid:
        return None
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        buf = _RusageV4()
        if lib.proc_pid_rusage(int(pid), 4, ctypes.byref(buf)) != 0:
            return None
        return int(buf.v[28] / 1048576)
    except Exception:  # noqa: BLE001
        return None


def memory_what(platform: str, gpu: int | None = None) -> str:
    if platform == "darwin":
        return "통합 메모리 전체 사용량(맥 · 전체 − 커널이 본 남은 양) — 다른 프로그램 몫 포함 · 실행기 자신의 최대는 proc_peak_mib"
    return f"그래픽카드 전체 사용량(nvidia-smi · 카드 {gpu or 0}) — 다른 프로그램 몫 포함"
