"""브라우저 무대 — 화면 밖 크롬을 온텔릭 창 안에서 보고 만진다 (2026-09-24 부산).

진짜 크롬에 붙인 확인은 스크래치 `probe_live_view.py` 로 했다(첫 장 0.06초 · 한글 입력·클릭·Enter 제출 · 크기 맞추기).
여기서는 그 뒤에서 깨지기 쉬운 규칙들을 못 박는다.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from alture_jarvis import live_view as lv
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.live_view import LiveView, _key_params


def _view() -> tuple[LiveView, list[tuple[str, dict]]]:
    worker = SimpleNamespace(_connected=True, _page=None, _cdp_port_in_use=9222, config=SimpleNamespace(browser_cdp_port=9222))
    view = LiveView(worker)
    sent: list[tuple[str, dict]] = []
    view._send = lambda method, params=None, **_: sent.append((method, params or {}))  # type: ignore[method-assign]
    view._ws = object()  # 연결된 무대 — 끊긴 무대의 입력은 not_connected 로 돌아간다
    view._frame = {"seq": 1, "jpeg": b"x", "css_width": 1280.0, "css_height": 800.0}
    return view, sent


def test_a_click_is_sent_in_page_css_pixels_and_takes_control():
    view, sent = _view()
    assert view.input({"kind": "mouse", "type": "down", "x": 0.5, "y": 0.25, "button": "left", "clickCount": 1})["ok"]
    assert view.human_in_control(), "누르는 순간이 곧 넘겨받기다"
    method, params = sent[-1]
    assert method == "Input.dispatchMouseEvent"
    assert params["type"] == "mousePressed" and params["x"] == 640 and params["y"] == 200


def test_korean_text_goes_in_as_committed_text():
    view, sent = _view()
    view.input({"kind": "text", "text": "부산 날씨"})
    assert sent[-1] == ("Input.insertText", {"text": "부산 날씨"})


def test_enter_carries_a_carriage_return_so_forms_submit():
    params = _key_params({"type": "down", "key": "Enter", "code": "Enter", "keyCode": 13}, 0)
    assert params["type"] == "keyDown" and params["text"] == "\r"
    assert _key_params({"type": "down", "key": "Backspace", "code": "Backspace", "keyCode": 8}, 0)["type"] == "rawKeyDown"


def test_edit_shortcuts_are_sent_as_commands():
    params = _key_params({"type": "down", "key": "a", "code": "KeyA", "keyCode": 65}, 2)
    assert params["commands"] == ["selectAll"]


def test_control_returns_by_itself_after_two_idle_minutes(monkeypatch):
    view, _sent = _view()
    view.take_control()
    view._control_last_input = time.time() - lv.CONTROL_IDLE_SEC - 1
    assert not view.human_in_control()
    assert view.control_state()["last_release"] == "idle"


def test_fit_never_narrows_chrome_below_a_desktop_layout():
    """좁히면 사이트가 태블릿 배치로 바뀌어 레시피가 어긋난다 — 폭은 하한 아래로 안 내리고 비율만 맞춘다."""
    view, _sent = _view()
    view._watch = lambda: None  # type: ignore[method-assign]
    wanted = view.fit(950, 800)["wanted"]
    assert wanted[0] == lv.FIT_MIN_WIDTH
    assert abs(wanted[1] / wanted[0] - 800 / 950) < 0.01


def test_the_agent_waits_while_a_human_holds_the_browser_and_is_told_afterwards():
    worker = BrowserWorker.__new__(BrowserWorker)
    view, _sent = _view()
    worker.live_view = view
    view.take_control()
    threading.Timer(0.6, lambda: view.release_control("button")).start()
    started = time.time()
    waited = worker._wait_while_human_controls()
    assert 0.4 < waited < 3 and time.time() - started >= 0.5
    result = worker._with_takeover_note({"ok": True})
    assert "human_took_over" in result, "돌려받은 뒤 첫 결과에 화면이 바뀌었을 수 있다고 알려야 한다"
    assert "human_took_over" not in worker._with_takeover_note({"ok": True}), "알림은 한 번만"


def test_nothing_waits_when_nobody_took_over():
    worker = BrowserWorker.__new__(BrowserWorker)
    view, _sent = _view()
    worker.live_view = view
    assert worker._wait_while_human_controls() == 0.0


def test_an_old_chrome_without_the_occlusion_flag_is_restarted(monkeypatch, tmp_path):
    """업데이트 뒤 살아남은 옛 크롬은 화면 밖에서 그리기를 멈춘다(스트림 0장) — 한 번 끄고 새로 띄운다."""
    monkeypatch.setattr("sys.platform", "win32")
    BrowserWorker._park_offscreen = True
    worker = BrowserWorker.__new__(BrowserWorker)
    worker.config = SimpleNamespace(browser_profile_dir=tmp_path / "browser-profile", browser_headless=False)
    old = f'chrome.exe --remote-debugging-port=9222 --user-data-dir="{worker.config.browser_profile_dir}"'
    worker._chrome_scan = lambda max_age_sec=0.0: {1: old, 2: old + " --type=renderer"}  # type: ignore[method-assign]
    assert worker._our_chrome_needs_restart()
    worker._chrome_scan = lambda max_age_sec=0.0: {1: old + " --disable-backgrounding-occluded-windows"}  # type: ignore[method-assign]
    assert worker._our_chrome_needs_restart(), "음소거 없는 옛 크롬(09-26 전)도 한 번 다시 띄운다 — 자동 재생 소리"
    worker._chrome_scan = lambda max_age_sec=0.0: {1: old + " --disable-backgrounding-occluded-windows --mute-audio"}  # type: ignore[method-assign]
    assert not worker._our_chrome_needs_restart()
    worker._chrome_scan = lambda max_age_sec=0.0: {}  # type: ignore[method-assign]
    assert not worker._our_chrome_needs_restart(), "떠 있는 크롬이 없으면 끌 것도 없다"


def test_parking_keeps_the_size_the_stage_chose():
    """무대에 맞춘 크기를 치울 때마다 되돌리면 화면이 출렁인다 — 제 크기 창은 자리만 옮긴다."""
    BrowserWorker._park_offscreen = True

    class _User32:
        moves: list = []

        def GetForegroundWindow(self):  # noqa: N802
            return 0

        def IsZoomed(self, _h):  # noqa: N802
            return 0

        def GetSystemMetrics(self, i):  # noqa: N802
            return {78: 1920, 16: 1920, 17: 1100}.get(i, 0)

        def GetWindowRect(self, _h, ref):  # noqa: N802
            rect = ref._obj
            rect.left, rect.top, rect.right, rect.bottom = 2120, 0, 2120 + 1280, 1000
            return 1

        def SetWindowPos(self, *args):  # noqa: N802
            self.moves.append(args)
            return 1

    user32 = _User32()
    assert BrowserWorker._park_window_offscreen(user32, 7)
    assert user32.moves[-1][-1] & 0x0001, "SWP_NOSIZE 가 없다 — 무대 크기를 되돌렸다"


def test_a_takeover_while_the_agent_was_thinking_still_reaches_the_agent():
    """넘겨받았다 돌려주는 동안 온텔릭이 도구를 안 불렀으면(생각 중) 기다린 적이 없다 — 그래도 다음 결과에 알려야 한다."""
    worker = BrowserWorker.__new__(BrowserWorker)
    view, _sent = _view()
    view.worker = worker
    worker.live_view = view
    worker._human_took_over = None
    view.take_control()
    view._control_since = time.time() - 5
    view.release_control("button")
    assert "human_took_over" in worker._with_takeover_note({"ok": True})


def test_every_live_header_the_screen_reads_is_exposed_to_the_webview():
    """포장 앱은 화면과 백엔드의 출처가 달라 CORS 가 노출한 헤더만 읽힌다 — 빠진 헤더는 화면에서 null 이 된다(2026-09-24 발견)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    api = (root / "src" / "alture_jarvis" / "api.py").read_text(encoding="utf-8")
    exposed = set(re.findall(r'"(X-Live-[A-Za-z-]+)"', api.split("expose_headers=", 1)[1].split("]", 1)[0]))
    client = (root / "ui" / "src" / "backend.ts").read_text(encoding="utf-8")
    read = set(re.findall(r'header\("(X-Live-[A-Za-z-]+)"\)', client))
    assert read, "화면이 읽는 X-Live 헤더를 못 찾았다 — 이 시험의 눈금이 낡았다"
    assert read <= exposed, f"노출 안 된 헤더: {sorted(read - exposed)}"


