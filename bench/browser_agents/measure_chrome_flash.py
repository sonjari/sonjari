"""크롬이 **뜰 때 화면에 번쩍 보이는가** — 앞창(포커스)이 아니라 눈에 보이는 것을 잰다 (2026-09-18 밤).

사용자 보고: 「온텔릭이 크롬을 띄울 때 한순간 팍 떴다가 바로 스르륵 들어간다. 사용자가 놀란다.」

`measure_chrome_foreground.py` 는 **앞창을 뺏는 시간**만 잰다. 그런데 앞창을 안 뺏어도 창이 화면에
그려졌다가 최소화 애니메이션으로 사라지면 사람 눈에는 똑같이 번쩍이다. 그래서 20ms 마다 셋을 본다.

    on_screen_ms   우리 크롬 창이 최소화가 아니고, 크기가 있고, 어느 모니터와 겹친 채 보인 시간  ← 「팍」
    front_ms       우리 크롬이 앞창이던 시간                                                ← 치던 글자를 뺏김
    sank_after_seen 화면에 보였다가 최소화로 사라진 횟수                                     ← 「스르륵」

**다 뜬 뒤**(감시가 창을 맨 뒤로 되살린 뒤)에 보이는 것은 의도한 상태다 — 사람이 작업 표시줄에서 볼 수
있어야 한다. 그래서 되살린 시각(`restored_at`) **전까지만** 센다.

    SRC=E:/.../src  ATTACH_MODE=auto  python measure_chrome_flash.py
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.environ.get("SRC", r"C:\RoboMetaFit\tools\alture-jarvis\src"))
sys.stdout.reconfigure(encoding="utf-8")

from alture_jarvis.browser import BrowserWorker  # noqa: E402
from alture_jarvis.config import JarvisConfig  # noqa: E402
from alture_jarvis.user_presence import UserPresence  # noqa: E402

user32 = ctypes.windll.user32
# ★ 5ms 다 (2026-09-21). 번쩍임이 **20ms** 였는데 표집 주기도 20ms 라 절반은 놓쳤다 —
#   보는 주기가 사건보다 굵으면 그 사건은 우리에게 존재하지 않는다.
TICK = float(os.environ.get("TICK_MS", "5")) / 1000

_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "SysShadow"}


def _title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def _cloaked(hwnd: int) -> bool:
    """UWP 의 잠든 창은 보이는 것처럼 z 순서에 남는다 — DWM 이 가린 창은 사람 눈에 없다."""
    value = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(value), 4)  # DWMWA_CLOAKED
    except Exception:  # noqa: BLE001
        return False
    return bool(value.value)


def _layered_alpha(hwnd: int) -> int:
    """레이어드가 아니면 255(불투명). 레이어드면 실제 알파.

    ★ 알파 0 인 창은 z 순서상 위에 서도 **사람 눈에 안 보인다** — 화면 픽셀로 확인했다(2026-09-21,
      크롬을 맨 위에 올린 채 ① 불투명 (238,238,238) ② 알파 0 → 뒤의 색 ③ 복구 → 다시 크롬).
      그래서 「보이는 번쩍임」은 알파가 0 보다 큰 창만 센다. z 순서만 센 값은 따로 남긴다.
    """
    if not (user32.GetWindowLongW(hwnd, -20) & 0x80000):  # WS_EX_LAYERED
        return 255
    key, alpha, flags = wt.DWORD(0), ctypes.c_ubyte(0), wt.DWORD(0)
    if not user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags)):
        return 255
    return int(alpha.value) if flags.value & 0x2 else 255  # LWA_ALPHA


def _is_app_window(hwnd: int) -> bool:
    """사람이 「창」으로 보는 것 — 보이고, 최소화 아니고, 제목이 있고, 셸 바탕이 아닌 것."""
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or _cloaked(hwnd):
        return False
    if user32.GetWindowLongW(hwnd, -20) & 0x80:  # WS_EX_TOOLWINDOW
        return False
    cls = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, cls, 128)
    if cls.value in _SHELL_CLASSES:
        return False
    return bool(_title(hwnd)) and _on_a_monitor(hwnd)


def _image_name(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(260)
        buf = ctypes.create_unicode_buffer(260)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


_INDEPENDENT_CACHE: dict[int, bool] = {}


def _independent_windows(preexisting_pids: set[int]) -> list[int]:
    """워커의 캐시·판정과 **무관하게** 크롬 주 창을 찾는다 — 프로세스 이름(chrome.exe)과 「측정 전에 없던 pid」만 본다.

    ★ 워커의 `_our_chrome_windows()` 로 재면 워커가 못 알아보는 순간(새 pid 캐시 · 1초)을 눈금도 못 본다 — 같은 코드의 눈으로
      재면 같은 곳에서 못 본다. 실험실 0/8 이 운영을 못 덮은 이유의 절반이다(운영을 밖에서 관찰해서 알았다).
      그래서 **창이 태어나는 순간(birth)** 도 이 눈금이 잡는다.
    """
    found: list[int] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def visit(hwnd, _param):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != "Chrome_WidgetWin_1":
            return True
        if (user32.GetWindowLongW(hwnd, -16) & 0xC00000) != 0xC00000:  # WS_CAPTION — 주 창만
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        number = int(pid.value)
        if number in preexisting_pids:
            return True
        ok = _INDEPENDENT_CACHE.get(number)
        if ok is None:
            ok = _image_name(number) == "chrome.exe"
            _INDEPENDENT_CACHE[number] = ok
        if ok:
            found.append(int(hwnd))
        return True

    user32.EnumWindows(proto(visit), 0)
    return found


def _chrome_pids_now() -> set[int]:
    import subprocess

    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Process chrome -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }"],
        capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {int(x) for x in done.stdout.split() if x.strip().isdigit()}


def _spawn_scapegoat() -> tuple[object, int]:
    """주 모니터에 최대화된 더미 창을 띄워 **앞창**으로 둔다.

    ★ 처음 눈금은 「지금 앞창」과 겹칠 때만 번쩍임으로 셌다. 앞창이 **보조 모니터**에 있으면
      (`keep_rect` 가 음수 좌표) 우리 크롬이 주 모니터에서 번쩍여도 겹치지 않아 0 이 나온다 —
      사람이 본 것을 못 보는 눈금이다. 더미 창을 우리가 정하면 배치와 상관없이 재현된다.
    """
    import subprocess

    code = ("import tkinter as tk\nr=tk.Tk()\nr.title('FLASH-SCAPEGOAT')\n"
            "r.state('zoomed')\nr.configure(bg='#223')\nr.mainloop()\n")
    proc = subprocess.Popen([sys.executable, "-c", code])
    hwnd = 0
    # ★ Tk 는 최상위 창을 **둘** 만든다 — 최소화된 껍데기와 진짜 창. `FindWindowW` 는 껍데기를
    #   먼저 돌려줘서, 처음엔 눈금이 최소화된 창을 앞창으로 알고 있었다(실측: rect -32000).
    #   보이고·최소화 아닌 쪽을 골라야 한다.
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    for _ in range(100):
        found: list[int] = []

        def _enum(h, _lparam):  # noqa: ANN001
            if _title(h) == "FLASH-SCAPEGOAT" and user32.IsWindowVisible(h) and not user32.IsIconic(h):
                found.append(int(h))
            return True

        user32.EnumWindows(proto(_enum), 0)
        if found:
            hwnd = found[0]
            break
        time.sleep(0.1)
    if hwnd:
        user32.keybd_event(0x12, 0, 0, 0)  # ALT 한 번 — 포그라운드 잠금 우회
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)
    return proc, int(hwnd or 0)


def _on_a_monitor(hwnd: int) -> bool:
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    if rect.right - rect.left < 50 or rect.bottom - rect.top < 50:
        return False
    # MONITOR_DEFAULTTONULL = 0 — 어느 모니터와도 안 겹치면 0 이다(화면 밖).
    return bool(user32.MonitorFromRect(ctypes.byref(rect), 0))


def _rect(hwnd: int) -> list[int]:
    rect = wt.RECT()
    if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return []
    return [rect.left, rect.top, rect.right, rect.bottom]


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="chrome-flash-"))
    config = JarvisConfig(
        runtime_root=root,
        data_dir=root / "data",
        yield_to_user_enabled=True,
        browser_headless=False,
        browser_attach_mode=os.environ.get("ATTACH_MODE", "auto"),
        browser_birth_guard=os.environ.get("BIRTH_GUARD", "1") == "1",
        browser_birth_offscreen=os.environ.get("BIRTH_OFFSCREEN", "1") == "1",
        browser_profile_dir=root / "profile",
        browser_cdp_port=9352,
        browser_max_tabs=6,
    )
    if os.environ.get("SEED_LIKE_LIVE") == "1":
        # ★ 운영 프로필처럼 만든다 — 빈 임시 프로필에서는 번쩍임이 5/5 재현 안 됐다. 운영 프로필은 창 자리를
        #   화면 전체(1920×1032)로 기억하고, 재시작으로 크롬이 강제로 꺼져 종료 상태가 Crashed 였다.
        prefs = root / "profile" / "Default" / "Preferences"
        prefs.parent.mkdir(parents=True, exist_ok=True)
        prefs.write_text(json.dumps({
            "browser": {"window_placement": {
                "bottom": 1032, "left": 0, "maximized": False, "right": 1920, "top": 0,
                "work_area_bottom": 1032, "work_area_left": 0, "work_area_right": 1920, "work_area_top": 0}},
            "profile": {"exit_type": os.environ.get("EXIT_TYPE", "Crashed")},
        }), encoding="utf-8")
    if os.environ.get("RESTORE_MODE") == "old":
        # 예전 복원(맨 뒤 사전 이동 → ShowWindow → 맨 뒤)으로 되돌린다 — 같은 눈금으로 이전/이후를 비교하려고.
        def _old_restore(win_api, hwnd):  # type: ignore[no-untyped-def]
            win_api.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0013)
            win_api.ShowWindow(hwnd, 4)
            BrowserWorker._last_restore_path = "old"
        BrowserWorker._restore_quietly = staticmethod(_old_restore)  # type: ignore[method-assign]
    preexisting_pids = _chrome_pids_now()  # 사람의 크롬 — 이 목록에 없는 chrome.exe 창만 우리 것으로 센다
    worker = BrowserWorker(config)
    # 「지켜보는 사람」 — 운영에서 사람이 자리에 있을 때와 같은 길(앞으로 나오면 안 되는 길)
    worker.presence = UserPresence(config, idle=lambda: 9999.0)

    over_user = 0
    over_any = 0          # 사람 눈에 **보이는** 것(알파>0)만 센 밀리초
    over_any_z = 0        # z 순서상 위였던 시간(투명한 것 포함)
    over_any_under: list[str] = []
    front = 0
    sank_after_seen = 0
    first_seen_at: float | None = None
    first_seen_phase = ""
    phase = "browser_start"
    timeline: list[dict[str, object]] = []
    pre_back_above = 0
    seen_over: set[int] = set()
    stop = threading.Event()
    scapegoat_proc = None
    scapegoat_hwnd = 0
    if os.environ.get("SCAPEGOAT", "1") == "1":
        scapegoat_proc, scapegoat_hwnd = _spawn_scapegoat()
    # 사람이 보던 창. 「팍」은 우리 크롬이 **이 창보다 위에** 겹쳐 그려진 것이다.
    keep = scapegoat_hwnd if scapegoat_hwnd and user32.GetForegroundWindow() == scapegoat_hwnd \
        else user32.GetForegroundWindow()
    keep_class = BrowserWorker._window_class(keep) if keep else ""
    started = time.time()

    # 번쩍임과 브라우저 동작을 같은 시계에 놓는다. 창을 제어하는 본체 코드는
    # 바꾸지 않고 이 측정판의 진입점만 감싼다.
    for method_name in (
        "_spawn_chrome", "_attach_chrome", "_connect_context", "_launch_chrome",
        "_restore_sunk_windows", "_go_home", "_yield_new_window", "_open", "_capture",
    ):
        original = getattr(worker, method_name)

        def traced(*args, _name=method_name, _original=original, **kwargs):
            nonlocal phase
            previous = phase
            phase = _name
            timeline.append({"at": round(time.time() - started, 3), "event": f"{_name}:start"})
            try:
                return _original(*args, **kwargs)
            finally:
                timeline.append({"at": round(time.time() - started, 3), "event": f"{_name}:end"})
                phase = previous

        setattr(worker, method_name, traced)

    def _above(ours: int, other: int) -> bool:
        """z 순서에서 ours 가 other 보다 위인가 — 맨 위 창부터 아래로 훑어 먼저 만나는 쪽."""
        hwnd = user32.GetTopWindow(0)
        for _ in range(4000):
            if not hwnd:
                return False
            if hwnd == ours:
                return True
            if hwnd == other:
                return False
            hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
        return False

    def _overlaps(a: int, b: int) -> bool:
        ra, rb = wt.RECT(), wt.RECT()
        if not (user32.GetWindowRect(a, ctypes.byref(ra)) and user32.GetWindowRect(b, ctypes.byref(rb))):
            return False
        return ra.left < rb.right and rb.left < ra.right and ra.top < rb.bottom and rb.top < ra.bottom

    original_send_to_back = worker._send_window_to_back

    def traced_send_to_back(win_api, hwnd):  # type: ignore[no-untyped-def]
        nonlocal pre_back_above
        above = bool(keep and _above(hwnd, keep) and _overlaps(hwnd, keep))
        if above:
            pre_back_above += 1
        timeline.append({"at": round(time.time() - started, 3), "event": "send_to_back:start",
                         "above_keep": above, "iconic": bool(win_api.IsIconic(hwnd))})
        result = original_send_to_back(win_api, hwnd)
        timeline.append({"at": round(time.time() - started, 3), "event": "send_to_back:end",
                         "above_keep": bool(keep and _above(hwnd, keep))})
        return result

    worker._send_window_to_back = traced_send_to_back

    flash_events: list[dict[str, object]] = []
    over_any_ms_total = [0.0]
    over_z_ms_total = [0.0]
    sample_stats: dict[str, object] = {}

    def _describe(hwnd: int) -> dict[str, object]:
        cls = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, cls, 128)
        return {"hwnd": int(hwnd), "class": cls.value, "title": _title(hwnd)[:40], "rect": _rect(hwnd),
                "ex_style": hex(user32.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF), "alpha": _layered_alpha(hwnd)}

    last_offender: dict[str, object] = {}

    def _above_any(ours: set[int]) -> tuple[bool, str]:
        """우리 창이 z 순서에서 **겹치는 어떤 앱 창 위에** 있는가 — 앞창이 아니어도 번쩍임이다.

        맨 위부터 내려가며, 우리 창을 만난 **뒤에** 나오는 겹치는 앱 창이 있으면 우리가 그 위다.
        쉬는 자리(맨 뒤)의 크롬 아래에는 바탕화면 창뿐이라 이 값이 거짓이다.
        """
        visible_ours = {h for h in ours if not user32.IsIconic(h) and _on_a_monitor(h)}
        if not visible_ours:
            return False, ""
        hwnd = user32.GetTopWindow(0)
        seen: list[int] = []
        for _ in range(4000):
            if not hwnd:
                break
            if int(hwnd) in visible_ours:
                seen.append(int(hwnd))
            elif seen and _is_app_window(hwnd):
                for mine in seen:
                    if _overlaps(mine, hwnd):
                        last_offender.clear()
                        last_offender.update(_describe(mine))  # **무엇이** 올라왔나 — 메인 창인가 보조 창인가
                        return True, _title(hwnd)[:40]
            hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
        return False, ""

    def watch() -> None:
        nonlocal over_user, over_any, over_any_z, front, sank_after_seen, first_seen_at, first_seen_phase
        # ★ 「다 떴다」에서 멈추지 않는다. 처음 판은 거기서 멈춰 5판 모두 0 이 나왔다 — 크롬 창은 그 **뒤에**
        #   나타난다. 사람이 본 것을 못 본 눈금이었다.
        in_episode = False
        in_z_episode = False
        z_start = 0.0
        episode_start = 0.0
        ticks = 0
        watch_started = time.perf_counter()
        while not stop.is_set():
            ticks += 1
            sample_stats["ticks"] = ticks
            sample_stats["avg_tick_ms"] = round((time.perf_counter() - watch_started) / ticks * 1000, 1)
            if scapegoat_hwnd and "scapegoat_iconic_at" not in sample_stats and user32.IsIconic(scapegoat_hwnd):
                sample_stats["scapegoat_iconic_at"] = round(time.time() - started, 3)
            try:
                # ★ birth: 워커가 아니라 이 눈금이 직접 알아본다 — 태어나는 순간의 창도 잡는다.
                visible_now = set(_independent_windows(preexisting_pids))
            except Exception:  # noqa: BLE001
                visible_now = set()
            over = [
                h for h in visible_now
                if not user32.IsIconic(h) and _on_a_monitor(h) and keep and _overlaps(h, keep) and _above(h, keep)
            ]
            try:
                covering, under = _above_any(visible_now)
            except Exception:  # noqa: BLE001 — 못 재면 세지 않는다(거짓 양성보다 낫다)
                covering, under = False, ""
            visible_cover = bool(covering and int(last_offender.get("alpha", 255)) > 0)
            now_pc = time.perf_counter()
            # z 순서 기준(투명한 것 포함)
            if covering:
                if not in_z_episode:
                    z_start = now_pc
                in_z_episode = True
                over_any_z = int(round(over_z_ms_total[0] + (now_pc - z_start) * 1000))
            elif in_z_episode:
                over_z_ms_total[0] += (now_pc - z_start) * 1000
                over_any_z = int(round(over_z_ms_total[0]))
                in_z_episode = False
            # 사람 눈에 보이는 기준(알파 > 0)
            if visible_cover:
                if not in_episode:
                    episode_start = now_pc
                    if len(flash_events) < 20:
                        flash_events.append({"at": round(time.time() - started, 3), "phase": phase, "over": under,
                                             "who": dict(last_offender),
                                             "all_ours": [_describe(h) for h in visible_now]})
                in_episode = True
                over_any = int(round(over_any_ms_total[0] + (now_pc - episode_start) * 1000))
                if flash_events:
                    flash_events[-1]["ms"] = round((now_pc - episode_start) * 1000)
            else:
                if in_episode:
                    over_any_ms_total[0] += (now_pc - episode_start) * 1000
                    over_any = int(round(over_any_ms_total[0]))
                in_episode = False
            if over or visible_cover:
                over_user += 1 if over else 0
                if first_seen_at is None:
                    first_seen_at = time.time() - started
                    first_seen_phase = phase
                seen_over.update(over)
            for hwnd in list(seen_over):
                if user32.IsIconic(hwnd):
                    sank_after_seen += 1
                    seen_over.discard(hwnd)
            fg = user32.GetForegroundWindow()
            if fg:
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
                try:
                    if worker._is_our_chrome_pid(int(pid.value)):
                        front += 1
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(TICK)

    pixel_frames: list[dict[str, object]] = []
    pixel_stats: dict[str, object] = {"grabs": 0}
    pixel_file = root / "pixels.jsonl"
    pixel_proc = None

    # ★ 픽셀 감시는 **별도 프로세스**다. 같은 프로세스 스레드로 돌렸더니 GIL·화면 캡처 부하로 타이밍이 바뀌어
    #   예전 복원에서도 번쩍임이 4/4 사라졌다 — 눈금이 대상을 바꿔 버린 것이다.
    #   z 순서 눈금은 윈도우의 최소화 해제 **애니메이션**(150~250ms)을 못 본다. 픽셀 표집(~30ms)은 10~40ms 번쩍임은
    #   놓치고 애니메이션처럼 긴 것만 잡는다 — 그것이 이 눈금의 몫이다.
    if os.environ.get("PIXEL_WATCH") == "1":
        import subprocess

        child = Path(__file__).with_name("pixel_watch_child.py")
        pixel_proc = subprocess.Popen([sys.executable, str(child), str(pixel_file), "12"])
        time.sleep(1.0)  # 기준 색을 읽을 시간

    threading.Thread(target=watch, daemon=True).start()
    out: dict = {"attach_mode": config.browser_attach_mode}
    try:
        worker.execute_trusted("browser_open", {"url": "https://example.com"})
        out["open_ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["open_ok"] = False
        out["open_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    if os.environ.get("INJECT_FLASH") == "1":
        # ★ 양성 대조 — 눈금이 **진짜(보이는) 번쩍임을 잡는가**. 감시 스레드(8초)가 끝난 뒤 크롬을 실제로
        #   60ms 앞으로 올렸다 내린다(감시가 살아 있으면 20ms 마다 도로 내려서 올릴 수가 없다).
        #   이게 안 잡히면 0 이라는 숫자는 「안 번쩍인다」가 아니라 「못 본다」다.
        for _ in range(200):
            if (getattr(worker, "_sink_report", {}) or {}).get("thread") == "done":
                break
            time.sleep(0.1)
        time.sleep(0.5)
        target = worker._our_chrome_windows()
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        for hwnd in target:
            user32.SetForegroundWindow(hwnd)
        time.sleep(0.06)
        for hwnd in target:
            worker._send_window_to_back(user32, hwnd)
        if keep:
            user32.SetForegroundWindow(keep)
        out["injected_flash_ms"] = 60
        time.sleep(1.0)
    else:
        time.sleep(5)
    stop.set()
    time.sleep(0.2)
    if pixel_proc is not None:
        try:
            pixel_proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            pixel_proc.kill()
        try:
            for line in pixel_file.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if "t" in row and len(pixel_frames) < 80:
                    pixel_frames.append({"at": round(row["t"] - started, 3), "changed": row["changed"]})
                elif "grabs" in row:
                    pixel_stats["grabs"] = row["grabs"]
        except Exception:  # noqa: BLE001
            pass
    # 판이 **유효한지** — 희생양이 끝까지 화면에 있었나. 최소화되면 바탕화면이 비쳐 눈금이 오염된다.
    scapegoat_valid = bool(not scapegoat_hwnd or (not user32.IsIconic(scapegoat_hwnd) and _on_a_monitor(scapegoat_hwnd)))
    report = getattr(worker, "_sink_report", {}) or {}
    out.update({
        "keep_hwnd": int(keep or 0),
        "keep_class": keep_class,
        "keep_rect": _rect(keep),
        "chrome_rects": [_rect(int(h)) for h in worker._our_chrome_windows()],
        "over_user_ms": round(over_user * TICK * 1000),
        # 겹치는 **어떤** 앱 창 위에든 올라온 시간 — 앞창이 어느 모니터에 있든 잡는 눈금.
        # over_any 는 이제 **실제 시각으로 잰 밀리초**다(틱 수 × 주기는 틱이 길어 과소 계상했다).
        "over_any_ms": over_any,
        "over_any_z_ms": over_any_z,
        "valid_run": scapegoat_valid,
        "pixel_frames": pixel_frames,
        "pixel_grabs": pixel_stats["grabs"],
        "restore_path": getattr(BrowserWorker, "_last_restore_path", "(안 불림)"),
        "sampling": sample_stats,
        "flash_events": flash_events,
        "scapegoat": {"hwnd": scapegoat_hwnd, "is_keep": bool(scapegoat_hwnd and keep == scapegoat_hwnd),
                      "rect": _rect(scapegoat_hwnd)},
        "cold_start": True,
        "ruler": "independent (birth 포함)",
        "front_ms": round(front * TICK * 1000),
        "sank_after_seen": sank_after_seen,
        "first_seen_at_sec": None if first_seen_at is None else round(first_seen_at, 2),
        "first_seen_phase": first_seen_phase,
        "pre_back_above": pre_back_above,
        "timeline": timeline,
        "restored_at": report.get("restored_at"),
        "window_sink": {k: v for k, v in report.items() if k != "rose_above_at"},
        "sunk": report.get("sunk"),
        "connect_mode": getattr(worker, "_connect_mode", None),
        "cdp_port_in_use": getattr(worker, "_cdp_port_in_use", None),
        "attach_error": str(getattr(worker, "_attach_error", "") or "")[:80],
    })
    # 되살린 뒤 창이 **정상으로 돌아왔는지** — 레이어드가 남았거나 알파가 0 이면 창이 영영 투명하다.
    try:
        out["final_chrome"] = [_describe(int(h)) for h in worker._our_chrome_windows()]
    except Exception as exc:  # noqa: BLE001
        out["final_chrome"] = f"{type(exc).__name__}"
    try:
        out["live_frame_bytes"] = len((worker.live_frame() or {}).get("jpeg") or b"")
    except Exception as exc:  # noqa: BLE001
        out["live_frame_bytes"] = f"{type(exc).__name__}"
    try:
        worker.stop()
    except Exception:  # noqa: BLE001
        pass
    if scapegoat_proc is not None:
        try:
            scapegoat_proc.kill()
        except Exception:  # noqa: BLE001
            pass
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
