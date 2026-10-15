"""막 태어난 크롬 창은 **보이기 전에** 투명하게 만든다 — 콜드스타트 번쩍임의 나머지 조각 (2026-09-21, 사장님).

> 온텔릭 전용 크롬이 떠 있으면 안 번쩍거리는데 콜드스타트할 때 번쩍거려.
> (그 뒤) 아직 내 PC 운영 앱은 콜드스타트하면 번쩍인다.

## 이번 조각

되살리는 순간(`_restore_quietly`)은 이미 투명하게 했다. 그런데 **운영 콜드스타트를 밖에서 관찰**했더니 그보다 앞에 두 가지가 더 있었다:

1. **창 탄생**: 크롬이 `wShowWindow=SW_SHOWMINNOACTIVE` 를 줘도 자기를 다시 띄워서, 첫 창이 비최소화·전체 화면으로 태어나
   ~16ms 동안 다른 창 위에 보인 뒤 20ms 감시 스레드가 최소화했다. 실험실 눈금은 새 창을 「우리 것」으로 알아보는 캐시가 있어서
   이 순간을 못 봤다 — 같은 코드의 눈으로 재면 같은 곳에서 못 본다.
2. **앞창 다툼**: 크롬이 앞창을 되풀이해 쥐고(운영 1.4초) 감시 스레드가 매번 내렸다 올렸다. 그 사이마다 창이 보였다.

## 고친 것

뜨는 동안 **창 표시 이벤트(`SetWinEventHook`)** 로 새 크롬 주 창을 받자마자 알파 0 으로 만들고, 다 뜨면(`settled`) 한꺼번에 불투명으로
돌린다. 폴링 틈이 없고, 그 동안의 최소화·복원 소용돌이는 투명한 채 일어난다.

## 안전 (안 보이는 크롬은 사고다)

- 끝나면 **반드시** 불투명으로 — `finally`, 그리고 「크롬 창 보기」를 누른 순간에도.
- 백엔드가 죽어도 크롬은 산다 → 다음 기동 때 **투명한 채 남은 우리 창을 청소**한다.
- 말풍선·메뉴·툴팁(`WS_POPUP`)과 사람의 크롬(띄우기 전에 있던 pid)은 건드리지 않는다.
"""

from __future__ import annotations

import ctypes
import inspect
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

_LAYERED = 0x80000
_CAPTION = 0xC00000


class _Win:
    """Win32 를 흉내 내는 가짜. 창마다 (클래스, pid, 스타일, 확장스타일, 알파) 를 든다."""

    def __init__(self, windows: dict[int, dict[str, Any]] | None = None) -> None:
        self.windows = windows or {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _w(self, hwnd: int) -> dict[str, Any]:
        return self.windows.setdefault(hwnd, {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION,
                                              "ex": 0x200100, "alpha": 255, "alive": True})

    def GetClassNameW(self, hwnd, buf, size):  # noqa: N802
        buf.value = self._w(hwnd)["cls"]
        return len(buf.value)

    def GetWindowThreadProcessId(self, hwnd, ref):  # noqa: N802
        ref._obj.value = self._w(hwnd)["pid"]
        return 1

    def GetWindowLongW(self, hwnd, index):  # noqa: N802
        return self._w(hwnd)["style"] if index == -16 else self._w(hwnd)["ex"]

    def SetWindowLongW(self, hwnd, index, value):  # noqa: N802
        self.calls.append(("SetWindowLongW", (hwnd, index, value)))
        if index == -20:
            self._w(hwnd)["ex"] = value
        return 1

    def SetLayeredWindowAttributes(self, hwnd, key, alpha, flags):  # noqa: N802
        self.calls.append(("SetLayeredWindowAttributes", (hwnd, key, alpha, flags)))
        self._w(hwnd)["alpha"] = alpha
        return 1

    def IsWindow(self, hwnd):  # noqa: N802
        return 1 if self._w(hwnd)["alive"] else 0

    def ShowWindow(self, hwnd, command):  # noqa: N802
        self.calls.append(("ShowWindow", (hwnd, command)))
        return 1

    def SetWindowPos(self, *args):  # noqa: N802
        self.calls.append(("SetWindowPos", args))
        return 1


def _worker(tmp_path: Path, **config_over: Any) -> BrowserWorker:
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                                        output_dir=tmp_path / "out", **config_over))
    worker._chrome_pids_before_launch = {100, 101}   # 사람의 크롬
    worker._process_name = lambda pid: "chrome.exe"  # type: ignore[method-assign]
    BrowserWorker._newborn_transparent.clear()
    return worker


