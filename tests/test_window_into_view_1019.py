"""화면 밖 창을 주 모니터로 데려오고, 못 하면 까닭을 정확히 말한다 (2026-10-19 판 ae395490 뒤).

그 판에서 모델은 Claude 앱 창 좌표 -1928 을 보고 「화면 왼쪽 밖」이라 짐작했다. 기록을 다시 보니 창은 **왼쪽 보조 모니터에
최대화**돼 있었고(-1928,-8 은 최대화 여백), 캡처에도 앱이 그대로 찍혀 있었다. 그래서 여기서 지키는 것:

1. 정말 화면 밖(꺼진 · 뽑힌 모니터 자리)이면 주 모니터 작업 영역으로 옮긴다 — 크기가 맞으면 그대로, 크면 맞춘다
2. **다른 모니터에 제대로 떠 있는 창 · 반 넘게 보이는 창은 건드리지 않는다**
3. 최소화된 창은 옮기지 않고 펼친다(-32000 좌표를 「화면 밖」으로 착각하지 않는다)
4. 앞으로 가져오기 · 비전 좌표가 실패하면 「창은 어디 있다 — 위치 문제가 아니다」를 문장에 담는다
5. 창을 옮기는 것은 L1 걸음(앞으로 가져오기 · 미리보기)에서만 — 읽기(L0)에서는 하지 않는다
"""

from __future__ import annotations

import ctypes as real_ctypes
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import window_view
from alture_jarvis.config import JarvisConfig
from alture_jarvis.models import RiskLevel
from alture_jarvis.window_view import Monitor, Rect, bring_into_view, plan_into_view, visible_fraction, where

PRIMARY = Monitor(Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1032), True)
LEFT = Monitor(Rect(-1920, 0, 0, 1080), Rect(-1920, 0, 0, 1032), False)
#: ae395490 의 Claude 창 — 왼쪽 모니터에 최대화(가장자리 8px 씩 넘친다).
INCIDENT_RECT = Rect(-1928, -8, 8, 1040)


class FakeDesk:
    def __init__(
        self,
        monitors: list[Monitor],
        rect: Rect,
        *,
        minimized: bool = False,
        maximized: bool = False,
        restored_rect: Rect | None = None,
        restores: bool = True,
        movable: bool = True,
    ) -> None:
        self._monitors = monitors
        self._rect = rect
        self._minimized = minimized
        self._maximized = maximized
        self._restored_rect = restored_rect
        self._restores = restores
        self._movable = movable
        self.calls: list[Any] = []

    def monitors(self) -> list[Monitor]:
        return list(self._monitors)

    def rect(self, hwnd: int) -> Rect:
        return Rect(-32000, -32000, -31840, -31972) if self._minimized else self._rect

    def is_minimized(self, hwnd: int) -> bool:
        return self._minimized

    def is_maximized(self, hwnd: int) -> bool:
        return self._maximized

    def restore(self, hwnd: int) -> None:
        self.calls.append("restore")
        if not self._restores:
            return
        if self._minimized:
            self._minimized = False
        elif self._maximized:
            self._maximized = False
        if self._restored_rect is not None:
            self._rect = self._restored_rect

    def move(self, hwnd: int, rect: Rect) -> bool:
        self.calls.append(("move", rect))
        if self._movable:
            self._rect = rect
        return self._movable

    @property
    def moves(self) -> list[Rect]:
        return [call[1] for call in self.calls if isinstance(call, tuple)]


# ── 좌표 계산 ────────────────────────────────────────────────────────────────
def test_the_incident_window_was_on_the_left_monitor_and_is_left_alone() -> None:
    """ae395490 의 창은 화면 밖이 아니었다 — 보조 모니터 위에 98% 가 있다. 옮기지 않고, 어디 있는지 말한다."""
    monitors = [LEFT, PRIMARY]
    assert visible_fraction(INCIDENT_RECT, monitors) > 0.95
    assert plan_into_view(INCIDENT_RECT, monitors) is None
    assert where(INCIDENT_RECT, monitors) == "보조 모니터 1(-1920,0~0,1080) 안"
    desk = FakeDesk(monitors, INCIDENT_RECT, maximized=True)
    assert bring_into_view(1, desk, settle_sec=0) == {}
    assert desk.calls == []


