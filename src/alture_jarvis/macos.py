"""맥(macOS) 전용 작은 함수들 (2026-11-03 맥판 · 설계 `docs/설계_맥판_1103.md` D1).

윈도우 쪽은 이미 있는 `os.name` / `sys.platform` 가드 옆에 그대로 두고, 맥 갈래에서 부를 것만 여기 모은다.
여기 함수는 **실패해도 예외를 던지지 않는다** — 맥 OS 층이 실패했다고 일을 멈추지 않는다(설계 §5).
윈도우에서 import 해도 아무 일도 안 한다(맨 위에 맥 전용 import 없음).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

Runner = Callable[..., "subprocess.CompletedProcess[str]"]

#: 클로드 데스크톱 앱(일렉트론)의 본 실행 파일 끝. **대소문자를 가린다** — 클로드 코드 CLI 는
#: `…/claude-code/<판>/<해시>/claude.app/Contents/MacOS/claude`(소문자)라 소문자로 비교하면 둘이 섞인다.
DESKTOP_EXE_TAIL = "/Claude.app/Contents/MacOS/Claude"


def is_mac() -> bool:
    return sys.platform == "darwin"


def processes(run: Runner | None = None) -> list[tuple[int, str]]:
    """(PID, 실행 파일 전체 경로) 목록. `ps -axo pid=,comm=` — 맥 `comm` 은 전체 경로를 준다(맥미니 확인).

    경로에 빈칸이 있으므로(`/Applications/Google Chrome.app/…`) 첫 빈칸에서만 자른다.
    """
    runner = run or subprocess.run
    try:
        done = runner(["ps", "-axo", "pid=,comm="], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001 — ps 가 없거나 막혀도 「모름」으로
        return []
    rows: list[tuple[int, str]] = []
    for line in str(getattr(done, "stdout", "") or "").splitlines():
        pid, _, exe = line.strip().partition(" ")
        if pid.isdigit() and exe.strip():
            rows.append((int(pid), exe.strip()))
    return rows


def process_commands(run: Runner | None = None) -> list[tuple[int, int, str]]:
    """(PID, 부모 PID, 명령 줄 전체) — 크롬처럼 인자(`--user-data-dir`)로 가려야 할 때."""
    runner = run or subprocess.run
    try:
        done = runner(["ps", "-axww", "-o", "pid=,ppid=,command="], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return []
    rows: list[tuple[int, int, str]] = []
    for line in str(getattr(done, "stdout", "") or "").splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def app_bundle_of(exe: str) -> str:
    """`/Applications/Claude.app/Contents/MacOS/Claude` → `/Applications/Claude.app`. 번들 밖이면 빈 값."""
    head, sep, _ = str(exe or "").partition("/Contents/MacOS/")
    return head if sep and head.endswith(".app") else ""


def claude_cli_candidates(home: Path) -> list[Path]:
    """맥에서 클로드 코드 CLI 가 있을 만한 자리. 데스크톱 앱이 들고 있는 것은 판이 여럿이면 새것부터."""
    direct = [home / ".local" / "bin" / "claude", Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")]
    bundled = sorted(
        (home / "Library" / "Application Support" / "Claude" / "claude-code").glob("*/*/claude.app/Contents/MacOS/claude"),
        key=lambda path: _version_key(path),
        reverse=True,
    )
    return [path for path in [*direct, *bundled] if path.is_file()]


def _version_key(path: Path) -> tuple[int, ...]:
    for part in path.parts:
        numbers = part.split(".")
        if len(numbers) >= 2 and all(number.isdigit() for number in numbers):
            return tuple(int(number) for number in numbers)
    return (0,)


# ── 앱 숨기기 · 앞 앱 · 화면 위 창 (ctypes 로 objc 런타임을 직접 부른다 — PyObjC 설치 없이) ──────────────
#
# ★ 설계 D3: 손자리가 띄운 크롬 **그 PID 만** 숨긴다. `NSRunningApplication.hide` 는 허락 창이 없었다(맥미니 · 11-03).
#   System Events AppleScript 는 「자동화」 허락 창을 띄우므로 쓰지 않는다. 창 목록(`CGWindowListCopyWindowInfo`)은
#   창 **이름**만 화면 기록 허락이 필요하고, 주인 PID · 화면 위 여부 · 크기는 허락 없이 나온다.

_OBJC: object | None = None


def _objc():  # noqa: ANN202 — ctypes 핸들 묶음
    global _OBJC
    if _OBJC is not None:
        return _OBJC or None
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
        ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
        cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        _OBJC = (ctypes, objc, cg, cf)
    except Exception:  # noqa: BLE001 — 맥이 아니거나 라이브러리가 없으면 「모름」
        _OBJC = False
        return None
    return _OBJC


_PROTOS: dict[tuple, object] = {}


def _fn(lib, name: str, restype, *argtypes):  # noqa: ANN001, ANN202
    """라이브러리 함수를 **그 모양 전용 원형**으로 — 공용 함수 객체의 restype/argtypes 를 바꾸지 않는다.

    ★ 11-04 (test_winapi_1103 · 윈도우 0xc0000005 사고와 같은 병): 예전엔 부를 때마다 cf.CFArrayGetCount 의 restype 을 새로 적는 식으로
      공용 객체를 고쳤다. 숨김 감시 스레드와 다른 스레드가 같은 함수를 다른 모양으로 동시에 고치면 엇갈려 죽을 수 있다.
      모양마다 한 번 만든 원형을 쥐고 쓴다(`_send` 와 같은 방식).
    """
    import ctypes

    key = (id(lib), name, restype, argtypes)
    proto = _PROTOS.get(key)
    if proto is None:
        proto = ctypes.CFUNCTYPE(restype, *argtypes)((name, lib))
        _PROTOS[key] = proto
    return proto


def _cls(name: bytes):  # noqa: ANN202
    bundle = _objc()
    if not bundle:
        return None
    ctypes, objc, _, _ = bundle
    return _fn(objc, "objc_getClass", ctypes.c_void_p, ctypes.c_char_p)(name)


class autorelease_pool:  # noqa: N801 — with 문으로 쓰는 작은 도구
    """objc 가 돌려준 자동 해제 객체를 이 블록이 끝날 때 비운다(`objc_autoreleasePoolPush/Pop`).

    ★ 11-03 코드 검토: 숨김 감시는 실행 루프 없는 스레드에서 0.1~0.5초마다 objc 를 부른다 — 풀이 없으면 받은 객체가
      영영 안 풀려 백엔드 메모리가 시간 따라 늘었을 것이다. 맥이 아니면 아무것도 안 한다.
    """

    def __enter__(self) -> "autorelease_pool":
        bundle = _objc()
        self._token = None
        if bundle:
            ctypes, objc, _, _ = bundle
            self._token = _fn(objc, "objc_autoreleasePoolPush", ctypes.c_void_p)()
        return self

    def __exit__(self, *_exc: object) -> None:
        bundle = _objc()
        if bundle and self._token:
            ctypes, objc, _, _ = bundle
            _fn(objc, "objc_autoreleasePoolPop", None, ctypes.c_void_p)(self._token)


def _send(restype, receiver, selector: str, *args):  # noqa: ANN001, ANN202
    bundle = _objc()
    if not bundle or not receiver:
        return None
    ctypes, objc, _, _ = bundle
    argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(arg) if isinstance(arg, ctypes._SimpleCData) else ctypes.c_void_p
                                                     for arg in args]
    fn = ctypes.CFUNCTYPE(restype, *argtypes)(("objc_msgSend", objc))
    return fn(receiver, _fn(objc, "sel_registerName", ctypes.c_void_p, ctypes.c_char_p)(selector.encode()), *args)


def _running_app(pid: int):  # noqa: ANN202
    bundle = _objc()
    if not bundle:
        return None
    ctypes, objc, _, _ = bundle
    cls = _cls(b"NSRunningApplication")
    return _send(ctypes.c_void_p, cls, "runningApplicationWithProcessIdentifier:", ctypes.c_int(int(pid)))


def hide_app(pid: int) -> bool:
    """그 PID 의 앱을 숨긴다(⌘H 와 같다). 성공이면 True. 다른 앱은 건드리지 않는다."""
    bundle = _objc()
    if not bundle or not pid:
        return False
    ctypes = bundle[0]
    app = _running_app(pid)
    if not app:
        return False
    return bool(_send(ctypes.c_bool, app, "hide"))


def unhide_app(pid: int) -> bool:
    bundle = _objc()
    if not bundle or not pid:
        return False
    app = _running_app(pid)
    return bool(app and _send(bundle[0].c_bool, app, "unhide"))


def app_is_hidden(pid: int) -> bool | None:
    bundle = _objc()
    if not bundle or not pid:
        return None
    app = _running_app(pid)
    if not app:
        return None
    return bool(_send(bundle[0].c_bool, app, "isHidden"))


def frontmost_pid() -> int | None:
    """지금 앞에 있는(키보드를 받는) 앱의 PID — **운영체제에 직접** 묻는다(`lsappinfo`).

    ★ 2026-11-03 맥미니 실측: `NSWorkspace.frontmostApplication` 은 메인 실행 루프가 없는 프로세스(손자리 백엔드 ·
      측정기)에서 **낡은 값**을 준다 — 숨긴 크롬이 앞 앱인데도 처음 본 앱(대표 크롬)을 계속 답했다. 이 눈금을 믿고
      「앞 앱을 안 뺏는다(0ms)」고 적었다가 바로잡았다. `lsappinfo` 는 부를 때마다 LaunchServices 에 묻는다.
    """
    try:
        asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=3,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        if asn:
            out = subprocess.run(["lsappinfo", "info", "-only", "pid", asn],
                                 capture_output=True, text=True, timeout=3,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            tail = out.rsplit("=", 1)[-1].strip()
            if tail.isdigit():
                return int(tail)
    except Exception:  # noqa: BLE001 — lsappinfo 가 없으면 아래(낡을 수 있는 값)로
        pass
    bundle = _objc()
    if not bundle:
        return None
    ctypes, objc, _, _ = bundle
    workspace = _send(ctypes.c_void_p, _cls(b"NSWorkspace"), "sharedWorkspace")
    app = _send(ctypes.c_void_p, workspace, "frontmostApplication")
    if not app:
        return None
    return int(_send(ctypes.c_int, app, "processIdentifier"))


_CF_KEYS: dict[str, int] = {}


def onscreen_window_count(pids: set[int]) -> int | None:
    """그 PID 들이 가진 **화면에 그려진** 보통 창(층 0) 수. 허락 없이 된다(창 이름은 안 읽는다)."""
    bundle = _objc()
    if not bundle or not pids:
        return None
    ctypes, _, cg, cf = bundle
    vp = ctypes.c_void_p
    window_list = _fn(cg, "CGWindowListCopyWindowInfo", vp, ctypes.c_uint32, ctypes.c_uint32)
    array_count = _fn(cf, "CFArrayGetCount", ctypes.c_long, vp)
    array_at = _fn(cf, "CFArrayGetValueAtIndex", vp, vp, ctypes.c_long)
    dict_get = _fn(cf, "CFDictionaryGetValue", vp, vp, vp)
    number_get = _fn(cf, "CFNumberGetValue", ctypes.c_bool, vp, ctypes.c_int, vp)
    make_string = _fn(cf, "CFStringCreateWithCString", vp, vp, ctypes.c_char_p, ctypes.c_uint32)
    release = _fn(cf, "CFRelease", None, vp)

    keys = _CF_KEYS
    if not keys:
        for name in ("kCGWindowOwnerPID", "kCGWindowLayer"):
            keys[name] = make_string(None, name.encode(), 0x08000100)  # 한 번 만들어 계속 쓴다(풀지 않음 · 둘뿐)

    def key(name: str):  # noqa: ANN202
        return keys[name]

    def number(dictionary, name):  # noqa: ANN001, ANN202
        value = dict_get(dictionary, key(name))
        out = ctypes.c_int64(0)
        return int(out.value) if value and number_get(value, 4, ctypes.byref(out)) else None

    # kCGWindowListOptionOnScreenOnly(1) | kCGWindowListExcludeDesktopElements(16)
    windows = window_list(1 | 16, 0)
    if not windows:
        return None
    try:
        count = 0
        for index in range(array_count(windows)):
            item = array_at(windows, index)
            if number(item, "kCGWindowOwnerPID") in pids and number(item, "kCGWindowLayer") == 0:
                count += 1
        return count
    finally:
        release(windows)


_RECT: type | None = None


def main_screen_bounds() -> tuple[int, int, int, int] | None:
    """주 화면의 (왼쪽, 위, 너비, 높이) — 왼쪽 위가 원점(크롬 창 좌표와 같은 기준). 허락 없이 된다. 못 읽으면 None."""
    bundle = _objc()
    if not bundle:
        return None
    ctypes, _, cg, _ = bundle
    global _RECT
    if _RECT is None:  # 형은 한 번만 — 부를 때마다 새 형이면 `_fn` 원형 캐시가 끝없이 는다
        _RECT = type("CGRect", (ctypes.Structure,), {"_fields_": [
            ("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]})
    try:
        display = _fn(cg, "CGMainDisplayID", ctypes.c_uint32)()
        rect = _fn(cg, "CGDisplayBounds", _RECT, ctypes.c_uint32)(display)
    except Exception:  # noqa: BLE001
        return None
    if rect.w <= 0 or rect.h <= 0:
        return None
    return int(rect.x), int(rect.y), int(rect.w), int(rect.h)


def activate_app(pid: int) -> bool:
    """그 PID 의 앱을 앞으로(사람이 「크롬 창 보기」를 직접 눌렀을 때만 부른다)."""
    bundle = _objc()
    if not bundle or not pid:
        return False
    app = _running_app(pid)
    # NSApplicationActivateIgnoringOtherApps = 1 << 1
    return bool(app and _send(bundle[0].c_bool, app, "activateWithOptions:", bundle[0].c_ulong(2)))


def idle_seconds() -> float | None:
    """마지막 키 · 마우스 입력 뒤 지난 초(`CGEventSourceSecondsSinceLastEventType`). 허락 없이 된다. 못 재면 None."""
    bundle = _objc()
    if not bundle:
        return None
    ctypes, _, cg, _ = bundle
    try:
        fn = _fn(cg, "CGEventSourceSecondsSinceLastEventType", ctypes.c_double, ctypes.c_int, ctypes.c_uint32)
        # kCGEventSourceStateCombinedSessionState = 0 · kCGAnyInputEventType = 0xFFFFFFFF
        return float(fn(0, 0xFFFFFFFF))
    except Exception:  # noqa: BLE001
        return None


# ── 애플 통합 메모리 (2026-11-03 · 대표 지시 「메모리 예산으로 센다 · 16GB 에 묶지 않는다」) ──────────────────

def sysctl(name: str) -> str:
    """`sysctl -n <name>` 값(못 읽으면 빈 값)."""
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def metal_gpu_limit_gb() -> float | None:
    """GPU 에 내줄 수 있는 상한 — Metal 의 `recommendedMaxWorkingSetSize`(GB). 맥미니 M4 16GB 에서 10.67(11-03 잼).

    `iogpu.wired_limit_mb` 를 사람이 올려 두었으면 그 값이 이 상한에 반영된다(0 이면 맥 기본값). 못 읽으면 None.
    """
    bundle = _objc()
    if not bundle:
        return None
    ctypes, objc, _, _ = bundle
    try:
        metal = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Metal.framework/Metal")
        with autorelease_pool():
            device = _fn(metal, "MTLCreateSystemDefaultDevice", ctypes.c_void_p)()
            if not device:
                return None
            size = _send(ctypes.c_uint64, device, "recommendedMaxWorkingSetSize")
        return round(int(size) / 2**30, 2) if size else None
    except Exception:  # noqa: BLE001
        return None


def memory_free_percent() -> float | None:
    """맥이 말하는 「지금 비어 있다고 볼 수 있는 메모리」 비율(`memory_pressure -Q`). 못 읽으면 None."""
    try:
        out = subprocess.run(["memory_pressure", "-Q"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:  # noqa: BLE001
        return None
    for line in out.splitlines():
        if "free percentage" in line:
            try:
                return float(line.rsplit(":", 1)[-1].strip().rstrip("%"))
            except ValueError:
                return None
    return None


def swap_used_gb() -> float | None:
    """쓰고 있는 스왑(GB) — `vm.swapusage`. 크면 이미 메모리가 모자란 맥이다."""
    raw = sysctl("vm.swapusage")
    import re as _re

    match = _re.search(r"used = ([\d.]+)M", raw)
    return round(float(match.group(1)) / 1024, 2) if match else None


def footprint_gb(pids: list[int]) -> float:
    """프로세스들의 실제 메모리 사용량 합(`footprint` · GB). Metal 버퍼처럼 RSS 에 안 잡히는 것도 들어간다."""
    if not pids:
        return 0.0
    try:
        out = subprocess.run(["footprint", *map(str, pids)], capture_output=True, text=True, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:  # noqa: BLE001
        return 0.0
    import re as _re

    # ★ 여러 프로세스를 넘기면 끝에 「Summary Footprint」 한 줄이 더 있다(공유 메모리를 한 번만 센 합). 그 줄이 있으면 그것만,
    #   없으면(프로세스 하나) 그 줄 하나 — 둘 다 더하면 두 배가 된다(11-03 맥미니: 손자리 몫을 2.65GB 로 부풀려 잼 · 바로잡음).
    units = {"KB": 1 / 1024, "MB": 1.0, "GB": 1024.0}
    summary = _re.search(r"Summary Footprint:\s*([\d.]+)\s*(KB|MB|GB)", out)
    if summary:
        return round(float(summary.group(1)) * units[summary.group(2)] / 1024, 2)
    total_mb = sum(float(size) * units[unit] for size, unit in _re.findall(r"\]:.*?Footprint:\s*([\d.]+)\s*(KB|MB|GB)", out))
    return round(total_mb / 1024, 2)


def ollama_pids(run: Runner | None = None) -> list[int]:
    """이 맥의 Ollama 프로세스(앱 · 서버 · 모델 러너). 모델이 **올라가는 중**인 메모리도 여기 잡힌다."""
    rows = process_commands(run)
    return [pid for pid, _ppid, command in rows
            if "/Ollama.app/" in command or command.split(" ", 1)[0].endswith("/ollama")]
