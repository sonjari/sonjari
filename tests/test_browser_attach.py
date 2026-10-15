"""크롬을 **Playwright 가 띄우지 않고**, 평범하게 띄운 크롬에 붙는다.

2026-08-11 실측. 같은 PC · 같은 UA · 같은 headed 조건에서:

    Playwright 가 띄운 크롬   navigator.webdriver=true   쿠팡 상품검색 Access Denied
    chrome.exe + CDP attach  navigator.webdriver=false  열림 · 상품 309개

원인은 위장 여부가 아니라 **누가 크롬을 띄웠는가**였다. Playwright 는
`--remote-debugging-pipe` 로 크롬을 모는데 그게 크롬을 자동화 모드로 넣고,
덤으로 사람 브라우저엔 없는 플래그 40여 개가 붙는다. `--remote-debugging-port`
는 자동화 모드가 아니다 — 개발자가 DevTools 를 여는 것과 같은 길이다.

여기서 지키는 것 다섯:

  1. 포트가 이미 열려 있으면 **새로 띄우지 않고** 그 크롬에 붙는다
  2. 안 열려 있으면 chrome.exe 를 사람이 띄우듯 띄운다 — `--disable-*` 를 덧대지 않는다
  3. 붙기가 안 되면 예전 방식으로 내려가되, **왜 내려갔는지 남긴다**(조용한 폴백 금지)
  4. 붙기만 한 크롬은 끄지 않는다. 남의 창이다
  5. 프로필은 예전과 같은 폴더 — 해 둔 로그인이 그대로 딸려 와야 한다
"""

from __future__ import annotations

import sys

import pytest
import types
from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Page:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return ""

    def evaluate(self, script: str) -> Any:
        del script
        return False

    def on(self, event: str, handler: Any) -> None:
        del event, handler

    def goto(self, url: str, **kwargs: Any) -> None:
        self.url = url


class _Context:
    def __init__(self, pages: list[_Page] | None = None, browser: Any = None) -> None:
        self.pages = pages if pages is not None else [_Page()]
        self.browser = browser
        self.closed = False
        self.new_pages = 0

    def set_default_timeout(self, value: Any) -> None:
        del value

    def set_default_navigation_timeout(self, value: Any) -> None:
        del value

    def on(self, event: str, handler: Any) -> None:
        del event, handler

    def cookies(self, urls: Any = None) -> list[dict[str, Any]]:
        del urls
        return []

    def new_page(self) -> _Page:
        self.new_pages += 1
        page = _Page()
        self.pages.append(page)
        return page

    def new_cdp_session(self, page: Any) -> Any:
        del page
        raise RuntimeError("no cdp in test")

    def close(self) -> None:
        self.closed = True


class _Browser:
    def __init__(self, context: _Context) -> None:
        self.contexts = [context]
        self.closed = False

    def is_connected(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


class _Chromium:
    """`connect_over_cdp` 와 `launch_persistent_context` 중 무엇이 불렸는지 센다."""

    def __init__(self, context: _Context) -> None:
        self.context = context
        self.browser = _Browser(context)
        self.cdp_endpoints: list[str] = []
        self.launch_calls: list[dict[str, Any]] = []

    def connect_over_cdp(self, endpoint: str) -> _Browser:
        self.cdp_endpoints.append(endpoint)
        return self.browser

    def launch_persistent_context(self, **kwargs: Any) -> _Context:
        self.launch_calls.append(kwargs)
        return self.context


class _Playwright:
    def __init__(self, chromium: _Chromium) -> None:
        self.chromium = chromium
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _Proc:
    """chrome.exe 대역. `alive=False` 면 띄우자마자 죽은 것으로 친다."""

    def __init__(self, alive: bool = True) -> None:
        self.pid = 4242
        self.alive = alive
        self.killed = False

    def poll(self) -> int | None:
        return None if self.alive else 1

    def terminate(self) -> None:
        self.killed = True


def _worker(tmp_path: Path, **overrides: Any) -> tuple[BrowserWorker, _Chromium]:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_visual_overlay=False,
        browser_evidence_dir=tmp_path / "evidence",
        browser_headless=True,
        browser_home_url="",
        **overrides,
    )
    worker = BrowserWorker(config)
    # ★ 이 PC 에 **실제로 떠 있는 크롬 명령줄**을 읽지 않게 한다(2026-09-23). 읽으면 평소 온텔릭 크롬(9222)이
    #   「다른 온텔릭」으로 잡혀 시험 결과가 PC 상태에 따라 갈린다.
    worker._chrome_scan = lambda max_age_sec=1.0: {}  # type: ignore[method-assign]
    chromium = _Chromium(_Context())
    playwright = _Playwright(chromium)

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: types.SimpleNamespace(start=lambda: playwright)  # type: ignore[attr-defined]
    package = types.ModuleType("playwright")
    sys.modules.setdefault("playwright", package)
    sys.modules["playwright.sync_api"] = module
    return worker, chromium