def test_a_window_left_of_the_desktop_moves_onto_the_primary_work_area_with_its_size() -> None:
    rect = Rect(-1800, 100, -800, 800)  # 1000x700, 어느 모니터에도 없다
    desk = FakeDesk([PRIMARY], rect)
    view = bring_into_view(1, desk, settle_sec=0)
    assert desk.moves == [Rect(460, 166, 1460, 866)]  # 작업 영역(1920x1032) 가운데, 크기 그대로
    assert view["moved_into_view"]["from"] == rect.as_dict()
    assert view["moved_into_view"]["to"] == Rect(460, 166, 1460, 866).as_dict()
    assert "resized_to_fit" not in view["moved_into_view"]
    assert view["note"] == "창이 화면 밖(-1800,100)에 있어 주 모니터로 옮겼습니다."


def test_a_maximized_window_on_an_unplugged_monitor_is_unmaximized_then_moved() -> None:
    """같은 -1928 창이라도 그 모니터가 뽑혔으면 진짜 화면 밖이다. 최대화를 풀고, 풀린 크기로 옮긴다."""
    desk = FakeDesk([PRIMARY], INCIDENT_RECT, maximized=True, restored_rect=Rect(-1700, 100, -500, 900))
    assert where(INCIDENT_RECT, [PRIMARY]) == "화면 밖(-1928,-8)"
    view = bring_into_view(1, desk, settle_sec=0)
    assert desk.calls[0] == "restore"
    assert desk.moves == [Rect(360, 116, 1560, 916)]
    assert view["note"].startswith("창이 화면 밖(-1928,-8)에 있어 주 모니터로 옮겼습니다")


def test_a_window_bigger_than_the_screen_is_fitted_to_the_work_area() -> None:
    desk = FakeDesk([PRIMARY], Rect(-2600, 0, -200, 1300))  # 2400x1300
    view = bring_into_view(1, desk, settle_sec=0)
    assert desk.moves == [Rect(0, 0, 1920, 1032)]
    assert view["moved_into_view"]["resized_to_fit"] is True
    assert "크기를 맞췄습니다" in view["note"]


def test_a_minimized_window_is_restored_not_moved() -> None:
    """최소화 좌표(-32000)를 화면 밖으로 읽고 옮기면 펼쳐진 뒤 엉뚱한 자리에 간다."""
    desk = FakeDesk([LEFT, PRIMARY], Rect(0, 0, 0, 0), minimized=True, restored_rect=Rect(100, 100, 900, 700))
    view = bring_into_view(1, desk, settle_sec=0)
    assert desk.calls == ["restore"]
    assert view == {"restored": True, "note": "창이 최소화돼 있어 펼쳤습니다."}


def test_a_minimized_window_that_will_not_restore_is_not_moved() -> None:
    desk = FakeDesk([PRIMARY], Rect(0, 0, 0, 0), minimized=True, restores=False)
    view = bring_into_view(1, desk, settle_sec=0)
    assert desk.moves == []
    assert view["still_minimized"] is True


def test_a_minimized_window_restored_off_screen_is_then_moved() -> None:
    desk = FakeDesk([PRIMARY], Rect(0, 0, 0, 0), minimized=True, restored_rect=Rect(-1500, 200, -700, 800))
    view = bring_into_view(1, desk, settle_sec=0)
    assert view["restored"] is True and desk.moves
    assert view["note"] == "창이 최소화돼 있어 펼쳤습니다. 창이 화면 밖(-1500,200)에 있어 주 모니터로 옮겼습니다."


def test_a_mostly_visible_window_is_left_where_the_person_put_it() -> None:
    mostly = Rect(-300, 100, 700, 800)  # 70% 가 주 모니터 위
    assert plan_into_view(mostly, [PRIMARY]) is None
    desk = FakeDesk([PRIMARY], mostly)
    assert bring_into_view(1, desk, settle_sec=0) == {}
    # 기준선 반대쪽: 30% 만 보이면 옮긴다
    assert plan_into_view(Rect(-700, 100, 300, 800), [PRIMARY]) is not None


def test_a_window_on_a_second_active_monitor_is_not_touched() -> None:
    rect = Rect(-1500, 100, -500, 800)
    desk = FakeDesk([LEFT, PRIMARY], rect)
    assert bring_into_view(1, desk, settle_sec=0) == {}
    assert desk.calls == []
    # 오른쪽 · 위에 둔 모니터도 같다
    right = Monitor(Rect(1920, -200, 4480, 1240), Rect(1920, -200, 4480, 1200), False)
    assert plan_into_view(Rect(2000, -100, 3000, 600), [PRIMARY, right]) is None


def test_a_window_spanning_two_monitors_counts_both() -> None:
    assert visible_fraction(Rect(-500, 0, 500, 500), [LEFT, PRIMARY]) == 1.0


