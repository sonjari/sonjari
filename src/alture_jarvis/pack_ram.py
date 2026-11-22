"""무거운 팩 일(3D · 영상 굽기) 전에 램 비우기 — 판정 한 자리 (2026-11-17 · 설계 `docs/설계_무거운팩_램비우기_2026-11-17.ko.md`).

## 왜

11-17 새벽: Ollama 실행기(손자리 27B)가 프롬프트 캐시를 램에 24.2GB + 저장점 → 실행기 private 46GB · PC 약속 메모리 113/127.7GB.
영상 실행기가 들어오자 초당 7,760쪽 디스크 넘기기 → 시안 30~60초가 234~400초(글 읽기 단계 15~22초 → 218초).
27B 를 내리자 약속 메모리 54.7GB · 디스크 넘기기 0. 캐시 상한(24GB)은 재서 고른 값이라(작은 호출 16번 뒤 돌아오기 0.5초 대 1분)
평소엔 그대로 두고 **무거운 일 때만** 내린다.

## 지킬 것

- 못 재면 내리지 않는다(지어낸 숫자로 사람의 대화를 끊지 않는다).
- 사람이 `JARVIS_PACK_RAM_UNLOAD=0` 으로 끄면 내리지 않고 「느릴 수 있다」만 남긴다.
- 굽는 동안에는 「무거운 일 중」 깃발이 서 있어 앞부분 데우기(`runtime._front_prime_loop`)가 27B 를 도로 올리지 않는다.
- 내렸으면 굽기가 끝난 뒤 데우기 반복이 한 번 데운다(`take_reprime`) — 다음 질문이 앞부분을 처음부터 읽지 않게.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

#: 남은 램이 필요한 양의 이만큼 배가 안 되면 내린다(실행기 · 글 읽기 부품이 굽는 도중 더 잡는 몫).
NEED_FACTOR = 1.25
#: PC 약속 메모리(커밋)가 한도의 이만큼을 넘으면 내린다 — 11-17 새벽 89% 에서 디스크 넘기기가 시작됐다.
COMMIT_LIMIT_SHARE = 0.85
#: 영상 실행기(sd-cli · FastWan/Wan 5B q8) — 11-17 실측 약속 12.2GB · 글 읽기 부품 램 5.7GB(로그 text_encoders 5757MB).
VIDEO_NEED_MIB = 12_500
#: 3D 실행기(trellis-cli 512 · 윈도우) — **재 둔 값 없음 · 어림**(맥 512 실측 MAC_512_PEAK_MIB 를 빌림). 재서 고칠 것.
GEN3D_NEED_MIB = 8_000


def memory_status() -> dict[str, Any]:
    """`{free_mib, commit_mib, commit_limit_mib, commit_share}` — 윈도우는 GlobalMemoryStatusEx, 그 밖은 남은 램만. 못 재면 None 칸."""
    out: dict[str, Any] = {"free_mib": None, "commit_mib": None, "commit_limit_mib": None, "commit_share": None}
    if os.name == "nt" and sys.platform != "darwin":
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
            from . import winapi

            if winapi.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                limit = int(status.ullTotalPageFile // 1048576)
                used = int((status.ullTotalPageFile - status.ullAvailPageFile) // 1048576)
                out.update(free_mib=int(status.ullAvailPhys // 1048576), commit_mib=used, commit_limit_mib=limit,
                           commit_share=round(used / limit, 3) if limit else None)
        except Exception:  # noqa: BLE001 — 못 재면 모른다
            pass
        return out
    try:
        out["free_mib"] = int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1048576)
    except Exception:  # noqa: BLE001
        pass
    return out


def unload_disabled() -> bool:
    # 환경을 바로 읽지 않는다 — 켤 때 `JARVIS_*` 는 보관소로 옮겨지고 환경에서 지워진다(`config.absorb_environment`).
    from .config import setting

    return setting("JARVIS_PACK_RAM_UNLOAD", "") == "0"


def should_unload(need_mib: int | None, status: dict[str, Any], *, disabled: bool = False) -> tuple[bool, str]:
    """(내릴까, 까닭). 넉넉하면 (False, ""). 못 재면 (False, "못 잼") — 막지도 내리지도 않는다."""
    free = status.get("free_mib")
    share = status.get("commit_share")
    reasons: list[str] = []
    if need_mib and free is not None and free < need_mib * NEED_FACTOR:
        reasons.append(f"남은 램 {free / 1024:.1f}GB · 이 일에 약 {need_mib * NEED_FACTOR / 1024:.1f}GB 필요")
    if share is not None and share > COMMIT_LIMIT_SHARE:
        reasons.append(f"PC 약속 메모리가 한도의 {share:.0%}(기준 {COMMIT_LIMIT_SHARE:.0%})")
    if not reasons:
        return False, "" if (free is not None or share is not None) else "램을 못 재서 그대로 굽는다"
    why = " · ".join(reasons)
    if disabled:
        return False, f"{why} — 사람이 언어 모델 내리기를 꺼 둬서 그대로 굽는다(몇 배 느릴 수 있다)"
    return True, why


# ── 「무거운 일 중」 깃발 ──────────────────────────────────────────────────
_lock = threading.Lock()
_busy = 0


@contextmanager
def heavy_work() -> Iterator[None]:
    """굽는 동안 감싼다 — 앞부분 데우기가 이 깃발을 보고 쉰다(겹쳐 감싸도 된다)."""
    global _busy
    with _lock:
        _busy += 1
    try:
        yield
    finally:
        with _lock:
            _busy = max(0, _busy - 1)


def heavy_busy() -> bool:
    with _lock:
        return _busy > 0


# ── 한 줄 대기열 (11-18 · 설계 `설계_블렌더공통층_워크플로우` §14-2) ─────────────────
# 3D 굽기 · 영상 굽기 · 블렌더 일(마무리 · 렌더 · 애니)을 프로세스 하나에서 한 줄로. 배타는 맥(통합 메모리 16GB)만 기본 —
# 윈도우 PC 는 카드 둘에서 영상과 3D 를 같이 굽는 것이 빠르다(`JARVIS_HEAVY_ONE_LINE=1` 이면 윈도우도 한 줄).
# 교착 막기: 3D 실행기 안 잠금(`_heavy`) → 이 잠금 순서 하나 · 기다리는 쪽은 굽기뿐 · 블렌더 일은 절대 안 기다린다(busy 로 거절).
_slot = threading.Lock()
_holders: list[str] = []


class HeavyBusy(RuntimeError):
    """한 줄 잠금을 다른 일이 쥐고 있어 기다리지 않는 일이 거절됐다."""

    def __init__(self, holders: list[str]) -> None:
        self.holders = list(holders)
        who = " · ".join(holders) or "다른 무거운 일"
        super().__init__(f"busy: 지금 {who} 이(가) 돈다 — 이 기기는 무거운 일(굽기 · 블렌더)을 한 줄로 돌린다(메모리). 끝난 뒤 다시 부른다")


_GPU_COUNT: int | None = None


def gpu_count() -> int:
    """엔비디아 카드 수(한 번만 잼 · nvidia-smi 가 없으면 0)."""
    global _GPU_COUNT
    if _GPU_COUNT is None:
        try:
            from .gen3d.memory import gpu_list

            _GPU_COUNT = len(gpu_list())
        except Exception:  # noqa: BLE001
            _GPU_COUNT = 0
    return _GPU_COUNT


def one_line() -> bool:
    """맥(통합 메모리) · 그래픽카드가 하나 이하인 PC 는 한 줄(11-19 적대적 검토: 손님 대부분은 3060 12GB 한 장 —
    영상 시안 약 6.4GB · 3D 굽기 최대 약 4.1GB 가 한 카드에서 겹친다). 카드 둘 이상이면 같이 굽는다. 설정이 이긴다."""
    from .config import setting

    raw = setting("JARVIS_HEAVY_ONE_LINE", "").strip()
    if raw in {"0", "1"}:
        return raw == "1"
    return sys.platform == "darwin" or gpu_count() <= 1


def heavy_holders() -> list[str]:
    with _lock:
        return list(_holders)


@contextmanager
def heavy_slot(who: str, *, wait: bool, exclusive: bool | None = None,
               on_wait: Any = None) -> Iterator[dict[str, Any]]:
    """한 줄 잠금. wait=False 면 잡혀 있을 때 바로 `HeavyBusy`. 넘겨주는 dict: `{busy_wait_sec, one_line}`(기다린 시간은 일한 시간과 따로 — 사고 S)."""
    excl = one_line() if exclusive is None else bool(exclusive)
    got = False
    started = time.monotonic()
    if excl:
        if _slot.acquire(blocking=False):
            got = True
        elif not wait:
            raise HeavyBusy(heavy_holders())
        else:
            if callable(on_wait):
                try:
                    on_wait(heavy_holders())
                except Exception:  # noqa: BLE001 — 알림은 덤
                    pass
            _slot.acquire()
            got = True
    info = {"busy_wait_sec": round(time.monotonic() - started, 1), "one_line": excl}
    with _lock:
        _holders.append(who)
    try:
        yield info
    finally:
        with _lock:
            if who in _holders:
                _holders.remove(who)
        if got:
            _slot.release()


# ── 내린 뒤 다시 데우기 ──────────────────────────────────────────────────
# 데우기 반복의 엔진 감시(`ollama.watch_front_engine`)는 모델이 「다시 올라온 것」만 보고 스스로 올리지는 않는다(11-17 코드 확인).
# 그래서 우리가 내렸으면 그 사실을 남겨 두고, 굽기가 끝난 뒤 데우기 반복이 한 번 데우게 한다(그 데우기가 모델을 올린다).
_reprime = False


def note_unloaded() -> None:
    global _reprime
    with _lock:
        _reprime = True


def take_reprime() -> bool:
    """내린 적이 있고 지금 굽는 일이 없으면 True 를 한 번 돌려주고 지운다."""
    global _reprime
    with _lock:
        if _reprime and _busy == 0:
            _reprime = False
            return True
        return False


# ── 무거운 실행기는 「보통」 순위로 ──────────────────────────────────────────
# 11-17 새벽 확정: 손자리 본체는 작업 스케줄러 기본값으로 떠 **CPU 보통 아래 · 메모리 순위 2 · 디스크 순위 1(낮음)** 이다.
# 영상 실행기(sd-cli)가 그걸 물려받아 모델 파일을 초당 약 28MB 로 한 쪽씩 읽었다 — 시안 한 판 400초.
# 같은 명령을 보통 순위 셸에서 부르면 32~36초(글 읽기 부품 읽기 192초 → 1.5초). 본체는 사람 일을 방해하지 않게 낮게 두고,
# 사람이 시킨 굽기 실행기만 보통으로 올린다.
_NORMAL_PRIORITY_CLASS = 0x20
_PROCESS_MEMORY_PRIORITY = 0      # PROCESS_INFORMATION_CLASS.ProcessMemoryPriority
_MEMORY_PRIORITY_NORMAL = 5
_PROCESS_POWER_THROTTLING = 4   # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
_PROCESS_IO_PRIORITY = 33         # NtSetInformationProcess ProcessIoPriority
_IO_PRIORITY_NORMAL = 2


def priority_of(pid: int) -> dict[str, Any]:
    """{cpu_class, memory, io} — 못 읽은 칸은 None. 영수증 · 시험이 「정말 올라갔나」를 본다."""
    out: dict[str, Any] = {"cpu_class": None, "memory": None, "io": None}
    if os.name != "nt":
        return out
    try:
        from . import winapi

        handle = winapi.kernel32.OpenProcess(0x0400 | 0x1000, False, int(pid))  # QUERY_INFORMATION | QUERY_LIMITED
        if not handle:
            return out
        try:
            out["cpu_class"] = int(winapi.kernel32.GetPriorityClass(handle)) or None
            mem = ctypes.c_ulong(0)
            if winapi.kernel32.GetProcessInformation(handle, _PROCESS_MEMORY_PRIORITY, ctypes.byref(mem), 4):
                out["memory"] = int(mem.value)
            io = ctypes.c_ulong(0)
            if winapi.ntdll.NtQueryInformationProcess(handle, _PROCESS_IO_PRIORITY, ctypes.byref(io), 4, None) == 0:
                out["io"] = int(io.value)
        finally:
            winapi.kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass
    return out


def lift_to_normal(process: Any) -> dict[str, Any] | None:
    """방금 띄운 실행기를 CPU · 메모리 · 디스크 모두 「보통」으로. 진짜 `subprocess.Popen` 에만(시험의 가짜 과정은 건드리지 않는다).

    돌려주는 값: 올린 뒤 순위(`priority_of`) · 윈도우가 아니거나 가짜면 None. 실패해도 굽기는 그대로 간다.
    """
    import subprocess

    if os.name != "nt" or not isinstance(process, subprocess.Popen):
        return None
    try:
        from . import winapi

        handle = winapi.kernel32.OpenProcess(0x0200 | 0x0400, False, int(process.pid))  # SET_INFORMATION | QUERY_INFORMATION
        if handle:
            try:
                winapi.kernel32.SetPriorityClass(handle, _NORMAL_PRIORITY_CLASS)
                mem = ctypes.c_ulong(_MEMORY_PRIORITY_NORMAL)
                winapi.kernel32.SetProcessInformation(handle, _PROCESS_MEMORY_PRIORITY, ctypes.byref(mem), 4)
                io = ctypes.c_ulong(_IO_PRIORITY_NORMAL)
                winapi.ntdll.NtSetInformationProcess(handle, _PROCESS_IO_PRIORITY, ctypes.byref(io), 4)
                # 효율 모드(전력 조절) 끄기 — 창 없이 낮은 순위로 도는 본체의 자식은 윈도우가 알아서 느리게 돌릴 수 있다(11-18 렌더 의심).
                # PROCESS_POWER_THROTTLING_STATE{Version 1, ControlMask=EXECUTION_SPEED, StateMask=0} = 「이 프로세스는 조절하지 마라」.
                # JARVIS_POWER_THROTTLE_FIX=0 이면 건너뛴다 — 되돌려 보기 실험(11-19 적대적 검토: 원인 판정이 n=2 · 앞뒤 사이 재시작)용.
                from .config import setting

                if setting("JARVIS_POWER_THROTTLE_FIX", "1") != "0":
                    throttle = (ctypes.c_ulong * 3)(1, 0x1, 0)
                    winapi.kernel32.SetProcessInformation(handle, _PROCESS_POWER_THROTTLING, ctypes.byref(throttle), ctypes.sizeof(throttle))
            finally:
                winapi.kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass
    return priority_of(process.pid)


def unload_note(names: list[str], why: str) -> str:
    """영수증 not_done 한 줄."""
    return (f"램이 모자라 굽기 전에 언어 모델을 잠시 내렸다({', '.join(names)} · {why}) — 끝나면 저절로 다시 올라온다. "
            "다음 큰 대화 한 번은 앞부분을 다시 읽어 1분쯤 느릴 수 있다")


__all__ = ["COMMIT_LIMIT_SHARE", "GEN3D_NEED_MIB", "NEED_FACTOR", "VIDEO_NEED_MIB", "heavy_busy", "heavy_work",
           "lift_to_normal", "memory_status", "note_unloaded", "priority_of", "should_unload", "take_reprime", "unload_disabled", "unload_note"]
