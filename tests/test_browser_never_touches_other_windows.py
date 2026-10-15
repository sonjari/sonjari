"""★ 제품 사고 (2026-09-16): 크롬을 내리려던 감시 스레드가 **사용자의 창을 내렸다.**

증상은 「카톡 작업표시줄을 눌러도 안 뜬다」와 「보조 모니터 작업표시줄이 사라졌다」였다.
실측으로 카카오톡 창과 explorer 의 `Shell_SecondaryTrayWnd` 가 `iconic=True` 인 것을 확인했다.

원인: 「우리 크롬인가」 판단이 **띄운 직후 몇 초는 「새로 생긴 pid 인가」로만** 답했다.
그 사이에 사람이 카톡을 새로 띄우면 그 pid 는 목록에 없으니 「우리 것」이 됐다.
`_our_chrome_windows` 는 이름을 봤지만 **앞창을 보는 자리는 안 봤다** — 한 겹이 빠졌다.

이 파일은 그 한 겹을 못 박는다. 창을 내리는 코드는 위험하다: 되돌리는 값이 서로 다르다
(크롬 창 하나 vs 사람이 PC 를 쓸 수 없게 되는 것).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path: Path) -> BrowserWorker:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    worker = BrowserWorker(config)
    # 사고 당시의 상태: 크롬을 방금 띄웠고, 그 전 pid 목록을 찍어 두었다.
    worker._chrome_pids_before_launch = {1111, 2222}
    worker._launch_watch_until = float("inf")
    return worker


@pytest.mark.parametrize("name", ["KakaoTalk.exe", "explorer.exe", "Code.exe", "", "chrome.exe.bak"])
def test_a_process_that_is_not_chrome_is_never_ours(tmp_path: Path, monkeypatch, name: str) -> None:
    """★ 이 줄이 사고를 막는다 — 이름이 chrome.exe 가 아니면 무엇이든 우리 것이 아니다."""
    worker = _worker(tmp_path)
    monkeypatch.setattr(BrowserWorker, "_process_name", staticmethod(lambda pid: name))

    # 9999 는 띄우기 전 목록에 없다 — 예전 코드는 이것만 보고 True 를 답했다.
    assert worker._is_our_chrome_pid(9999) is False


def test_a_new_chrome_pid_during_the_launch_window_is_ours(tmp_path: Path, monkeypatch) -> None:
    """막기만 하면 안 된다 — 크롬은 여전히 알아봐야 한다(안 그러면 창이 앞으로 튀어나온다)."""
    worker = _worker(tmp_path)
    monkeypatch.setattr(BrowserWorker, "_process_name", staticmethod(lambda pid: "chrome.exe"))

    assert worker._is_our_chrome_pid(9999) is True   # 띄운 뒤 생긴 크롬
    assert worker._is_our_chrome_pid(1111) is False  # 띄우기 전부터 있던 사람의 크롬


@pytest.mark.parametrize("klass", ["Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"])
def test_shell_windows_are_off_limits_even_if_the_pid_says_ours(tmp_path: Path, monkeypatch, klass: str) -> None:
    """둘째 그물 — 작업표시줄·바탕화면은 창처럼 보이지만 사람의 PC 그 자체다."""
    worker = _worker(tmp_path)
    monkeypatch.setattr(BrowserWorker, "_process_name", staticmethod(lambda pid: "chrome.exe"))
    monkeypatch.setattr(BrowserWorker, "_window_class", staticmethod(lambda hwnd: klass))

    assert worker._is_our_chrome_pid(9999) is True, "pid 로는 우리 것이라도"
    assert worker._window_is_ours(4242, 9999) is False, "셸 창이면 안 건드린다"


def test_an_ordinary_chrome_window_still_passes(tmp_path: Path, monkeypatch) -> None:
    worker = _worker(tmp_path)
    monkeypatch.setattr(BrowserWorker, "_process_name", staticmethod(lambda pid: "chrome.exe"))
    monkeypatch.setattr(BrowserWorker, "_window_class", staticmethod(lambda hwnd: "Chrome_WidgetWin_1"))

    assert worker._window_is_ours(4242, 9999) is True


def test_the_watcher_can_be_turned_off_in_one_line(tmp_path: Path) -> None:
    """남의 창에 닿을 수 있는 코드에는 끄는 손잡이가 있어야 한다 — `JARVIS_BROWSER_SINK_WINDOWS=0`."""
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          browser_sink_windows=False)
    worker = BrowserWorker(config)

    worker._sink_new_chrome_window(watch_sec=0.1)

    assert worker._sink_report.get("thread") == "disabled"


def test_the_switch_lives_in_both_places(tmp_path: Path, monkeypatch) -> None:
    """dataclass 기본값과 환경변수 로더가 갈리면 낮은 쪽이 일한다(사고 Q)."""
    assert JarvisConfig(runtime_root=tmp_path).browser_sink_windows is True
    monkeypatch.setenv("JARVIS_RUNTIME_ROOT", str(tmp_path / "rt"))
    monkeypatch.setenv("JARVIS_BROWSER_SINK_WINDOWS", "0")
    assert JarvisConfig.from_env().browser_sink_windows is False