def test_a_move_that_did_not_take_is_reported_not_claimed() -> None:
    desk = FakeDesk([PRIMARY], Rect(-1800, 100, -800, 800), movable=False)
    view = bring_into_view(1, desk, settle_sec=0)
    assert view["still_off_screen"] is True and "moved_into_view" not in view
    assert "옮겨지지 않았습니다" in view["note"]


def test_no_monitor_information_means_no_move() -> None:
    assert plan_into_view(Rect(-1800, 100, -800, 800), []) is None


# ── 창 앞으로 가져오기(L1) ─────────────────────────────────────────────────────
class _FakeUser32:
    def __init__(self, *, foreground_ok: bool) -> None:
        self.foreground_ok = foreground_ok
        self.shown: list[tuple[int, int]] = []

    def IsWindow(self, hwnd: int) -> int:  # noqa: N802 — user32 이름 그대로
        return 1

    def GetWindowTextLengthW(self, hwnd: int) -> int:  # noqa: N802
        return 6

    def GetWindowTextW(self, hwnd: int, buffer: Any, size: int) -> int:  # noqa: N802
        buffer.value = "Claude"
        return 6

    def IsIconic(self, hwnd: int) -> int:  # noqa: N802
        return 0

    def ShowWindow(self, hwnd: int, command: int) -> int:  # noqa: N802
        self.shown.append((hwnd, command))
        return 1

    def SetForegroundWindow(self, hwnd: int) -> int:  # noqa: N802
        self._front = hwnd if self.foreground_ok else 0
        return self._front

    def GetForegroundWindow(self) -> int:  # noqa: N802
        return self._front


def _local_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, desk: FakeDesk, *, foreground_ok: bool):
    if os.name != "nt":
        pytest.skip("윈도우 전용 손")
    from alture_jarvis import local_computer
    from alture_jarvis.user_presence import UserPresence

    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(user32=_FakeUser32(foreground_ok=foreground_ok)),
                                  create_unicode_buffer=real_ctypes.create_unicode_buffer)
    monkeypatch.setattr(local_computer, "ctypes", fake_ctypes)
    monkeypatch.setattr(window_view, "desktop", lambda: desk)
    monkeypatch.setattr(UserPresence, "wait_until_idle", lambda self, **kw: True)
    monkeypatch.setattr(window_view.time, "sleep", lambda _s: None)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")
    return local_computer.LocalComputerTools(config)


def test_focus_brings_an_off_screen_window_in_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desk = FakeDesk([PRIMARY], INCIDENT_RECT, restored_rect=None)
    tools = _local_tools(tmp_path, monkeypatch, desk, foreground_ok=True)
    result = tools.focus_window({"window_id": 48959036})
    assert result["action"] == "windows_focus_window"
    assert result["moved_into_view"]["from"] == INCIDENT_RECT.as_dict()
    assert result["note"].startswith("창이 화면 밖(-1928,-8)에 있어 주 모니터로 옮겼습니다")


