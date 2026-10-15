"""사람이 PC 를 쓰는 중이면 화면을 뺏지 않는다 (인수인계 H2-A)."""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.user_presence import UserPresence


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _config(tmp_path: Path, **values) -> JarvisConfig:
    values.setdefault("yield_to_user_enabled", True)
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", **values)


def test_tests_do_not_read_the_real_keyboard_but_the_product_does(tmp_path: Path, monkeypatch) -> None:
    assert JarvisConfig(runtime_root=tmp_path).yield_to_user_enabled is False
    monkeypatch.delenv("JARVIS_YIELD_TO_USER", raising=False)
    monkeypatch.setenv("JARVIS_RUNTIME_ROOT", str(tmp_path / "rt"))
    assert JarvisConfig.from_env().yield_to_user_enabled is True


def test_recent_input_means_active_and_old_input_means_away(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_ASSUME_USER_ACTIVE", raising=False)
    config = _config(tmp_path)
    assert UserPresence(config, idle=lambda: 3.0).active() is True
    assert UserPresence(config, idle=lambda: 30.0).active() is False
    # 잴 수 없으면(윈도우 아님) 지금까지처럼 굴어야 한다.
    assert UserPresence(config, idle=lambda: None).active() is False
    assert UserPresence(_config(tmp_path, yield_to_user_enabled=False), idle=lambda: 0.1).active() is False


def test_waiting_for_hands_off_returns_when_the_hands_stop(tmp_path: Path) -> None:
    clock = _Clock()
    typing_until = 5.0
    presence = UserPresence(_config(tmp_path), idle=lambda: 0.0 if clock.now < typing_until else clock.now - typing_until,
                            sleep=clock.sleep, clock=clock)
    assert presence.wait_until_idle(quiet_sec=2.0, timeout_sec=45.0) is True
    assert clock.now >= typing_until + 2.0


def test_hands_that_never_stop_postpone_the_action(tmp_path: Path) -> None:
    clock = _Clock()
    presence = UserPresence(_config(tmp_path), idle=lambda: 0.0, sleep=clock.sleep, clock=clock)
    assert presence.wait_until_idle(quiet_sec=2.0, timeout_sec=10.0) is False


class _Page:
    def __init__(self) -> None:
        self.fronted = 0

    def bring_to_front(self) -> None:
        self.fronted += 1

    def is_closed(self) -> bool:
        return False


# ★ 2026-09-16, 같은 지적 다섬 번째. 이 사례는 상한을 올리는 것이 아니라
#   조건을 없어야 하는 자리여서 예전 사례(60초 유휴 → 창을 올린다)를 바꿨 적는다.
#   60초는 「사람이 없다」가 아니다 — 맡기고 지키는 사람은 상태가 그렇다.
@pytest.mark.parametrize("idle,counted_as_active_yield", [(1.0, 1), (60.0, 0), (3600.0, 0)])
def test_the_browser_never_raises_its_own_window(tmp_path: Path, idle: float, counted_as_active_yield: int) -> None:
    """손이 멈췰도 화면을 가지지 안는다 — 60초는 고친 진짜 고장이다.

    단 `_yielded_front` 는 「**타이핑 중인** 사람에게 양보한 횟수」로 남긴다 —
    눈금의 뜻을 바꾸지 않는다. 그러니 60초 유휴에서는 0 이고, 그것은 양보를
    안 했다는 말이 아니다(창은 그대로 안 올린다 — 위 줄이 그것을 재고 있다).
    """
    worker = BrowserWorker(_config(tmp_path))
    worker.presence = UserPresence(worker.config, idle=lambda: idle)
    page = _Page()
    worker._bring_to_front(page)
    assert page.fronted == 0
    assert worker._yielded_front == counted_as_active_yield


def test_the_switch_is_the_only_way_to_let_it_take_the_screen(tmp_path: Path) -> None:
    """되돌릴 수 있어야 한다 — `JARVIS_BROWSER_ALLOW_FOREGROUND=1` 한 줄."""
    worker = BrowserWorker(_config(tmp_path, browser_allow_foreground=True))
    worker.presence = UserPresence(worker.config, idle=lambda: 1.0)
    page = _Page()
    worker._bring_to_front(page)
    assert page.fronted == 1


def test_a_worker_without_presence_behaves_as_before(tmp_path: Path) -> None:
    """`__init__` 을 안 거친 시험 워커는 지금까지처럼 굴어야 한다(시험이 창을 기다리지 않게)."""
    worker = BrowserWorker(_config(tmp_path))
    worker.presence = None  # type: ignore[assignment]
    page = _Page()
    worker._bring_to_front(page)
    assert page.fronted == 1


class _CdpPage(_Page):
    """캡처는 되는데, 창을 올리면 안 되는 페이지. 제한 없는 캡처를 부르면 여기서 깨진다."""

    def __init__(self) -> None:
        super().__init__()
        self.shots: list[dict] = []

    def screenshot(self, **kwargs) -> bytes:
        assert kwargs.get("timeout"), "제한 없는 캡처 — 숨은 탭에서 영원히 안 돌아온다(2026-09-16 e2e 5·6·7판)"
        self.shots.append(kwargs)
        return b"jpeg-bytes"


def test_a_screenshot_does_not_raise_the_window_while_someone_types(tmp_path: Path) -> None:
    """★ 사람이 쓰는 중에 캡처가 창을 올리면 안 된다 — 양보 규칙 밖으로 샜던 자리.

    2026-09-16 저녁: CDP 직접 호출(제한 없음)에서 `page.screenshot(timeout=…)` 으로 바꿨다. Playwright 1.62
    드라이버의 `takeScreenshot` 은 같은 CDP 호출에 제한만 씌우고 `bringToFront` 를 부르지 않는다(실측 네 조건).
    이 시험이 지키는 약속은 그대로다: **창을 안 올린다**(`bring_to_front` 0회).
    """
    worker = BrowserWorker(_config(tmp_path))
    worker.presence = UserPresence(worker.config, idle=lambda: 1.0)
    page = _CdpPage()

    raw = worker._capture(page, quiet=True)

    assert raw == b"jpeg-bytes" and len(page.shots) == 1
    assert page.fronted == 0
    # ★ 지키는 사람도 자리를 막 뜨는 사람과 구별하지 못한다 — 120초 유휴에도 창을 올리지 않는다.
    worker.presence = UserPresence(worker.config, idle=lambda: 120.0)
    assert worker._capture(page, quiet=True) == b"jpeg-bytes"
    assert page.fronted == 0
    # 스위치를 켜 둔 사람은 평소 길(Playwright)로 — 되돌리는 법은 남아 있다.
    worker.config.browser_allow_foreground = True
    assert worker._capture(page, quiet=True) is None
