"""상태 확인이 진짜 일을 밀어내지 않는다 (2026-10-01 운영 판 d60f38d3).

화면의 상태 확인(`/health` → naver_blog.status)이 몇 초마다 `naver_session_alive` 를 부르는데, 전면 일로 등록돼 있어서
그 순간 손자리의 걸음(browser_page_data)이 「앞 동작(browser_internal:naver_session_alive)을 0초째 실행 중」으로 거절됐다.
배경 일로 보내면 작업 걸음은 몇 초 양보받고, 작업 중엔 확인 쪽이 물러난다.
"""

from __future__ import annotations

from alture_jarvis.browser import BrowserWorker


def _worker(calls: list[dict]) -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)

    def submit(function, timeout=None, **kwargs):  # noqa: ANN001
        calls.append(kwargs)
        return []

    worker._submit = submit  # type: ignore[assignment]
    worker.start = lambda: None  # type: ignore[assignment]
    return worker


def test_naver_session_check_is_background() -> None:
    calls: list[dict] = []
    _worker(calls).naver_session_alive()
    assert calls and calls[0].get("background") is True
    assert calls[0].get("operation") == "browser_internal:naver_session_alive"


def test_gate_watcher_is_background() -> None:
    calls: list[dict] = []
    worker = _worker(calls)
    worker.gate_state({"url": "https://nid.naver.com/", "hosts": ["naver.com"]})
    assert calls and calls[0].get("background") is True