def test_focus_failure_on_a_visible_window_says_it_is_not_a_position_problem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ae395490 그대로: 창은 왼쪽 모니터에 있고, 윈도우가 앞으로 가져오기를 막았다. 모델이 「화면 밖」을 짐작하지 않게."""
    desk = FakeDesk([LEFT, PRIMARY], INCIDENT_RECT, maximized=True)
    tools = _local_tools(tmp_path, monkeypatch, desk, foreground_ok=False)
    with pytest.raises(RuntimeError) as caught:
        tools.focus_window({"window_id": 48959036})
    message = str(caught.value)
    assert message.startswith("window_focus_failed: 창은 보조 모니터 1(-1920,0~0,1080) 안에 있습니다")
    assert "위치 문제가 아니라" in message and "windows_execute_preview" in message
    assert desk.calls == []  # 잘 보이는 창은 옮기지 않았다
    # 같은 창이면 같은 문장 — 같은 실패 되풀이를 세는 열쇠가 문장 전체다
    with pytest.raises(RuntimeError) as again:
        tools.focus_window({"window_id": 48959036})
    assert str(again.value) == message


def test_focus_on_a_window_that_cannot_be_moved_names_the_off_screen_cause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desk = FakeDesk([PRIMARY], Rect(-1800, 100, -800, 800), movable=False)
    tools = _local_tools(tmp_path, monkeypatch, desk, foreground_ok=True)
    with pytest.raises(RuntimeError, match=r"^window_off_screen: 창이 화면 밖\(-1800,100\)"):
        tools.focus_window({"window_id": 7})


def test_the_window_list_marks_only_off_screen_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """목록은 읽기(L0)다 — 표시만 달고 옮기지 않는다."""
    if os.name != "nt":
        pytest.skip("윈도우 전용 손")
    from alture_jarvis import local_computer

    rects = {11: Rect(100, 100, 900, 700), 12: Rect(-1800, 100, -800, 800), 13: INCIDENT_RECT}

    class _ListDesk(FakeDesk):
        def rect(self, hwnd: int) -> Rect:
            return rects[hwnd]

    desk = _ListDesk([PRIMARY], Rect(0, 0, 0, 0))
    monkeypatch.setattr(window_view, "desktop", lambda: desk)

    class _ListUser32(_FakeUser32):
        def EnumWindows(self, callback: Any, _data: int) -> int:  # noqa: N802
            for hwnd in rects:
                callback(hwnd, 0)
            return 1

        def IsWindowVisible(self, hwnd: int) -> int:  # noqa: N802
            return 1

        def GetWindowThreadProcessId(self, hwnd: int, out: Any) -> int:  # noqa: N802
            return 1

    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(user32=_ListUser32(foreground_ok=True)),
                                  create_unicode_buffer=real_ctypes.create_unicode_buffer,
                                  WINFUNCTYPE=lambda *a: (lambda fn: fn), c_bool=None, c_void_p=None,
                                  byref=lambda value: value)
    monkeypatch.setattr(local_computer, "ctypes", fake_ctypes)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")
    windows = {row["window_id"]: row for row in local_computer.LocalComputerTools(config).list_open_windows({})["windows"]}
    assert "off_screen" not in windows[11]
    assert windows[12]["off_screen"] is True and windows[12]["where"] == "화면 밖(-1800,100)"
    assert windows[13]["where"] == "화면 밖(-1928,-8)"  # 이 배치(주 모니터 하나)에서는 진짜 밖이다
    assert desk.calls == []


# ── 미리보기(L1) · 스냅샷(L0) ─────────────────────────────────────────────────
def _automation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, desk: FakeDesk, planner: Any = None):
    from alture_jarvis import windows_automation
    from alture_jarvis.windows_automation import WindowsAutomationTools

    tools = WindowsAutomationTools(
        JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"),
        visual_planner=planner,
    )
    monkeypatch.setattr(window_view, "desktop", lambda: desk)
    monkeypatch.setattr(window_view.time, "sleep", lambda _s: None)
    monkeypatch.setattr(windows_automation.time, "sleep", lambda _s: None)
    monkeypatch.setattr(tools.presence, "wait_until_idle", lambda **kw: True)
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"png")
    monkeypatch.setattr(tools, "_capture_window",
                        lambda window_id, prefix: (shot, {"left": 0, "top": 0, "right": 1936, "bottom": 1048}))
    return tools


def test_a_visual_miss_is_called_a_vision_miss_not_an_off_screen_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ae395490 5 · 19걸음: 비전이 그림 밖 좌표를 줬고, 모델은 그것을 「창이 화면 밖」의 증거로 읽었다."""
    desk = FakeDesk([LEFT, PRIMARY], INCIDENT_RECT, maximized=True)
    tools = _automation(tmp_path, monkeypatch, desk, planner=lambda *_a: {"x": 2400, "y": 30, "confidence": 0.9})
    with pytest.raises(RuntimeError) as caught:
        tools.visual_preview({"window_id": 48959036, "instruction": "설정 버튼"})
    message = str(caught.value)
    assert message.startswith("visual_coordinate_out_of_bounds: 비전이 고른 자리가 창 그림(1936x1048) 밖입니다")
    assert "보조 모니터 1(-1920,0~0,1080) 안" in message and "창 위치 문제가 아니라" in message
    assert "2400" not in message  # 부를 때마다 바뀌는 숫자는 문장에 없다
    assert desk.calls == []


def test_a_visual_preview_brings_an_off_screen_window_in_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desk = FakeDesk([PRIMARY], Rect(-1800, 100, -800, 800))
    tools = _automation(tmp_path, monkeypatch, desk, planner=lambda *_a: {"x": 50, "y": 40, "confidence": 0.9})
    result = tools.visual_preview({"window_id": 5, "instruction": "설정 버튼"})
    assert desk.moves and result["moved_into_view"]["to"]["left"] == 460
    assert result["note"] == "창이 화면 밖(-1800,100)에 있어 주 모니터로 옮겼습니다."
    assert result["requires_approval"] is True  # 클릭 자체는 여전히 승인 뒤에


