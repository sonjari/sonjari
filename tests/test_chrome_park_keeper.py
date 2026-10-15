"""화면 밖에 둔 크롬은 **사람이 부를 때만** 화면 안으로 (2026-09-24 부산 노트북).

사람이 노트북을 쓰는 중이면 「1초 안에 입력이 있었나」는 늘 참이라, 크롬이 혼자 앞을 쥘 때마다 화면 전체로 끌려 나왔다
(40초 중 20초 보임). 새벽 측정은 아무도 안 만지는 노트북이라 못 봤다. 이제 입력이 **어디서** 왔는지를 본다.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from alture_jarvis.agent import _final_answer_thinks
from alture_jarvis.browser import BrowserWorker


class _User32:
    """커서 아래 창과 키 상태만 흉내 낸다."""

    def __init__(self, under: int, *, alt_down: bool = False, fg: int = 0, zoomed: bool = False) -> None:
        self.under = under
        self.alt_down = alt_down
        self.fg = fg
        self.zoomed = zoomed
        self.moves: list[tuple] = []

    def GetAsyncKeyState(self, key):  # noqa: N802
        return 0x8000 if key == 0x12 and self.alt_down else 0

    def GetCursorPos(self, _ref):  # noqa: N802
        return 1

    def WindowFromPoint(self, _point):  # noqa: N802
        return self.under

    def GetAncestor(self, hwnd, _flag):  # noqa: N802
        return hwnd

    def GetForegroundWindow(self):  # noqa: N802
        return self.fg

    def IsZoomed(self, _hwnd):  # noqa: N802
        return self.zoomed

    def GetSystemMetrics(self, index):  # noqa: N802
        return {76: 0, 77: 0, 78: 1920, 16: 1920, 17: 1100}.get(index, 0)

    def SetWindowPos(self, *args):  # noqa: N802
        self.moves.append(args)
        return 1


CLASSES = {10: "Shell_TrayWnd", 11: "XamlExplorerHostIslandWindow", 20: "Chrome_WidgetWin_1", 30: "Ontelic"}


@pytest.fixture(autouse=True)
def _classes(monkeypatch):
    monkeypatch.setattr(BrowserWorker, "_window_class", staticmethod(lambda hwnd: CLASSES.get(int(hwnd), "")))
    BrowserWorker._human_shown = set()
    yield
    BrowserWorker._human_shown = set()
    BrowserWorker._park_offscreen = False


def _recent_input(monkeypatch, recent: bool) -> None:
    monkeypatch.setattr(BrowserWorker, "_user_input_within", staticmethod(lambda _seconds: recent))


def test_a_taskbar_click_is_a_summon():
    now = time.time()
    assert BrowserWorker._human_summoned(_User32(under=10), alt_seen_at=0.0, click_seen_at=now - 0.2, click_class="Shell_TrayWnd")
    assert BrowserWorker._human_summoned(_User32(under=11), alt_seen_at=0.0, click_seen_at=now - 0.2,
                                         click_class="XamlExplorerHostIslandWindow")  # 작업 표시줄 미리보기


def test_using_the_pc_elsewhere_is_not_a_summon():
    """★ 사람이 온텔릭 창에서 마우스를 쓰는 중에 크롬이 혼자 앞을 쥐었다 — 부른 게 아니다."""
    assert not BrowserWorker._human_summoned(_User32(under=30), alt_seen_at=0.0, click_seen_at=time.time() - 0.2, click_class="Ontelic")


def test_no_recent_click_is_not_a_summon():
    assert not BrowserWorker._human_summoned(_User32(under=10), alt_seen_at=0.0, click_seen_at=time.time() - 5.0, click_class="Shell_TrayWnd")


def test_typing_with_the_cursor_resting_on_the_taskbar_is_not_a_summon():
    """★ 2026-09-26: 작업 표시줄에서 클로드를 켠 뒤 커서를 거기 둔 채 채팅하면 「불렀다」가 됐다(크롬 20초 노출). 클릭이 없으면 아니다."""
    assert not BrowserWorker._human_summoned(_User32(under=10), alt_seen_at=0.0)


def test_alt_tab_is_a_summon(monkeypatch):
    """Alt+Tab 은 Alt 를 **뗄 때** 창이 바뀐다 — 감시가 Alt 를 본 시각으로 판단한다."""
    _recent_input(monkeypatch, True)
    assert BrowserWorker._human_summoned(_User32(under=30), alt_seen_at=time.time() - 0.2)
    assert not BrowserWorker._human_summoned(_User32(under=30), alt_seen_at=time.time() - 5.0)


def test_parking_never_spreads_a_window_over_the_screen():
    """★ 치우기를 못 한 창(앞창)을 옛 규칙이 작업 영역 전체로 폈다 — 「화면 전체 크롬」. 주차 중에는 순서만 바꾼다."""
    BrowserWorker._park_offscreen = True
    user32 = _User32(under=0, fg=4242)
    BrowserWorker._send_window_to_back(user32, 4242)
    assert user32.moves, "아무것도 안 했다"
    flags = user32.moves[-1][-1]
    assert flags & 0x0001 and flags & 0x0002, f"자리·크기를 바꿨다: {user32.moves[-1]}"


def test_a_window_the_human_called_is_left_where_it_is():
    BrowserWorker._park_offscreen = True
    BrowserWorker._human_shown = {4242}
    user32 = _User32(under=0, fg=0)
    assert BrowserWorker._park_window_offscreen(user32, 4242) is False
    BrowserWorker._send_window_to_back(user32, 4242)
    flags = user32.moves[-1][-1]
    assert flags & 0x0001 and flags & 0x0002


def test_a_window_nobody_called_is_parked_offscreen():
    BrowserWorker._park_offscreen = True
    user32 = _User32(under=0, fg=0)
    assert BrowserWorker._park_window_offscreen(user32, 4242) is True
    left = user32.moves[-1][2]
    assert left >= 1920, "화면 밖이 아니다"


def test_the_keeper_also_starts_when_we_attach_to_our_own_chrome():
    """백엔드만 다시 켜진 판(업데이트)은 크롬을 새로 안 띄운다 — 감시가 붙기에서도 서야 한다."""
    import inspect

    source = inspect.getsource(BrowserWorker)
    attach = source[source.index("self._park_existing_windows()\n"):][:400]
    assert "_start_park_rescue()" in attach


def _config(policy: str, enabled: bool = True):
    return SimpleNamespace(agent_thinking_enabled=enabled, agent_thinking_policy=policy)


def test_fast_thinking_level_turns_off_the_final_answer_thinking_too():
    """「빠르게」를 골라도 마무리 답에서 생각을 다 했다 — 마무리 답도 정책을 따른다."""
    assert _final_answer_thinks(_config("always"))
    assert _final_answer_thinks(_config("adaptive"))
    assert not _final_answer_thinks(_config("off"))
    assert not _final_answer_thinks(_config("always", enabled=False))


def test_balanced_level_keeps_thinking_short():
    from alture_jarvis.ollama import OllamaClient

    client = OllamaClient.__new__(OllamaClient)
    client.config = SimpleNamespace(ollama_thinking_char_budget=8000, ollama_thinking_budget_by_model={"qwen3.6": 3000},
                                    agent_thinking_policy="adaptive")
    assert client._thinking_budget_for("qwen3.5:4b") == 2500
    client.config.agent_thinking_policy = "always"
    assert client._thinking_budget_for("qwen3.5:4b") == 8000
    assert client._thinking_budget_for("qwen3.6:35b-a3b") == 3000



class _Keys:
    def __init__(self, *down: int) -> None:
        self.down = set(down)

    def GetAsyncKeyState(self, key: int) -> int:  # noqa: N802 — user32 이름 그대로
        return 0x8000 if key in self.down else 0


def test_the_hangul_key_is_not_a_summon() -> None:
    """한국 노트북의 한/영 = 오른쪽 Alt. 채팅하며 한/영을 누를 때마다 크롬을 부른 것으로 읽었다(2026-09-26)."""
    from alture_jarvis.browser import _alt_tab_held

    assert not _alt_tab_held(_Keys(0xA5)), "오른쪽 Alt(한/영)"
    assert not _alt_tab_held(_Keys(0x12, 0xA5)), "VK_MENU 가 같이 켜져도 오른쪽 Alt 면 아니다"
    assert not _alt_tab_held(_Keys(0xA4)), "왼쪽 Alt 단독도 아니다"
    assert _alt_tab_held(_Keys(0xA4, 0x09)), "왼쪽 Alt + Tab 은 사람이 창을 부르는 것이다"



def test_parked_chrome_is_muted_and_does_not_autoplay():
    """가림 판정을 끄자 화면 밖 크롬이 검색 결과의 영상 미리보기를 자동 재생했다(2026-09-26 노트북) — 소리·재생을 막는다."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py").read_text(encoding="utf-8")
    block = source[source.index('arguments.append("--disable-backgrounding-occluded-windows")'):][:900]
    assert '"--mute-audio"' in block and '"--autoplay-policy=user-gesture-required"' in block


def test_parked_chrome_starts_without_a_window_so_nothing_is_activated():
    """첫 창이 앞창을 가져가는 게 콜드스타트 줄다리기의 뿌리였다 — 창 없이 띄우고 첫 창은 CDP 로 뒤쪽·화면 밖에(2026-09-26)."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py").read_text(encoding="utf-8")
    block = source[source.index('arguments.append("--disable-backgrounding-occluded-windows")'):][:1500]
    assert '"--no-startup-window"' in block
    opener = source[source.index("def _open_first_window_background"):][:2500]
    assert '"newWindow": True' in opener and '"background": True' in opener
    assert "_open_first_window_background(info)" in source, "포트가 열린 뒤 붙기 전에 불러야 한다"