def test_a_newborn_main_window_of_a_new_chrome_is_hidden(tmp_path: Path) -> None:
    worker, win = _worker(tmp_path), _Win({7: {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION,
                                               "ex": 0x200100, "alpha": 255, "alive": True}})

    assert worker._newborn_should_hide(win, 7, {}) is True
    worker._make_newborn_transparent(win, 7)

    assert win.windows[7]["alpha"] == 0 and win.windows[7]["ex"] & _LAYERED
    assert 7 in BrowserWorker._newborn_transparent


@pytest.mark.parametrize("case", [
    {"pid": 100},                                   # 띄우기 전부터 있던 사람의 크롬
    {"cls": "Chrome_WidgetWin_0"},                  # 크롬의 숨은 메시지 창
    {"style": 0x80000000},                          # WS_POPUP — 말풍선·메뉴·툴팁
])
def test_it_never_touches_the_humans_chrome_or_popups(tmp_path: Path, case: dict[str, Any]) -> None:
    base = {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION, "ex": 0x200100, "alpha": 255, "alive": True}
    worker, win = _worker(tmp_path), _Win({7: {**base, **case}})

    assert worker._newborn_should_hide(win, 7, {}) is False


def test_a_window_of_another_program_with_the_same_class_is_left_alone(tmp_path: Path) -> None:
    """Electron 앱(클로드 데스크톱 등)도 `Chrome_WidgetWin_1` 을 쓴다 — 프로세스 이름으로 갈라야 한다."""
    worker = _worker(tmp_path)
    worker._process_name = lambda pid: "claude.exe"  # type: ignore[method-assign]
    win = _Win({7: {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION, "ex": 0x200100, "alpha": 255,
                    "alive": True}})

    assert worker._newborn_should_hide(win, 7, {}) is False


