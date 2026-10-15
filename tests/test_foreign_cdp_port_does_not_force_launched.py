"""9222 에 **남의 브라우저**가 답하면 붙기에 실패하고 자동화 크롬(`launched`)으로 내려갔다 (2026-09-20 이 PC 운영).

운영 `/health`: `connect_mode: launched`, `automation_flag: true`,
`attach_error: connect_over_cdp: Protocol error (Browser.setDownloadBehavior): Browser context management is not supported`.
9222 에 우리 프로필이 아닌 무언가가 떠 있었다. 그러면:

- Playwright 가 띄우는 크롬에는 「최소화로 띄우고 조용히 맨 뒤로」 장치가 없다 → 사용자가 본 「파파박 → 뒤로 숨기」.
  번쩍임 눈금(`measure_chrome_flash.py`)은 우리 방식(`spawned`)만 재서 3/3 이 0 이었다 — 운영이 탄 길을 안 쟀다.
- 자동화 표시가 켜진 크롬이라 봇 검사하는 사이트에서 막힌다.

고침: 남의 포트에 붙기가 실패하면 **비어 있는 다른 포트에 우리 크롬을 우리 방식으로** 띄워 붙는다. 그래도 안 될 때만 `launched`.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path: Path) -> BrowserWorker:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", browser_profile_dir=tmp_path / "p",
                          browser_cdp_port=9222, browser_attach_mode="auto")
    worker = BrowserWorker(config)
    worker._kill_profile_chromes = lambda: 0  # type: ignore[method-assign]
    worker._kill_chrome_process = lambda proc: None  # type: ignore[method-assign]
    worker._port_is_our_profile = lambda port: False  # type: ignore[method-assign]
    worker._free_cdp_port = lambda base: 9231  # type: ignore[method-assign]
    return worker


def test_a_foreign_port_failure_spawns_ours_on_a_spare_port(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    tried: list[int] = []

    def attach(port=None):
        tried.append(int(port or 9222))
        if int(port or 9222) == 9222:
            raise RuntimeError("Browser context management is not supported")
        worker._connect_mode = "spawned"
        return "our-context"

    worker._attach_chrome = attach  # type: ignore[method-assign]
    worker._launch_chrome = lambda: (_ for _ in ()).throw(AssertionError("자동화 크롬으로 내려갔다"))  # type: ignore[method-assign]
    assert worker._connect_context() == "our-context"
    assert tried[-1] == 9231 and worker._connect_mode == "spawned"
    assert worker._cdp_port_in_use == 9231


def test_when_even_the_spare_port_fails_it_still_launches(tmp_path: Path) -> None:
    """★ 좋은 표본 — 마지막 안전망은 그대로다. 브라우저가 아예 없는 것보다 자동화 크롬이 낫다."""
    worker = _worker(tmp_path)

    def attach(port=None):
        raise RuntimeError("nope")

    worker._attach_chrome = attach  # type: ignore[method-assign]
    worker._launch_chrome = lambda: "launched-context"  # type: ignore[method-assign]
    assert worker._connect_context() == "launched-context"
    assert worker._connect_mode == "launched"


def test_a_working_attach_is_untouched(tmp_path: Path) -> None:
    worker = _worker(tmp_path)

    def attach(port=None):
        worker._connect_mode = "attached"
        return "their-context"

    worker._attach_chrome = attach  # type: ignore[method-assign]
    assert worker._connect_context() == "their-context"
    assert worker._cdp_port_in_use == 9222


def test_the_spare_port_really_reaches_the_spawn() -> None:
    """위 시험들은 붙기 함수를 가짜로 바꿔 끼워서, 넘긴 포트를 **진짜 붙기 함수가 쓰는지**는 못 본다.
    실제로 한 번 빠졌었다(줄바꿈 차이로 그 줄만 안 고쳐짐) — 그래서 원문을 본다."""
    import inspect

    source = inspect.getsource(BrowserWorker._attach_chrome)
    assert "port: int | None = None" in source
    assert "port = int(port or self.config.browser_cdp_port or 9222)" in source


# ── 다른 온텔릭의 크롬에는 붙지 않는다 (2026-09-23) ─────────────────────────────────────────────
# 스토어 촬영용 앱(가짜 홈)이 이 PC 평소 온텔릭 크롬(9222)에 **붙기에 성공**했다 — 붙기가 실패해야 빈 포트로 가는데,
# 같은 온텔릭 크롬이라 성공해 버렸다. 두 앱이 크롬 하나를 몰아 다나와 본문 읽기가 180초씩 멈췄다(혼자면 2.2초).


def _attach_worker(tmp_path: Path, command_lines: dict[int, str]) -> BrowserWorker:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d",
                          browser_profile_dir=tmp_path / "mine" / "browser-profile",
                          browser_cdp_port=9222, browser_attach_mode="auto")
    worker = BrowserWorker(config)
    worker._probe_cdp = staticmethod(lambda port: {"Browser": "Chrome/151.0"})  # type: ignore[method-assign]
    worker._chrome_scan = lambda max_age_sec=1.0: command_lines  # type: ignore[method-assign]
    return worker


def test_another_ontelics_chrome_is_refused(tmp_path: Path) -> None:
    other = r'chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\RoboMetaFit\tools\alture-jarvis\data\browser-profile" --no-first-run'
    worker = _attach_worker(tmp_path, {7: other})
    try:
        worker._attach_chrome(9222)
    except RuntimeError as error:
        assert "another_ontelic_chrome" in str(error)
    else:  # pragma: no cover
        raise AssertionError("다른 온텔릭의 크롬에 붙었다")


def test_our_own_chrome_on_the_port_is_still_attached(tmp_path: Path) -> None:
    """★ 좋은 표본 — 앞 판 백엔드가 남긴 **우리** 크롬에는 그대로 붙는다."""
    mine = tmp_path / "mine" / "browser-profile"
    worker = _attach_worker(tmp_path, {7: f'chrome.exe --remote-debugging-port=9222 --user-data-dir="{mine}"'})
    assert worker._port_is_our_profile(9222) and not worker._port_is_another_ontelic(9222)


def test_a_persons_own_debug_chrome_is_still_attached(tmp_path: Path) -> None:
    """★ 좋은 표본 — 사람이 자기 프로필로 포트를 열어 둔 크롬은 막지 않는다(붙기 설계 1번)."""
    person = r'chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\Users\me\ChromeDebug"'
    worker = _attach_worker(tmp_path, {7: person})
    assert not worker._port_is_another_ontelic(9222)


def test_refusing_another_ontelic_moves_ours_to_a_spare_port(tmp_path: Path) -> None:
    """막은 뒤에는 빈 포트에 **우리 크롬을 우리 방식으로** — 자동화 크롬으로 내려가지 않는다."""
    worker = _worker(tmp_path)
    tried: list[int] = []

    def attach(port=None):
        tried.append(int(port or 9222))
        if int(port or 9222) == 9222:
            raise RuntimeError("another_ontelic_chrome:9222")
        worker._connect_mode = "spawned"
        return "our-context"

    worker._attach_chrome = attach  # type: ignore[method-assign]
    worker._launch_chrome = lambda: (_ for _ in ()).throw(AssertionError("자동화 크롬으로 내려갔다"))  # type: ignore[method-assign]
    assert worker._connect_context() == "our-context" and tried[-1] == 9231