def test_a_uia_preview_restores_a_minimized_window_before_capturing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 기록에서 최소화된 엑셀 · 메모장 창이 `window_not_visible` 로 다섯 걸음을 버렸다."""
    desk = FakeDesk([PRIMARY], Rect(0, 0, 0, 0), minimized=True, restored_rect=Rect(100, 100, 900, 700))
    tools = _automation(tmp_path, monkeypatch, desk)
    result = tools.uia_preview({"window_id": 5, "action": "key", "value": "ctrl+s"})
    assert result["restored"] is True and desk.moves == []
    assert result["requires_approval"] is True


def test_a_minimized_window_that_will_not_open_is_named_not_called_invisible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desk = FakeDesk([PRIMARY], Rect(0, 0, 0, 0), minimized=True, restores=False)
    tools = _automation(tmp_path, monkeypatch, desk)
    with pytest.raises(RuntimeError, match=r"^window_minimized: 창이 최소화돼 있는데 펼치지 못해"):
        tools.uia_preview({"window_id": 5, "action": "key", "value": "ctrl+s"})
    assert desk.moves == []


def test_moving_waits_for_the_persons_hands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """옮긴 창은 사람이 쓰던 창 위로 올라온다 — 손이 안 멈추면 옮기지 않고 미룬다."""
    desk = FakeDesk([PRIMARY], Rect(-1800, 100, -800, 800))
    tools = _automation(tmp_path, monkeypatch, desk, planner=lambda *_a: {"x": 50, "y": 40, "confidence": 0.9})
    monkeypatch.setattr(tools.presence, "wait_until_idle", lambda **kw: False)
    with pytest.raises(RuntimeError, match="user_active_try_later"):
        tools.visual_preview({"window_id": 5, "instruction": "설정 버튼"})
    assert desk.calls == []


def test_a_visible_window_does_not_wait_for_hands_at_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desk = FakeDesk([PRIMARY], Rect(100, 100, 900, 700))
    tools = _automation(tmp_path, monkeypatch, desk, planner=lambda *_a: {"x": 50, "y": 40, "confidence": 0.9})
    monkeypatch.setattr(tools.presence, "wait_until_idle", lambda **kw: pytest.fail("잘 보이는 창인데 사람 손을 기다렸다"))
    result = tools.visual_preview({"window_id": 5, "instruction": "설정 버튼"})
    assert "moved_into_view" not in result and desk.calls == []


def test_the_snapshot_read_never_moves_a_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """읽기(L0)는 화면을 바꾸지 않는다 — 화면 밖 창이어도 스냅샷은 옮기지 않는다."""
    desk = FakeDesk([PRIMARY], Rect(-1800, 100, -800, 800))
    tools = _automation(tmp_path, monkeypatch, desk)

    class _Window:
        element_info = SimpleNamespace(name="Claude", control_type="Window", automation_id="", class_name="Chrome_WidgetWin_1",
                                       rectangle=SimpleNamespace(left=-1800, top=100, right=-800, bottom=800))

        def descendants(self) -> list[Any]:
            return []

        def get_properties(self) -> dict[str, Any]:
            return {}

        def window_text(self) -> str:
            return "Claude"

        def process_id(self) -> int:
            return os.getpid()

    monkeypatch.setattr(tools, "_window", lambda window_id: _Window())
    tools.uia_snapshot({"window_id": 5})
    assert desk.calls == []


def test_window_moving_hands_stay_l1_and_reads_stay_l0(tmp_path: Path) -> None:
    """창을 옮길 수 있는 걸음은 이미 창을 바꾸던 L1 걸음뿐이다. 승인 등급을 바꾸지 않았다(새 도구도 없다)."""
    from alture_jarvis.local_computer import LocalComputerTools
    from alture_jarvis.windows_automation import WindowsAutomationTools

    captured: dict[str, RiskLevel] = {}
    gateway = SimpleNamespace(register=lambda spec: captured.__setitem__(spec.name, spec.risk_level),
                              approval_describers={}, pre_approval_checks={})
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")
    LocalComputerTools(config).register(gateway)  # type: ignore[arg-type]
    WindowsAutomationTools(config).register(gateway)  # type: ignore[arg-type]
    assert captured["windows_focus_window"] == RiskLevel.L1
    assert captured["windows_uia_preview"] == RiskLevel.L1
    assert captured["windows_visual_preview"] == RiskLevel.L1
    assert captured["windows_list_open_windows"] == RiskLevel.L0
    assert captured["windows_uia_snapshot"] == RiskLevel.L0
    assert captured["windows_execute_preview"] == RiskLevel.L2  # 클릭 · 키 입력은 여전히 사람 승인
    assert "windows_bring_into_view" not in captured