@pytest.fixture(autouse=True)
def _put_the_real_playwright_back():
    """`_worker` 가 가짜 playwright 모듈을 `sys.modules` 에 넣는다 — 되돌리지 않으면 **뒤에 도는** 진짜 크로미움
    시험들(섀도 DOM·구조화 데이터…)이 가짜를 받아 전체 실행에서만 깨진다(2026-09-18 실측)."""
    saved = {name: sys.modules.get(name) for name in ("playwright", "playwright.sync_api")}
    yield
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def test_an_open_port_is_used_instead_of_launching_another_chrome(tmp_path: Path) -> None:
    worker, chromium = _worker(tmp_path)
    spawned: list[int] = []
    worker._probe_cdp = staticmethod(lambda port: {"Browser": "Chrome/151.0"})  # type: ignore[method-assign]
    worker._spawn_chrome = lambda port: spawned.append(port)  # type: ignore[method-assign]

    worker._ensure_started()

    assert spawned == [], "이미 떠 있는 크롬을 두고 하나 더 띄웠다"
    assert worker._connect_mode == "attached"
    assert chromium.cdp_endpoints == ["http://127.0.0.1:9222"]
    assert chromium.launch_calls == [], "붙었는데도 Playwright 로 또 띄웠다"


def test_a_closed_port_spawns_a_plain_chrome_and_attaches(tmp_path: Path) -> None:
    worker, chromium = _worker(tmp_path)
    opened: list[int] = []

    def _probe(port: int) -> dict[str, Any] | None:
        # 처음엔 닫혀 있고, 크롬을 띄운 뒤부터 열린다.
        return {"Browser": "Chrome/151.0"} if opened else None

    worker._probe_cdp = staticmethod(_probe)  # type: ignore[method-assign]

    def _spawn(port: int) -> None:
        opened.append(port)
        worker._chrome_proc = _Proc()

    worker._spawn_chrome = _spawn  # type: ignore[method-assign]

    worker._ensure_started()

    assert opened == [9222]
    assert worker._connect_mode == "spawned"
    assert chromium.cdp_endpoints == ["http://127.0.0.1:9222"]


def test_the_spawned_chrome_looks_like_a_persons_chrome(tmp_path: Path) -> None:
    """플래그를 덧댈수록 다시 자동화 브라우저로 보인다 — 그럼 전환할 이유가 없다."""
    worker, _ = _worker(tmp_path)
    recorded: list[list[str]] = []

    class _Popen:
        def __init__(self, arguments: list[str], **kwargs: Any) -> None:
            recorded.append(arguments)
            self.pid = 1

        def poll(self) -> int | None:
            return None

    import alture_jarvis.browser as browser_module

    original = browser_module.subprocess.Popen
    browser_module.subprocess.Popen = _Popen  # type: ignore[assignment]
    worker._find_chrome = lambda: "chrome.exe"  # type: ignore[method-assign]
    try:
        worker._spawn_chrome(9222)
    finally:
        browser_module.subprocess.Popen = original  # type: ignore[assignment]

    # psutil 이 없는 환경(포장본·일부 venv)에서는 띄우기 전 크롬 스캔이 powershell 로 먼저 불린다 — 크롬 호출을 골라 본다.
    arguments = next(call for call in recorded if call and call[0] == "chrome.exe")
    assert "--remote-debugging-port=9222" in arguments
    assert f"--user-data-dir={worker.config.browser_profile_dir}" in arguments, (
        "프로필이 갈리면 해 둔 로그인이 통째로 사라진다"
    )
    assert not [a for a in arguments if a.startswith("--disable-") and "background" not in a]
    assert "--enable-automation" not in arguments


