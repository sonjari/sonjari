"""브라우저 연결은 「쌓인 것」을 보고 갈아 끼운다 — 우리가 띄운 크롬에서도 (2026-10-14).

그날 밤 PC 세 대에서 같은 과제를 되풀이 돌렸더니 뒤쪽 프로세스가 계속 불어났다(8GB 노트북 12시간 뒤 메모리 18GB ·
손잡이 70,323개 / 이 PC 손잡이 120,380개 — 거의 전부 세마포어). 안에서 세어 보니 Playwright 연결 장부에 페이지가
주고받은 요청 · 응답 기록이 쌓이고 있었다: 가격 조사 과제 세 개(주소로 간 것은 5번)에 손잡이 2,505 → 7,217개.

연결만 갈아 회수하는 장치는 8월부터 있었는데 둘이 어긋나 있었다.
- 눈금이 「주소로 간 횟수 50번」이었다 — 쌓이는 것은 횟수가 아니라 기록 수다.
- 「붙은 크롬」에서만 돌았다 — PC 를 켜고 처음 실행한 사람은 전부 「우리가 띄운 크롬」이라 회수가 아예 없었다.

지키는 약속:
- 장부에 쌓인 수가 한도를 넘으면 다음 동작 앞에서 간다. 붙은 크롬 · 띄운 크롬 둘 다.
- 갈 때 크롬을 끄지 않는다. 띄운 크롬은 다시 「우리가 띄운 것」으로 적어, 끌 때 같이 꺼지게 한다.
- 한도가 0 이면 끈다. Playwright 가 직접 띄운 브라우저(launched)는 다시 붙을 길이 없으니 건드리지 않는다.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path, **settings: Any) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out", **settings)
    )


def _context_with(count: int) -> Any:
    """연결 장부에 `count` 개가 쌓인 가짜 컨텍스트."""
    ledger = {f"request@{index}": object() for index in range(count)}
    return SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(_objects=ledger)))


def test_the_ledger_is_counted_and_an_unreadable_one_is_zero(tmp_path) -> None:
    worker = _worker(tmp_path)
    assert worker._connection_objects() == 0, "연결이 없으면 0"
    worker._context = _context_with(37)
    assert worker._connection_objects() == 37


@pytest.mark.parametrize("mode", ["attached", "spawned"])
def test_a_heavy_ledger_asks_for_a_swap_before_the_next_action(tmp_path, mode: str) -> None:
    worker = _worker(tmp_path, browser_reconnect_after_objects=100)
    worker._connect_mode = mode
    worker._context = _context_with(99)
    worker._note_connection_weight()
    assert worker._reconnect_pending is False, "한도 아래에서는 그대로 둔다"

    worker._context = _context_with(100)
    worker._note_connection_weight()

    assert worker._reconnect_pending is True
    assert worker._reconnect_reason == "connection_objects"


def test_zero_turns_it_off_and_a_launched_browser_is_left_alone(tmp_path) -> None:
    off = _worker(tmp_path, browser_reconnect_after_objects=0)
    off._connect_mode = "attached"
    off._context = _context_with(50_000)
    off._note_connection_weight()
    assert off._reconnect_pending is False

    launched = _worker(tmp_path, browser_reconnect_after_objects=100)
    launched._connect_mode = "launched"
    launched._context = _context_with(50_000)
    launched._note_connection_weight()
    assert launched._reconnect_pending is False, "다시 붙을 길이 없는 브라우저는 건드리지 않는다"


def test_the_default_is_on(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_BROWSER_RECONNECT_AFTER_OBJECTS", raising=False)
    plain = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    assert plain.browser_reconnect_after_objects > 0
    # 기본값과 로더가 갈리면 낮은 쪽만 일한다 — 둘이 같은 값을 넣는지 본다.
    assert JarvisConfig.from_env().browser_reconnect_after_objects == plain.browser_reconnect_after_objects


def test_a_chrome_we_started_is_swapped_without_being_closed(tmp_path) -> None:
    worker = _worker(tmp_path)
    chrome = object()
    calls: list[Any] = []

    class _Page:
        url = "https://example.test/item"

        def is_closed(self) -> bool:
            return False

    worker._connect_mode = "spawned"
    worker._chrome_proc = chrome
    worker._page = _Page()
    worker._context = _context_with(4321)
    worker._reconnect_pending = True
    worker._reconnect_reason = "connection_objects"

    def shutdown(*, keep_chrome: bool = False) -> None:
        calls.append(("shutdown", keep_chrome))
        worker._page = None
        worker._context = None
        worker._chrome_proc = None
        worker._connect_mode = ""

    def start() -> None:
        calls.append(("start", worker._reattach_url))
        # 같은 포트에 다시 붙으면 「붙은 크롬」으로 적힌다.
        worker._connect_mode = "attached"
        worker._context = _context_with(12)

    worker._shutdown = shutdown  # type: ignore[method-assign]
    worker._ensure_started = start  # type: ignore[method-assign]

    worker._reconnect_attached()

    assert calls == [("shutdown", True), ("start", "https://example.test/item")], "크롬은 두고, 보던 주소로 돌아간다"
    assert worker._connect_mode == "spawned" and worker._chrome_proc is chrome, "끌 때 같이 끄도록 다시 우리 것으로 적는다"
    assert worker._reconnect_pending is False and worker._reconnections == 1
    last = worker._last_reconnect
    assert (last["reason"], last["objects_before"], last["objects_after"]) == ("connection_objects", 4321, 12)
    assert last["took_ms"] >= 0


def test_keeping_chrome_means_neither_closing_the_browser_nor_killing_the_process(tmp_path) -> None:
    done: list[str] = []
    browser = SimpleNamespace(close=lambda: done.append("browser.close"))
    context = SimpleNamespace(browser=browser, close=lambda: done.append("context.close"))
    playwright = SimpleNamespace(stop=lambda: done.append("playwright.stop"))

    kept = _worker(tmp_path)
    kept._kill_chrome_process = lambda process: done.append("kill")  # type: ignore[method-assign]
    kept._context, kept._playwright, kept._connect_mode, kept._chrome_proc = context, playwright, "spawned", object()
    kept._shutdown(keep_chrome=True)
    assert done == ["playwright.stop"], "연결만 내려놓는다"

    done.clear()
    closed = _worker(tmp_path)
    closed._kill_chrome_process = lambda process: done.append("kill")  # type: ignore[method-assign]
    closed._context, closed._playwright, closed._connect_mode, closed._chrome_proc = context, playwright, "spawned", object()
    closed._shutdown()
    assert done == ["browser.close", "playwright.stop", "kill"], "정말 끌 때는 예전 그대로다"


def test_going_to_an_address_is_counted_for_a_chrome_we_started_too(tmp_path) -> None:
    worker = _worker(tmp_path, browser_reconnect_after_navigations=2)
    page = SimpleNamespace(goto=lambda url, wait_until: None)
    worker._connect_mode = "spawned"

    worker._goto_page(page, "https://one.test/", wait_until="domcontentloaded")
    worker._goto_page(page, "https://two.test/", wait_until="domcontentloaded")

    assert worker._reconnect_pending is True


# ── 옛 연결을 붙든 뿌리 (2026-10-14 운영에서 잡음) ───────────────────────────────────────────────
# 연결을 갈아 끼워도 손잡이가 13,800개에서 안 내려갔다. 브라우저 일꾼의 칸마다 아래로 따라가 보니 옛 연결에 닿는 칸은
# `_network_buffers` 하나였다 — 탭마다 받은 응답 40개를 적어 두는 칸인데, 탭이 닫혀도, 연결을 내려놓아도 안 비웠다.


class _FakePage:
    def __init__(self) -> None:
        self.handlers: dict[str, list[Any]] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def fire(self, event: str, *args: Any) -> None:
        for handler in self.handlers.get(event, []):
            handler(*args)


def test_a_closed_tab_lets_go_of_its_responses(tmp_path) -> None:
    worker = _worker(tmp_path)
    page = _FakePage()
    worker._watch_network(page)
    assert id(page) in worker._network_buffers

    page.fire("close", page)

    assert id(page) not in worker._network_buffers, "닫힌 탭의 응답을 붙들고 있다"


def test_a_new_tab_that_reuses_an_old_id_is_watched_again(tmp_path) -> None:
    worker = _worker(tmp_path)
    first = _FakePage()
    worker._watch_network(first)
    first.fire("close", first)
    # 같은 id 를 받은 새 탭을 흉내 낸다 — 닫힌 탭의 칸이 남아 있으면 「이미 감시 중」으로 읽혀 감시가 빠진다.
    worker._network_buffers.pop(id(first), None)
    second = _FakePage()
    worker._watch_network(second)
    assert "response" in second.handlers


def test_letting_go_of_the_connection_drops_every_buffer(tmp_path) -> None:
    worker = _worker(tmp_path)
    worker._watch_network(_FakePage())
    worker._context, worker._playwright, worker._connect_mode = None, None, "attached"

    worker._shutdown(keep_chrome=True)

    assert not worker.__dict__.get("_network_buffers"), "연결을 내려놓았는데 응답 기록이 남았다"
