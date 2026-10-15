"""이 프로세스가 무엇을 쥐고 있는지 센다 — 새는 것을 짐작하지 않고 보려고 (2026-10-14).

그날 밤 세 대의 PC 에서 같은 과제를 되풀이 돌렸더니 뒤쪽 프로세스가 계속 불어났다: 8GB 노트북에서 12시간 뒤
18GB · 손잡이 70,323개, 이 PC 에서 5시간 뒤 3.6GB · 손잡이 120,380개(그중 119,664개가 이름 없는 세마포어 —
윈도우의 파이썬 3.11 은 잠금 하나가 세마포어 하나를 쥔다). 6GB 노트북은 일반 메모리가 0.9GB 까지 내려가 판이
걸음 0 으로 시간만 채웠다. 밖에서는 「잠금을 가진 무언가가 쌓인다」까지만 보였다.

여기서는 안에서 센다: 손잡이 · 메모리 · 스레드, 그리고 살아 있는 물건을 종류별로. `who` 를 주면 그 종류의 물건을
누가 붙들고 있는지 몇 걸음 따라 올라간다. 읽기만 한다 — 아무것도 지우거나 바꾸지 않는다.
"""

from __future__ import annotations

import ctypes
import gc
import sys
import threading
import types
from collections import Counter
from typing import Any


def _kind(thing: Any) -> str:
    kind = type(thing)
    return f"{kind.__module__}.{kind.__qualname__}"


