"""콜드스타트에서 크롬이 **한 프레임도 안 번쩍이게** 되살린다 (2026-09-21, 사장님 지적).

> 전용 크롬이 떠 있으면 안 번쩍거리는데 콜드스타트할 때 번쩍거려. 이걸 테스트의 자로 잡아야 돼.

## 무엇이 번쩍였나

띄울 때 크롬을 최소화해 두었다가 다 뜨면 `ShowWindow(SW_SHOWNOACTIVATE)` 로 되살려 맨 뒤로 보낸다.
`ShowWindow` 가 **막 태어난 창을 맨 위에 세우고**, 다음 줄이 맨 뒤로 내리기까지 10~42ms 동안 다른 창
위에 그려졌다. 측정(`bench/browser_agents/measure_chrome_flash.py`, 희생양 창 + 콜드스타트):

    이전(예전 복원)   8/8 번쩍임 (10~42ms) · 별도 프로세스 5/5 · 화면 픽셀에도 2/5 잡힘
    이후(투명 복원)   0/8 · 0/5 · 화면 픽셀 0/5   (z 순서상 34~49ms 위에 서지만 **알파 0** 이라 안 보인다)

## 어떻게 고쳤나 — 되살리는 동안만 투명하게

`WS_EX_LAYERED` + 알파 0 → 되살림 → 맨 뒤 → 불투명 복구. 알파 0 이 크롬(DirectComposition)에서 실제로
투명한지는 **화면 픽셀로 확인했다**(크롬을 맨 위에 올린 채: 불투명 (238,238,238) → 알파 0 (34,34,51)=뒤의 색 → 복구 (238,…)).

## 해 봤는데 안 된 것 (다시 시도하지 말 것)

- 화면 밖에서 되살리기(`SetWindowPlacement`): 윈도우가 자리를 **가장 가까운 모니터 안으로 끌어온다**.
- DWM 클로킹: 남의 프로세스 창에는 `E_ACCESSDENIED`.
- 인수인계서의 「되살린 2.4초 뒤에 번쩍」은 **시계가 어긋난 해석**이었다(`restored_at` 은 감시 스레드 기준).
"""

from __future__ import annotations

import inspect
from typing import Any

from alture_jarvis.browser import BrowserWorker

_LAYERED = 0x80000


class _Win:
    """Win32 를 흉내 내는 가짜. 부른 순서와 창의 확장 스타일 변화를 기록한다."""

    def __init__(self, *, ex_style: int = 0x200100, layered_ok: bool = True,
                 show_raises: bool = False) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.ex_style = ex_style
        self.layered_ok = layered_ok
        self.show_raises = show_raises
        self._raised = False

    def GetWindowLongW(self, hwnd: int, index: int) -> int:  # noqa: N802
        self.calls.append(("GetWindowLongW", (hwnd, index)))
        return self.ex_style

    def SetWindowLongW(self, hwnd: int, index: int, value: int) -> int:  # noqa: N802
        self.calls.append(("SetWindowLongW", (hwnd, index, value)))
        self.ex_style = value
        return 1

    def SetLayeredWindowAttributes(self, hwnd: int, key: int, alpha: int, flags: int) -> int:  # noqa: N802
        self.calls.append(("SetLayeredWindowAttributes", (hwnd, key, alpha, flags)))
        return 1 if self.layered_ok else 0

    def ShowWindow(self, hwnd: int, command: int) -> int:  # noqa: N802
        self.calls.append(("ShowWindow", (hwnd, command)))
        if self.show_raises and not self._raised:
            self._raised = True
            raise OSError("boom")
        return 1

    def SetWindowPos(self, *args: Any) -> int:  # noqa: N802
        self.calls.append(("SetWindowPos", args))
        return 1

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def alphas(self) -> list[int]:
        return [args[2] for name, args in self.calls if name == "SetLayeredWindowAttributes"]


def test_the_window_is_transparent_while_it_is_brought_back_and_opaque_after() -> None:
    win = _Win()

    BrowserWorker._restore_quietly(win, 4242)

    assert win.alphas() == [0, 255], "투명하게 만들고, 끝나면 불투명으로 되돌려야 한다"
    names = win.names()
    first_alpha = names.index("SetLayeredWindowAttributes")
    show = names.index("ShowWindow")
    pos = names.index("SetWindowPos")
    last_alpha = len(names) - 1 - names[::-1].index("SetLayeredWindowAttributes")
    # ★ 투명해진 **뒤에** 되살리고, 맨 뒤로 보낸 **뒤에** 불투명으로 — 순서가 곧 「안 번쩍임」이다.
    assert first_alpha < show < pos < last_alpha
    assert ("ShowWindow", (4242, 4)) in win.calls, "활성화 없이(SW_SHOWNOACTIVATE) 되살려야 한다"
    hwnd, insert_after, *_rest, flags = next(args for name, args in win.calls if name == "SetWindowPos")
    assert hwnd == 4242 and insert_after == 1, "HWND_BOTTOM"
    assert flags & 0x10, "SWP_NOACTIVATE 가 빠지면 앞창을 뺏는다"
    assert BrowserWorker._last_restore_path == "transparent"