def test_a_failed_attach_falls_back_but_says_why(tmp_path: Path) -> None:
    """조용히 갈아타면 다음에 막혔을 때 원인을 처음부터 다시 판다."""
    worker, chromium = _worker(tmp_path)
    worker._probe_cdp = staticmethod(lambda port: None)  # type: ignore[method-assign]

    def _spawn(port: int) -> None:
        raise RuntimeError("chrome_not_found — JARVIS_BROWSER_CHROME_PATH 로 알려주세요.")

    worker._spawn_chrome = _spawn  # type: ignore[method-assign]

    worker._ensure_started()

    assert worker._connect_mode == "launched"
    assert chromium.launch_calls, "바닥으로 내려가지 않았다"
    assert "chrome_not_found" in worker._attach_error
    assert "chrome_not_found" in worker.status()["attach_error"], (
        "왜 예전 방식으로 돌아갔는지 화면에서 알 수 없다"
    )


def test_attach_off_keeps_the_old_path(tmp_path: Path) -> None:
    worker, chromium = _worker(tmp_path, browser_attach_mode="off")
    worker._probe_cdp = staticmethod(lambda port: {"Browser": "Chrome/151.0"})  # type: ignore[method-assign]

    worker._ensure_started()

    assert worker._connect_mode == "launched"
    assert chromium.cdp_endpoints == [], "꺼 뒀는데 붙었다"
    assert chromium.launch_calls


def test_a_borrowed_chrome_is_not_closed_but_ours_is(tmp_path: Path) -> None:
    worker, chromium = _worker(tmp_path)

    worker._context = chromium.context
    worker._playwright = _Playwright(chromium)
    worker._connect_mode = "attached"
    worker._shutdown()
    assert chromium.context.closed is False, "남의 크롬 창을 닫았다"
    assert chromium.browser.closed is False

    chromium.context.browser = chromium.browser
    worker._context = chromium.context
    worker._playwright = _Playwright(chromium)
    worker._connect_mode = "spawned"
    process = _Proc()
    worker._chrome_proc = process
    worker._shutdown()
    assert chromium.browser.closed is True, "우리가 띄운 크롬을 남겨 뒀다"


def test_a_locked_profile_says_so_instead_of_hanging(tmp_path: Path) -> None:
    """같은 프로필로 크롬이 이미 떠 있으면 chrome.exe 는 조용히 끝난다."""
    worker, _ = _worker(tmp_path, browser_attach_launch_timeout_sec=5)
    worker._probe_cdp = staticmethod(lambda port: None)  # type: ignore[method-assign]
    worker._spawn_chrome = lambda port: setattr(  # type: ignore[method-assign]
        worker, "_chrome_proc", _Proc(alive=False)
    )

    started = __import__("time").time()
    try:
        worker._attach_chrome()
    except RuntimeError as error:
        assert "cdp_port_never_opened" in str(error)
        assert "이미 떠 있으면" in str(error), "무엇을 해야 하는지 알 수 없는 에러다"
    else:  # pragma: no cover - 실패했을 때만 도달한다
        raise AssertionError("포트가 안 열렸는데 붙었다고 했다")
    assert __import__("time").time() - started < 10, "죽은 크롬을 끝까지 기다렸다"