def _process_numbers() -> dict[str, Any]:
    """손잡이 수와 메모리(윈도우). 다른 OS 에서는 모르는 값을 비워 둔다 — 지어내지 않는다."""
    numbers: dict[str, Any] = {"threads": threading.active_count()}
    if sys.platform != "win32":
        return numbers
    try:
        from ctypes import wintypes

        class _Memory(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        me = kernel.GetCurrentProcess()
        count = wintypes.DWORD(0)
        kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        if kernel.GetProcessHandleCount(me, ctypes.byref(count)):
            numbers["handles"] = int(count.value)
        memory = _Memory()
        memory.cb = ctypes.sizeof(_Memory)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(me, ctypes.byref(memory), memory.cb):
            numbers["private_mb"] = round(memory.PrivateUsage / 1_048_576, 1)
            numbers["working_mb"] = round(memory.WorkingSetSize / 1_048_576, 1)
    except Exception as error:  # noqa: BLE001 — 세지 못한 것은 못 셌다고 적는다
        numbers["error"] = f"{type(error).__name__}: {error}"[:160]
    return numbers


def _holders(target: Any, depth: int, skip: set[int]) -> list[str]:
    """`target` 을 붙든 것을 `depth` 걸음 따라 올라가며 종류만 적는다. 갈래가 여럿이면 가장 큰 통을 따라간다."""
    trail: list[str] = []
    current = target
    for _ in range(depth):
        # 이 함수 자신이 잠깐 쥔 것(프레임 · 닫힌 변수 칸)은 붙든 것으로 치지 않는다.
        holders = [item for item in gc.get_referrers(current)
                   if id(item) not in skip and not isinstance(item, (types.FrameType, types.CellType, types.GeneratorType))]
        skip.add(id(holders))
        if not holders:
            break
        # 인스턴스의 `__dict__` 는 그 주인으로 바꿔 읽는다 — 「dict」만으로는 아무것도 못 알아본다.
        chosen = max(holders, key=lambda item: len(item) if isinstance(item, (dict, list, set, tuple)) else 0)
        label = _kind(chosen)
        if isinstance(chosen, dict):
            owner = next((item for item in gc.get_referrers(chosen)
                          if id(item) not in skip and getattr(item, "__dict__", None) is chosen), None)
            keys = [str(key)[:28] for key in list(chosen)[:4]]
            if owner is not None:
                label = f"{_kind(owner)}.__dict__"
                key = next((str(name) for name, value in chosen.items() if value is current), "")
                label += f"[{key}]" if key else ""
                chosen = owner
            else:
                label += f"(len {len(chosen)} · keys {keys})"
        elif isinstance(chosen, (list, set, tuple)):
            label += f"(len {len(chosen)})"
        trail.append(label)
        skip.add(id(current))
        current = chosen
    return trail


def _anchor(thing: Any) -> bool:
    """뿌리로 볼 만한 것 — 우리 코드의 물건 · 모듈 · 스레드 · 실행 중인 프레임. 남의 라이브러리 안쪽 고리는 뿌리가 아니다."""
    kind = type(thing)
    module = str(getattr(kind, "__module__", "") or "")
    if module.startswith("alture_jarvis") or isinstance(thing, (types.ModuleType, threading.Thread)):
        return True
    return module.startswith("greenlet") or module.startswith("asyncio")


def roots_of(target: Any, limit: int = 40_000, wanted: int = 5, skip: set[int] | None = None) -> list[list[str]]:
    """`target` 을 거슬러 올라가 뿌리(`_anchor`)까지 닿는 길을 몇 개 찾는다 — 순환 고리 안에서 맴도는 대신 넓게 훑는다."""
    skip = set(skip or ())
    parents: dict[int, tuple[int, Any]] = {id(target): (0, target)}
    queue = [target]
    found: list[list[str]] = []
    skip.update({id(parents), id(queue), id(found)})
    while queue and len(parents) < limit and len(found) < wanted:
        current = queue.pop(0)
        for holder in gc.get_referrers(current):
            if id(holder) in parents or id(holder) in skip:
                continue
            if isinstance(holder, (types.FrameType, types.CellType, types.GeneratorType)) and holder is not None:
                if isinstance(holder, types.FrameType) and holder.f_code.co_filename.endswith("process_census.py"):
                    continue
            parents[id(holder)] = (id(current), holder)
            if _anchor(holder) and not isinstance(holder, types.ModuleType) or isinstance(holder, types.FrameType):
                path, node = [], id(holder)
                while node and node in parents and node != id(target):
                    parent_id, obj = parents[node]
                    label = _kind(obj)
                    if isinstance(obj, dict):
                        label += f"(len {len(obj)})"
                    elif isinstance(obj, types.FrameType):
                        label = f"frame {obj.f_code.co_name} ({obj.f_code.co_filename.rsplit(chr(92), 1)[-1]}:{obj.f_lineno})"
                    path.append(label)
                    node = parent_id
                found.append(list(reversed(path)))
                if len(found) >= wanted:
                    break
                continue
            queue.append(holder)
    return found


def stale_holders(owner: Any, current: Any, kind: str = "playwright._impl._connection.Connection",
                  depth: int = 6, limit: int = 20_000) -> dict[str, Any]:
    """`owner` 의 칸마다 아래로 따라가, `current` 가 아닌 `kind` 물건(옛 연결)에 닿는 칸을 적는다.

    거꾸로(누가 쥐었나) 훑으면 물건 60만 개에서 너무 느리다 — 의심 가는 주인에서 아래로 내려가는 쪽이 싸다.
    """
    stale = [thing for thing in gc.get_objects() if _kind(thing) == kind and thing is not current]
    targets = {id(thing) for thing in stale}
    reached: dict[str, int] = {}
    for name, value in list(vars(owner).items()):
        seen: set[int] = {id(owner)}
        frontier = [(value, 0)]
        hit = 0
        while frontier and len(seen) < limit:
            node, level = frontier.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            if id(node) in targets:
                hit += 1
                continue
            if level >= depth or isinstance(node, (type, types.ModuleType)):
                continue
            frontier.extend((child, level + 1) for child in gc.get_referents(node))
        if hit:
            reached[name] = hit
    return {"stale": len(stale), "reached_from": reached}


def census(top: int = 40, who: str = "", samples: int = 3, depth: int = 6, roots: bool = False) -> dict[str, Any]:
    """살아 있는 물건을 종류별로 세고, `who` 가 있으면 그 종류를 누가 붙들고 있는지 본다."""
    gc.collect()
    things = gc.get_objects()
    counts = Counter(_kind(thing) for thing in things)
    out: dict[str, Any] = {
        "process": _process_numbers(),
        "tracked_objects": len(things),
        "gc_counts": list(gc.get_count()),
        "top": [{"type": name, "count": number} for name, number in counts.most_common(max(1, min(int(top), 400)))],
    }
    if who:
        matches = [thing for thing in things if _kind(thing) == who]
        skip = {id(things), id(matches)}
        picked = matches[:: max(1, len(matches) // max(1, samples))][:samples]
        skip.add(id(picked))
        out["who"] = {"type": who, "count": len(matches),
                      "held_by": [_holders(thing, max(1, min(int(depth), 12)), set(skip)) for thing in picked]}
        if roots:
            out["who"]["roots"] = [roots_of(thing, skip=set(skip) | {id(picked)}) for thing in picked]
    return out
