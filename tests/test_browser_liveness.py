"""브라우저가 죽은 것을 **알아채고** 스스로 되살린다.

2026-08-09 실측 사고. 자비스 크롬이 21:45:16 에 정상 종료됐는데, 21:46 에 들어온
대화가 `browser_search` 에서 `Page.goto: Target page, context or browser has been
closed` 로 넘어졌다. 그 세션의 브라우저 도구는 그 뒤로 전부 같은 에러였고,
`/v1/browser/status` 는 내내 `started: true` 라고 답했다.

원인은 생존 검사였다. `context.browser.is_connected()` 는 **캐시된 플래그**다.
Playwright 동기 API 는 프로토콜 호출에 딸려 오는 이벤트로 그 값을 갱신하는데,
속성 읽기는 드라이버에 아무것도 안 보내므로 큐에 쌓인 disconnected 가 처리되지
않는다. 물어보는 그 순간에 반드시 낡아 있는 검사였다 — NAS 사고 H 의
`/api/tags`, 자비스 워치독의 초기 생존 검사와 같은 계열이다.

여기서 지키는 것 넷:

  1. 컨텍스트에 **실제로 말을 걸어서** 판정한다 (플래그만 읽지 않는다)
  2. 죽었으면 다음 도구 호출이 알아서 다시 띄운다
  3. `status()` 가 죽은 브라우저를 살아 있다고 하지 않는다
  4. 되돌릴 수 없는 동작은 조용히 재시도하지 않는다 — 사람이 화면을 본다
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

_DEAD = "Page.goto: Target page, context or browser has been closed"


class _Browser:
    def __init__(self, connected: bool = True) -> None:
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected


class _Context:
    """살아 있으면 대답하고, 죽었으면 예외를 던지는 컨텍스트.

    ★ `browser.is_connected()` 는 **죽은 뒤에도 계속 True** 를 돌려준다. 그게
    실제 Playwright 의 모양이고(이벤트가 처리되지 않아서), 이 시험의 전부다 —
    플래그만 보는 구현은 여기서 반드시 통과해 버린다.
    """

    def __init__(self) -> None:
        self.alive = True
        self.browser = _Browser(connected=True)
        self.cookie_calls = 0
        self.closed = False
        self.pages: list[Any] = []

    def cookies(self, urls: Any = None) -> list[dict[str, Any]]:
        del urls
        self.cookie_calls += 1
        if not self.alive:
            raise RuntimeError(_DEAD)
        return []

    def close(self) -> None:
        self.closed = True


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_visual_overlay=False,
            browser_evidence_dir=tmp_path / "evidence",
        )
    )


def test_liveness_asks_the_browser_instead_of_reading_a_flag(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    context = _Context()
    worker._context = context

    assert worker._context_alive() is True
    assert context.cookie_calls == 1, "플래그만 읽고 지나갔다 — 왕복이 없었다"

    # 크롬이 죽었다. 플래그는 여전히 '연결됨'이라고 말한다.
    context.alive = False
    assert context.browser.is_connected() is True

    assert worker._context_alive() is False, "죽은 브라우저를 살아 있다고 했다"


def test_status_does_not_claim_a_dead_browser_is_up(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    context = _Context()
    worker._context = context
    worker._connected = True  # 기동 때 세워 둔 값 — 이것만 믿으면 안 된다

    assert worker.status()["started"] is True

    context.alive = False
    status = worker.status()
    assert status["started"] is False
    assert status["liveness"] == "probed"

    worker.stop()


def test_a_dead_context_is_relaunched_on_the_next_call(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    dead = _Context()
    dead.alive = False
    worker._context = dead

    started: list[str] = []

    class _Page:
        def is_closed(self) -> bool:
            return False

    def _fake_start() -> dict[str, Any]:
        fresh = _Context()
        fresh.pages = [_Page()]
        worker._context = fresh
        started.append("started")
        return {"action": "browser_started"}

    worker._ensure_started = _fake_start  # type: ignore[method-assign]
    page = worker._current_page()

    assert started == ["started"], "죽은 컨텍스트를 두고 재기동하지 않았다"
    assert dead.closed is True, "죽은 컨텍스트를 정리하지 않았다"
    assert page is worker._context.pages[0]


def test_reads_retry_once_but_irreversible_actions_do_not(tmp_path: Path) -> None:
    """되돌릴 수 없는 것 앞에서는 조용히 다시 하지 않는다.

    브라우저가 사라졌다는 것은 그 동작이 닿지 않았다는 뜻이라 논리적으로는
    되풀이해도 안전하다. 그래도 누르기·발행은 뺀다 — 여러 단계를 밟는 핸들러가
    중간에 죽은 경우까지 여기서 판단할 수는 없기 때문이다.
    """
    worker = _worker(tmp_path)
    calls: list[str] = []

    def _once(action: str, arguments: dict[str, Any], *, trusted: bool = False) -> dict[str, Any]:
        del arguments, trusted
        calls.append(action)
        if calls.count(action) == 1:
            raise RuntimeError(_DEAD)
        return {"action": action}

    worker._execute_once = _once  # type: ignore[method-assign]
    worker._shutdown = lambda: None  # type: ignore[method-assign]

    assert worker._execute("browser_search", {}) == {"action": "browser_search"}
    assert calls.count("browser_search") == 2, "읽기인데 한 번 더 해 보지 않았다"

    try:
        worker._execute("browser_click_confirmed", {})
    except RuntimeError as exc:
        assert _DEAD in str(exc)
    else:  # pragma: no cover - 실패했을 때만 도달한다
        raise AssertionError("되돌릴 수 없는 동작을 조용히 다시 했다")
    assert calls.count("browser_click_confirmed") == 1


def test_other_failures_are_not_retried(tmp_path: Path) -> None:
    """브라우저가 죽은 것과 페이지가 이상한 것은 다르다. 후자는 재시도할 일이 아니다."""
    worker = _worker(tmp_path)
    calls: list[str] = []

    def _once(action: str, arguments: dict[str, Any], *, trusted: bool = False) -> dict[str, Any]:
        del arguments, trusted
        calls.append(action)
        raise RuntimeError("selector_not_found: .nope")

    worker._execute_once = _once  # type: ignore[method-assign]

    try:
        worker._execute("browser_search", {})
    except RuntimeError as exc:
        assert "selector_not_found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("엉뚱한 실패가 삼켜졌다")
    assert calls == ["browser_search"]