def test_a_background_tab_that_ignores_the_window_gets_the_same_size() -> None:
    """뒤 탭은 창 크기를 안 따라온다 — 창은 1280 인데 안쪽이 1920×922 로 남았다(2026-09-26 E2E)."""
    from alture_jarvis.live_view import LiveView

    sent: list[tuple[str, dict]] = []
    answers = {
        "Browser.getWindowForTarget": {"windowId": 7, "bounds": {"width": 1280, "height": 975, "windowState": "normal"}},
    }
    evaluations = iter(['[0, 70]', '[1920, 922]'])

    def fake_send(method, params=None, **_kwargs):
        sent.append((method, params or {}))
        if method == "Runtime.evaluate":
            return {"result": {"value": next(evaluations)}}
        return answers.get(method)

    worker = SimpleNamespace(_connected=True, _page=None, _cdp_port_in_use=9222,
                             config=SimpleNamespace(browser_cdp_port=9222), _human_took_over=None)
    view = LiveView(worker)
    view._watch = lambda: None  # type: ignore[method-assign]
    view._send = fake_send  # type: ignore[method-assign]
    view._target_id, view._ws = "A", object()
    view._fit_wanted = (1280, 905)
    view._apply_fit()
    assert ("Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 905, "deviceScaleFactor": 0, "mobile": False}) in sent
    assert not any(method == "Browser.setWindowBounds" for method, _ in sent), "창은 이미 맞다 — 다시 건드리지 않는다"


def test_input_while_the_stream_is_reconnecting_is_not_silently_dropped() -> None:
    """끊긴 사이의 입력이 「성공」으로 돌아가 사라졌다 — 로그인 E2E 에서 아이디가 비었다(2026-09-26)."""
    from alture_jarvis.live_view import LiveView

    worker = SimpleNamespace(_connected=True, _page=None, _cdp_port_in_use=9222,
                             config=SimpleNamespace(browser_cdp_port=9222), _human_took_over=None)
    view = LiveView(worker)
    view._watch = lambda: None  # type: ignore[method-assign]
    view._send = lambda *_a, **_k: None  # type: ignore[method-assign]
    view._frame = {"seq": 1, "jpeg": b"x", "css_width": 1280.0, "css_height": 800.0}
    view._ws = None
    result = view.input({"kind": "text", "text": "tester"})
    assert result == {"ok": False, "error": "not_connected"}


def test_the_stream_socket_does_not_die_on_keepalive() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "live_view.py").read_text(encoding="utf-8")
    assert "ping_interval=None" in source