def test_finishing_makes_every_hidden_window_opaque_and_restores_its_style(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    win = _Win({7: {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION, "ex": 0x200100, "alpha": 255,
                    "alive": True}})
    worker._make_newborn_transparent(win, 7)

    worker._finish_newborn_windows(win)

    assert win.windows[7]["alpha"] == 255
    assert win.windows[7]["ex"] == 0x200100, "레이어드를 우리가 켰으면 끝나고 벗겨야 한다"
    assert BrowserWorker._newborn_transparent == {}


def test_a_window_that_was_already_layered_keeps_its_style(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    win = _Win({7: {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION, "ex": 0x200100 | _LAYERED,
                    "alpha": 255, "alive": True}})
    worker._make_newborn_transparent(win, 7)

    worker._finish_newborn_windows(win)

    assert win.windows[7]["ex"] & _LAYERED


def test_a_window_that_died_meanwhile_is_skipped_not_crashed(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    win = _Win({7: {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION, "ex": 0x200100, "alpha": 255,
                    "alive": True}})
    worker._make_newborn_transparent(win, 7)
    win.windows[7]["alive"] = False

    worker._finish_newborn_windows(win)

    assert BrowserWorker._newborn_transparent == {}


def test_the_quiet_restore_does_not_make_a_newborn_opaque_midway(tmp_path: Path) -> None:
    """뜨는 동안 되살림이 여러 번 불려도 그때마다 보이면 소용돌이가 그대로 보인다 — 끝에서 한 번만 불투명."""
    worker = _worker(tmp_path)
    win = _Win({7: {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION, "ex": 0x200100, "alpha": 255,
                    "alive": True}})
    worker._make_newborn_transparent(win, 7)

    BrowserWorker._restore_quietly(win, 7)

    assert win.windows[7]["alpha"] == 0
    assert 7 in BrowserWorker._newborn_transparent


def test_stuck_transparent_windows_from_a_crashed_backend_are_cleaned_up(tmp_path: Path) -> None:
    """백엔드가 죽어도 크롬은 산다 — 투명한 채 남으면 사용자는 안 보이는 크롬을 갖게 된다."""
    worker = _worker(tmp_path)
    win = _Win({7: {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION, "ex": 0x200100 | _LAYERED,
                    "alpha": 0, "alive": True}})
    def _layered(hwnd, key, alpha, flags):  # noqa: ANN001
        alpha._obj.value = win.windows[hwnd]["alpha"]
        flags._obj.value = 0x2  # LWA_ALPHA
        return 1

    win.GetLayeredWindowAttributes = _layered  # type: ignore[attr-defined]
    worker._our_chrome_windows = lambda include_iconic=False: [7]  # type: ignore[method-assign]

    assert worker._sweep_stuck_transparent(win) == 1
    assert win.windows[7]["alpha"] == 255


def test_the_guard_can_be_turned_off_by_config(tmp_path: Path) -> None:
    worker = _worker(tmp_path, browser_birth_guard=False)

    assert worker._start_birth_guard() is False


def test_the_guard_starts_before_chrome_is_launched_on_both_paths() -> None:
    """창이 태어난 뒤에 가드를 세우면 이미 늦다 — 띄우기 **전에** 세워야 한다(순서가 곧 고침이다)."""
    spawn = inspect.getsource(BrowserWorker._spawn_chrome)
    assert spawn.index("_start_birth_guard()") < spawn.index("subprocess.Popen"), "조용한 경로"
    launch = inspect.getsource(BrowserWorker._launch_chrome)
    assert launch.index("self._start_birth_guard()") < launch.index("self._playwright.chromium.launch_persistent_context("), (
        "Playwright 폴백 경로")


def test_asking_to_see_the_window_makes_it_opaque_first() -> None:
    """「크롬 창 보기」를 눌렀는데 창이 투명하면 안 된다."""
    source = inspect.getsource(BrowserWorker._present_for_human)
    assert "_finish_newborn_windows(" in source and "_birth_guard_stop" in source


def test_the_guard_finishes_in_a_finally_so_it_cannot_leave_a_window_invisible() -> None:
    source = inspect.getsource(BrowserWorker._birth_guard)
    assert "finally:" in source and "_finish_newborn_windows(" in source.split("finally:")[1]


def test_the_ruler_does_not_share_the_workers_blind_spot() -> None:
    """눈금이 워커와 같은 캐시로 창을 알아보면 워커가 못 보는 순간을 눈금도 못 본다(실험실 0/8 이 운영을 못 덮은 이유)."""
    ruler = (Path(__file__).parent.parent / "bench" / "browser_agents" / "measure_chrome_flash.py").read_text(
        encoding="utf-8")
    assert "_independent_windows" in ruler and "birth" in ruler


def test_a_hidden_window_that_chrome_made_visible_again_is_hidden_again(tmp_path: Path) -> None:
    """★ 크롬은 창을 보일 때 스스로 레이어드 속성을 만진다 — 알파 0 을 걸어도 그 뒤에 되돌려질 수 있다.

    폴백(Playwright) 경로 실측: 가드가 창이 태어날 때(CREATE) 숨겼는데도 눈금엔 알파 255 로 6~13ms 보였다. 숨긴 뒤에도
    표시·위치·순서 이벤트마다 확인해서 되돌려졌으면 다시 건다.
    """
    worker = _worker(tmp_path)
    win = _Win({7: {"cls": "Chrome_WidgetWin_1", "pid": 500, "style": _CAPTION, "ex": 0x200100, "alpha": 255,
                    "alive": True}})

    def _layered(hwnd, key, alpha, flags):  # noqa: ANN001
        alpha._obj.value = win.windows[hwnd]["alpha"]
        flags._obj.value = 0x2
        return 1

    win.GetLayeredWindowAttributes = _layered  # type: ignore[attr-defined]
    worker._make_newborn_transparent(win, 7)
    assert win.windows[7]["alpha"] == 0

    win.windows[7]["alpha"] = 255            # 크롬이 되돌렸다
    stats: dict[str, Any] = {}
    assert worker._reassert_transparent(win, 7, stats) is True
    assert win.windows[7]["alpha"] == 0 and stats["reasserted"] == 1

    assert worker._reassert_transparent(win, 7, stats) is False, "이미 숨겨져 있으면 건드리지 않는다"
    assert stats["reasserted"] == 1


def test_the_hook_listens_beyond_show_events() -> None:
    source = inspect.getsource(BrowserWorker._birth_guard)
    assert "0x800B" in source and "_reassert_transparent(" in source


# ── 화면 밖에서 태어나게 한다 (반응 지연이 0 이 아닌 한 훅·폴링으로는 못 없앤다) ───────────────────────
#
# 훅으로 창을 숨겨도 눈금이 창을 처음 보는 순간엔 이미 보였다 — 이벤트 전달 + 파이썬 GIL 전환(5ms) 지연 때문에 8~26ms.
# 숨긴 hwnd 와 번쩍인 hwnd 가 **같은 창**이라는 것을 대조로 확인했다. 지연이 있는 한 반응으로는 0 에 못 간다.
# 그래서 창이 **어느 모니터에도 안 겹치는 자리에서 태어나게** 한다. 크롬은 `--window-position` 의 화면 밖 좌표를
# 그대로 받는다(실측: (2220,0)·(-20000,-20000) 둘 다 그 자리에 생김). 자동화 탐지 신호가 아니다.

class _Metrics:
    def __init__(self, x: int, y: int, w: int) -> None:
        self.values = {76: x, 77: y, 78: w}

    def GetSystemMetrics(self, index):  # noqa: N802
        return self.values[index]


def test_the_offscreen_position_is_beyond_every_monitor(tmp_path: Path) -> None:
    worker = _worker(tmp_path)

    # 듀얼 모니터: 가상 화면 x=-1920 .. 1920 → 오른쪽 바깥
    args = worker._offscreen_window_args(_Metrics(-1920, 0, 3840))

    assert args == ["--window-position=2120,0"], args


def test_the_offscreen_args_can_be_turned_off_by_config(tmp_path: Path) -> None:
    worker = _worker(tmp_path, browser_birth_offscreen=False)

    assert worker._offscreen_window_args(_Metrics(0, 0, 1920)) == []


def test_both_quiet_launch_paths_ask_for_an_offscreen_birth() -> None:
    """조용한 경로(스폰)와 Playwright 폴백 둘 다 — 한쪽만 고치면 다른 쪽이 그대로 번쩍인다(4/5 → 8/8 이 그 자리였다)."""
    spawn = inspect.getsource(BrowserWorker._spawn_chrome)
    assert "_offscreen_window_args()" in spawn
    launch = inspect.getsource(BrowserWorker._launch_chrome)
    assert "_offscreen_window_args()" in launch


def test_the_window_is_brought_onto_the_screen_when_it_settles() -> None:
    """화면 밖에서 태어난 창은 다 뜨면 사용자 화면의 작업 영역으로 **데려와** 맨 뒤에 둔다 — 안 그러면 작업 표시줄에서 눌러도 안 보인다."""
    source = inspect.getsource(BrowserWorker._usable_window_rect)
    assert "on_monitor" in source and "GetForegroundWindow" in source, "모니터 밖 창(유령)을 사람이 보는 화면으로 데려오는 규칙"