def test_the_extended_style_is_restored_so_the_window_is_not_left_layered() -> None:
    win = _Win(ex_style=0x200100)

    BrowserWorker._restore_quietly(win, 1)

    assert win.ex_style == 0x200100, "레이어드가 남으면 크롬 창이 영영 투명 상태로 남을 수 있다"


def test_a_window_that_was_already_layered_keeps_its_style() -> None:
    """이미 레이어드인 창의 스타일을 우리가 벗기면 그 창의 원래 동작이 깨진다."""
    win = _Win(ex_style=0x200100 | _LAYERED)

    BrowserWorker._restore_quietly(win, 1)

    assert win.ex_style & _LAYERED, "원래 레이어드였으면 그대로 둔다"
    assert not any(name == "SetWindowLongW" for name in win.names()), "이미 켜져 있는 것을 다시 쓰지 않는다"


def test_when_transparency_is_refused_it_falls_back_and_says_so() -> None:
    """크롬이 레이어드를 거부하는 환경에서도 창은 되살아나야 한다 — 그리고 폴백을 **조용히 넘기지 않는다**."""
    win = _Win(layered_ok=False)

    BrowserWorker._restore_quietly(win, 7)

    assert ("ShowWindow", (7, 4)) in win.calls, "예전 길로라도 되살려야 한다"
    assert win.ex_style == 0x200100, "실패했으면 켜 둔 레이어드 스타일을 되돌린다"
    assert BrowserWorker._last_restore_path.startswith("fallback:"), (
        "폴백이 조용히 옛 번쩍임을 되살리면 눈금은 「안 고쳐졌다」만 말한다"
    )


def test_opacity_is_restored_even_when_bringing_the_window_back_fails() -> None:
    """되살리다 예외가 나도 알파 0 인 채로 남으면 안 된다 — 안 보이는 크롬은 사고다."""
    win = _Win(show_raises=True)

    BrowserWorker._restore_quietly(win, 9)

    assert 255 in win.alphas(), "예외가 나도 finally 로 불투명을 되돌려야 한다"
    assert win.ex_style == 0x200100


def test_all_three_restore_sites_use_the_quiet_path() -> None:
    """만들어 놓고 부르는 자리가 없으면 아무 일도 안 일어난다(이 저장소가 여러 번 겪은 모양)."""
    for site in (BrowserWorker._restore_sunk_windows, BrowserWorker._give_focus_back,
                 BrowserWorker._present_for_human):
        assert "_restore_quietly(" in inspect.getsource(site), site.__qualname__

    # 날것의 SW_SHOWNOACTIVATE 복원이 다른 곳에 남아 있으면 그 자리가 다시 번쩍인다.
    source = inspect.getsource(BrowserWorker)
    quiet = inspect.getsource(BrowserWorker._restore_quietly)
    assert source.count("ShowWindow(hwnd, 4)") == quiet.count("ShowWindow(hwnd, 4)"), (
        "`_restore_quietly` 밖에 ShowWindow(hwnd, 4) 가 남았다"
    )


def test_the_flash_ruler_counts_what_a_person_can_see_not_just_z_order() -> None:
    """눈금이 「z 순서상 위」만 세면 투명하게 되살린 것도 번쩍임으로 센다(그리고 그 반대의 거짓 안심도 막는다).

    실측: 이전 8/8 · 이후 0/8 (보이는 것), z 순서만 세면 이후도 5/8. 두 숫자를 다 남긴다.
    """
    from pathlib import Path

    ruler = (Path(__file__).parent.parent / "bench" / "browser_agents" / "measure_chrome_flash.py").read_text(
        encoding="utf-8")
    assert "over_any_z_ms" in ruler, "z 순서 기준 숫자도 남겨서 두 숫자를 같이 보여 줘야 한다"
    assert "_layered_alpha" in ruler
    assert "INJECT_FLASH" in ruler, "양성 대조(진짜 번쩍임을 잡는가)가 없는 눈금은 0 이 「못 본다」일 수 있다"
    assert "valid_run" in ruler, "희생양이 최소화된 판은 무효로 걸러야 한다"
