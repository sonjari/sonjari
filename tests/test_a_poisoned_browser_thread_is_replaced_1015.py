"""옛 Playwright 가 깨끗이 안 닫힌 일꾼 스레드에서는 브라우저가 **영원히** 다시 안 켜진다 — 스레드를 바꿔 한 번 다시 켠다 (2026-10-15).

가격 판(price1015c 3판 · 11번가 상품 페이지에서 물림) 뒤로 손자리 브라우저가
`browser_start_failed: It looks like you are using Playwright Sync API inside the asyncio loop` 로 계속 죽었고,
백엔드를 다시 띄워야만 풀렸다. 08-16 에도 같은 오류를 봤는데 그때는 「물린 쪽이 풀리면 정리된다」고 넘겼다.

실험으로 가른 것(scratchpad `repro_same_thread.py` · `repro_stuck_start.py` · Playwright 1.62):
- sync Playwright 가 살아 있는 동안 **그 스레드**에는 「돌고 있는 asyncio 루프」가 보인다.
- 그 상태로 **같은 스레드**에서 다시 `sync_playwright().start()` → 이 오류. 옛 것이 깨끗이 안 닫히면 그 스레드는 영영 못 켠다.
- **새 스레드**에서는 같은 순간에도 정상으로 켜진다.

지키는 약속(`BrowserWorker._submit`):
- 브라우저 시작이 이 오류로 실패하면 일꾼 스레드를 새로 바꾸고(`_recover_from_stuck`) **한 번만** 다시 부른다.
  시작 단계에서 난 오류라 아무 동작도 안 일어났으니 다시 불러도 두 번 하는 것이 없다.
- 두 번째도 실패하면 그 오류를 그대로 올린다(끝없이 돌지 않는다). 다른 오류는 다시 부르지 않는다.
"""

from __future__ import annotations

import threading

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

POISONED = ("browser_start_failed:It looks like you are using Playwright Sync API inside the asyncio loop. "
            "Please use the Async API instead.")


def _worker(tmp_path) -> BrowserWorker:
    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                                      browser_task_timeout_sec=5))


def test_a_start_that_fails_on_a_poisoned_thread_is_retried_once_on_a_fresh_thread(tmp_path) -> None:
    worker = _worker(tmp_path)
    threads: list[int] = []

    def start() -> str:
        threads.append(threading.get_ident())
        if len(threads) == 1:
            raise RuntimeError(POISONED)
        return "browser_started"

    assert worker._submit(start) == "browser_started"
    assert len(threads) == 2
    assert threads[0] != threads[1], "같은 스레드에서 다시 켜면 또 실패한다 — 새 스레드여야 한다"


def test_a_second_failure_is_raised_not_looped(tmp_path) -> None:
    worker = _worker(tmp_path)
    calls: list[int] = []

    def start() -> str:
        calls.append(1)
        raise RuntimeError(POISONED)

    with pytest.raises(RuntimeError, match="Sync API inside the asyncio loop"):
        worker._submit(start)
    assert len(calls) == 2


def test_other_failures_are_not_retried(tmp_path) -> None:
    worker = _worker(tmp_path)
    calls: list[int] = []

    def act() -> str:
        calls.append(1)
        raise RuntimeError("browser_click_failed: element not found")

    with pytest.raises(RuntimeError, match="element not found"):
        worker._submit(act)
    assert len(calls) == 1
