"""그림 한 장이 브라우저 전체를 막으면 안 된다 (2026-09-16).

## 왜

이어받기 e2e 5·6·7판이 전부 사람인 검색 결과에서 `browser_busy_stuck` 으로 멈췄다.
실시간 화면 캡처가 CDP `Page.captureScreenshot` 을 **제한 없이** 불렀고, 크로미움은
프레임을 안 만드는 탭(최소화된 창 · 배경 탭)에서 그 요청에 답하지 않는다.
브라우저 전용 스레드가 무기한 쥐어져 뒤따른 모든 도구가 거절됐다.

재현(임시 프로필 크롬): 최소화+앞탭 · 최소화+배경탭 · 맨뒤+배경탭 → 8초 넘게 안 옴,
맨뒤+앞탭 → 0.04초. 그리고 네 조건 **전부** `visibilityState` 는 `visible` 이었다 —
페이지 안에서 미리 가를 수 없어서 제한을 건다.

## 이 검사가 지키는 것

1. 조용한 캡처는 **시간 제한이 있는 호출**만 쓴다
2. 제한에 걸린 탭은 잠깐 다시 안 찍는다 — 1.5초마다 2.5초씩 태우면 일꾼을 계속 쥔다
3. 제한에 걸린 뒤 **제한 없는 길로 되돌아가지 않는다**
4. 창은 뜨는 동안만 최소화하고, 다 뜨면 활성화 없이 되살려 맨 뒤로 둔다(최소화한 창은 그림을 안 만든다)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Presence:
    def active(self) -> bool:
        return False


class _HiddenTab:
    """프레임을 안 만드는 탭. 제한 있는 캡처는 시간 초과로, 직접 CDP 는 무한 대기로 흉내 낸다."""

    url = "https://www.saramin.co.kr/zf_user/search?searchword=x"

    def __init__(self) -> None:
        self.screenshot_calls: list[dict[str, Any]] = []

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "사람인 검색"

    def screenshot(self, **kwargs: Any) -> bytes:
        self.screenshot_calls.append(kwargs)
        if kwargs.get("timeout") is None:
            raise AssertionError("제한 없는 캡처를 불렀다 — 이 탭에서는 영원히 안 돌아온다")
        raise TimeoutError(f"Page.screenshot: Timeout {kwargs['timeout']}ms exceeded.")


class _Context:
    def __init__(self, page: Any) -> None:
        self.pages = [page]

    def new_cdp_session(self, _page: Any) -> Any:
        raise AssertionError("CDP 캡처를 직접 불렀다 — 그 호출에는 시간 제한이 없다")


def _quiet_worker(tmp_path: Path, page: Any) -> BrowserWorker:
    worker = BrowserWorker(
        JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    )
    worker.presence = _Presence()  # 이게 있어야 「앞으로 가져오지 말 것」이 켜진다
    worker.config.browser_allow_foreground = False
    worker._context = _Context(page)
    worker._page = page
    worker._context_alive = lambda: True  # type: ignore[method-assign]
    return worker


def test_a_hidden_tab_capture_is_bounded_and_says_why(tmp_path: Path) -> None:
    page = _HiddenTab()
    worker = _quiet_worker(tmp_path, page)

    assert worker._capture(page, quiet=True) is None
    assert worker._capture_skip_reason == "capture_timeout_hidden_tab"
    assert page.screenshot_calls and page.screenshot_calls[0]["timeout"] <= 3000


def test_a_stalled_tab_is_not_retried_every_poll(tmp_path: Path) -> None:
    """실시간 화면은 1.5초마다 온다. 매번 2.5초를 태우면 일꾼을 사실상 계속 쥔다."""
    page = _HiddenTab()
    worker = _quiet_worker(tmp_path, page)

    for _ in range(5):
        worker._capture(page, quiet=True)

    assert len(page.screenshot_calls) == 1
    assert worker._capture_skip_reason == "capture_timeout_hidden_tab"


def test_the_live_frame_does_not_fall_back_to_an_unbounded_capture(tmp_path: Path) -> None:
    page = _HiddenTab()
    worker = _quiet_worker(tmp_path, page)

    with pytest.raises(RuntimeError, match="capture_timeout_hidden_tab"):
        worker._capture_live_frame()
    # 제한 있는 한 번만 — 예전 폴백(4초짜리 두 번째 캡처)으로 가지 않았다.
    assert len(page.screenshot_calls) == 1


def test_a_visible_tab_still_captures(tmp_path: Path) -> None:
    class _VisibleTab(_HiddenTab):
        def screenshot(self, **kwargs: Any) -> bytes:
            self.screenshot_calls.append(kwargs)
            return b"\xff\xd8\xff\xdb-jpeg"

    page = _VisibleTab()
    worker = _quiet_worker(tmp_path, page)

    frame = worker._capture_live_frame()

    assert frame["jpeg"].startswith(b"\xff\xd8\xff")
    assert frame["title"] == "사람인 검색"
    assert worker._capture_skip_reason == ""


def test_a_tab_that_recovers_is_captured_again_after_the_backoff(tmp_path: Path) -> None:
    page = _HiddenTab()
    worker = _quiet_worker(tmp_path, page)
    worker._capture(page, quiet=True)

    at, reason, rest = worker._capture_stalled[id(page)]
    worker._capture_stalled[id(page)] = (at - rest - 1, reason, rest)
    worker._capture(page, quiet=True)

    assert len(page.screenshot_calls) == 2


class _User32:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def SetWindowPos(self, *args: Any) -> int:  # noqa: N802 - Win32 이름 그대로
        self.calls.append(("SetWindowPos", args))
        return 1

    def ShowWindow(self, *args: Any) -> int:  # noqa: N802
        self.calls.append(("ShowWindow", args))
        return 1

    def SetForegroundWindow(self, *args: Any) -> int:  # noqa: N802
        self.calls.append(("SetForegroundWindow", args))
        return 1


def test_our_window_goes_to_the_back_without_being_minimized_or_activated() -> None:
    user32 = _User32()

    BrowserWorker._send_window_to_back(user32, 4242)

    assert [name for name, _ in user32.calls] == ["SetWindowPos"], "최소화·크기 바꾸기를 부르면 안 된다"
    hwnd, insert_after, *_rest, flags = user32.calls[0][1]
    assert hwnd == 4242
    assert insert_after == 1  # HWND_BOTTOM
    assert flags & 0x0010, "SWP_NOACTIVATE 가 빠지면 뒤로 보내면서 앞창을 뺏는다"
    assert flags & 0x0001 and flags & 0x0002, "크기·위치를 건드리면 최대화가 풀린다"


def test_windows_we_sank_during_launch_are_restored_behind_without_activation(tmp_path: Path) -> None:
    """뜨는 동안 최소화한 창을 **그대로 두면** 실시간 화면이 영영 안 찍힌다(2026-09-16)."""

    class _Iconic(_User32):
        def IsWindow(self, hwnd: int) -> int:  # noqa: N802
            return 1

        def IsIconic(self, hwnd: int) -> int:  # noqa: N802
            return 1 if hwnd == 11 else 0  # 12 는 사람이 이미 되살린 창

    worker = BrowserWorker(
        JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    )
    worker._sunk_hwnds = {11, 12}
    worker._our_chrome_windows = lambda include_iconic=False: []  # type: ignore[method-assign]
    user32 = _Iconic()

    assert worker._restore_sunk_windows(user32) == 1
    assert ("ShowWindow", (11, 4)) in user32.calls, "SW_SHOWNOACTIVATE 로 되살려야 한다"
    assert not any(name == "ShowWindow" and args[0] == 12 for name, args in user32.calls)
    assert any(name == "SetWindowPos" and args[0] == 11 and args[1] == 1 for name, args in user32.calls)
    assert [name for name, _ in user32.calls[:2]] == ["SetWindowPos", "ShowWindow"], (
        "복원 전에 맨 뒤로 내리지 않으면 사용자 창 위에 잠깐 그려진다"
    )
    assert user32.calls[0][1][-1] & 0x0013 == 0x0013, "사전 이동은 크기·위치·포커스를 보존해야 한다"
    assert worker._sunk_hwnds == set()


def test_settling_is_signalled_when_the_browser_is_ready(tmp_path: Path, monkeypatch) -> None:
    """다 뜬 자리(`_yield_new_window`)가 감시에게 알리지 않으면 창이 최소화된 채 남는다."""
    import sys as _sys

    worker = _quiet_worker(tmp_path, _HiddenTab())
    worker.config.browser_headless = False
    worker._browser_is_ours = lambda: True  # type: ignore[method-assign]
    worker._our_chrome_windows = lambda: []  # type: ignore[method-assign]
    restored: list[bool] = []
    worker._restore_sunk_windows = lambda _u: restored.append(True) or 0  # type: ignore[method-assign]
    worker._sink_report = {"thread": "done"}
    monkeypatch.setattr(_sys, "platform", "win32")

    worker._yield_new_window(worker._page)

    assert worker._sink_settled.is_set()
    assert restored == [True], "감시가 이미 끝났으면 다 뜬 자리가 직접 되살려야 한다"


def test_when_our_chrome_holds_focus_it_is_handed_back_and_the_window_stays_visible() -> None:
    """맨 뒤로만 보내면 포커스가 안 돌아온다(2026-09-16 실측 0.2~1.0초). 최소화로 활성을 넘기되
    **최소화된 채로 두지 않는다** — 마지막 창 상태가 보이는 창이어야 탭이 그림을 만든다."""
    user32 = _User32()

    BrowserWorker._give_focus_back(user32, 4242, keep=777)

    shows = [args[1] for name, args in user32.calls if name == "ShowWindow"]
    assert shows == [7, 4], "최소화(7)로 활성을 넘긴 뒤 활성화 없이(4) 되살려야 한다"
    names = [name for name, _ in user32.calls]
    assert names.index("SetWindowPos") > names.index("ShowWindow")
    assert ("SetForegroundWindow", (777,)) in user32.calls


def test_a_window_that_was_born_minimized_is_restored_too(tmp_path: Path) -> None:
    """운영 기본 길은 크롬이 처음부터 최소화로 떠서 감시가 적은 창이 0개였다 — 화면 0/18 판(2026-09-16)."""

    class _Iconic(_User32):
        def IsWindow(self, hwnd: int) -> int:  # noqa: N802
            return 1

        def IsIconic(self, hwnd: int) -> int:  # noqa: N802
            return 1

    worker = BrowserWorker(
        JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    )
    worker._sunk_hwnds = set()
    asked: list[bool] = []

    def windows(include_iconic: bool = False) -> list[int]:
        asked.append(include_iconic)
        return [21] if include_iconic else []

    worker._our_chrome_windows = windows  # type: ignore[method-assign]
    user32 = _Iconic()

    assert worker._restore_sunk_windows(user32) == 1
    assert asked == [True]
    assert ("ShowWindow", (21, 4)) in user32.calls



def test_a_minimized_window_is_a_state_not_an_error(tmp_path: Path) -> None:
    """2026-09-17: 최소화된 크롬(폭 0)의 원문 오류가 화면에 그대로 떴다 — 창 상태로 분류하고 짧게 쉰다."""

    class _Minimized(_HiddenTab):
        def screenshot(self, **kwargs: Any) -> bytes:
            self.screenshot_calls.append(kwargs)
            raise RuntimeError("Page.screenshot: Protocol error (Page.captureScreenshot): Cannot take screenshot with 0 width.")

    page = _Minimized()
    worker = _quiet_worker(tmp_path, page)

    assert worker._capture(page, quiet=True) is None
    assert worker._capture_skip_reason == "capture_window_minimized"
    worker._capture(page, quiet=True)
    assert len(page.screenshot_calls) == 1, "쉬는 동안 다시 찍으면 1.5초마다 같은 오류를 만든다"
    assert worker._capture_stalled[id(page)][2] <= 5.0, "창을 올리면 금방 다시 보여야 한다"


class _Placed(_User32):
    """창 자리를 재는 가짜. `rect` 는 (left, top, right, bottom)."""

    def __init__(self, rect: tuple[int, int, int, int], on_monitor: bool, zoomed: bool = False) -> None:
        super().__init__()
        self.rect, self.on_monitor, self.zoomed = rect, on_monitor, zoomed

    def IsZoomed(self, hwnd: int) -> int:  # noqa: N802
        return 1 if self.zoomed else 0

    def GetWindowRect(self, hwnd: int, ref: Any) -> int:  # noqa: N802
        target = ref._obj
        target.left, target.top, target.right, target.bottom = self.rect
        return 1

    def MonitorFromRect(self, ref: Any, flags: int) -> int:  # noqa: N802
        return 99 if self.on_monitor else 0

    def GetForegroundWindow(self) -> int:  # noqa: N802
        return 777

    def MonitorFromWindow(self, hwnd: int, flags: int) -> int:  # noqa: N802
        return 99

    def GetMonitorInfoW(self, monitor: int, ref: Any) -> int:  # noqa: N802
        work = ref._obj.rcWork
        work.left, work.top, work.right, work.bottom = 0, 0, 1920, 1040
        return 1


def test_a_window_restored_off_screen_is_spread_over_the_users_monitor_behind_everything() -> None:
    """2026-09-17 실측: 최소화로 태어난 창을 되살리니 (-32000,-32000) 516×129 — 안 보이고 캡처는 흰 줄."""
    user32 = _Placed((-32000, -32000, -31484, -31871), on_monitor=False)

    BrowserWorker._send_window_to_back(user32, 4242)

    (name, args), = user32.calls
    hwnd, insert_after, left, top, width, height, flags = args
    assert name == "SetWindowPos" and hwnd == 4242 and insert_after == 1
    assert (left, top, width, height) == (0, 0, 1920, 1040), "사람이 쓰는 모니터의 작업 영역으로 편다"
    assert flags & 0x0010 and not flags & 0x0001 and not flags & 0x0002, "크기·위치는 주고, 활성화는 안 한다"


def test_a_tiny_window_on_a_monitor_is_also_repaired() -> None:
    user32 = _Placed((100, 100, 616, 229), on_monitor=True)
    BrowserWorker._send_window_to_back(user32, 1)
    assert user32.calls[0][1][4:6] == (1920, 1040)


def test_a_maximized_window_on_a_left_monitor_with_negative_coordinates_is_left_alone() -> None:
    """왼쪽 보조 모니터의 창은 좌표가 음수다 — 부호가 아니라 모니터 위에 있는가로 가른다.

    그리고 **최대화된 창에는 크기를 주지 않는다** — 주는 순간 최대화가 풀린다.
    """
    user32 = _Placed((-1920, 0, -200, 1000), on_monitor=True, zoomed=True)
    BrowserWorker._send_window_to_back(user32, 1)
    flags = user32.calls[0][1][-1]
    assert flags & 0x0001 and flags & 0x0002, "최대화된 창의 크기·위치는 건드리지 않는다"


def test_a_window_that_is_not_maximized_is_spread_over_its_own_monitor() -> None:
    """2026-09-18 사용자 화면: 「망가지진 않았는데 비율이 이상한」 창.

    조용히 뜨는 길은 `--start-maximized` 를 안 붙여서(최소화 출생과 싸운다) 되살아난 창이
    크롬 기본 크기로 남았다. 480×360 만 넘으면 멀쩡하다고 보던 예전 기준이 이것을 통과시켰다.
    """
    user32 = _Placed((60, 40, 1160, 840), on_monitor=True)  # 1100×800 — 작업 영역 1920×1040 보다 작다

    BrowserWorker._send_window_to_back(user32, 1)

    (name, args), = user32.calls
    hwnd, insert_after, left, top, width, height, flags = args
    assert name == "SetWindowPos" and hwnd == 1 and insert_after == 1  # HWND_BOTTOM
    assert (left, top, width, height) == (0, 0, 1920, 1040)
    assert flags & 0x0010, "SWP_NOACTIVATE — 크기를 고치려고 앞창을 뺏으면 안 된다"
    assert not flags & 0x0001 and not flags & 0x0002, "크기·위치를 실제로 줘야 한다"


def test_a_window_already_filling_the_work_area_is_left_alone() -> None:
    """작업 영역을 이미 덮은 창은 다시 밀어 넣지 않는다 — 매 판 같은 값을 쓰면 헛일이다."""
    user32 = _Placed((0, 0, 1920, 1040), on_monitor=True)
    BrowserWorker._send_window_to_back(user32, 1)
    flags = user32.calls[0][1][-1]
    assert flags & 0x0001 and flags & 0x0002
