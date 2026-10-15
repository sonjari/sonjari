"""브라우저가 물리면 **줄 서지 말고 그 사실을 말한다.**

## 사용자님이 겪은 것 (2026-08-16)

사람인 로그인 화면이 로딩을 못 끝내고 멈췄다. 사람이 눌러도 반응이 없었고
(페이지 JS 가 초기화를 못 끝냈다), 그 사이 자비스의 `browser_tabs` 같은
**가벼운 호출까지 응답이 없었다.** 화면에는 아무 말도 안 나왔다 — 죽은 것처럼 보였다.

## 왜 그런가

브라우저 일꾼은 하나다(`max_workers=1`). 하나가 물리면 뒤에 오는 모든 호출이 그
뒤에 줄을 서고, 각자 자기 상한(180초)을 기다린다. **부를 때마다 3분씩 침묵**한다.
그리고 `cancel()` 은 이미 도는 작업을 못 멈추므로 여기서 풀 방법도 없다.

## 그래서 무엇을 바꿨나

풀 수 없으면 **기다리지 않고 말한다.** 3분 침묵보다 즉시 "브라우저가 앞 동작에
물려 있다"가 낫다 — 위층이 다른 길을 고를 수 있고, 사람에게도 할 말이 생긴다.
앞의 것이 끝나면 저절로 정상으로 돌아간다.
"""

from __future__ import annotations

import threading
import time

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "out",
            browser_task_timeout_sec=1,  # 시험에서 3분을 기다릴 수는 없다
        )
    )


def test_a_call_that_overruns_marks_the_worker_as_stuck(tmp_path) -> None:
    worker = _worker(tmp_path)
    release = threading.Event()

    with pytest.raises(RuntimeError, match="browser_action_timeout"):
        worker._submit(lambda: release.wait(30))

    assert worker._stuck_future is not None, "물린 사실을 안 적어 두면 다음 호출이 또 3분을 쓴다"
    release.set()


def test_the_next_call_does_not_queue_behind_it(tmp_path) -> None:
    """★ 이 시험이 핵심이다 — 다음 호출이 **기다리지 않고** 돌아와야 한다."""
    worker = _worker(tmp_path)
    release = threading.Event()
    with pytest.raises(RuntimeError, match="browser_action_timeout"):
        worker._submit(lambda: release.wait(30))

    started = time.monotonic()
    with pytest.raises(RuntimeError) as caught:
        worker._submit(lambda: "가벼운 호출")
    waited = time.monotonic() - started

    assert waited < 0.5, f"또 줄을 섰다({waited:.1f}초)"
    message = str(caught.value)
    assert "browser_busy_stuck" in message
    # ★ **언제 풀리는지**를 말한다. 예전 문구는 "사람이 F5 하면 풀린다"였는데,
    # 이제 자비스가 스스로 되살리므로 사람을 부를 일이 아니다 — 기다렸다 다시
    # 부르면 된다. 끝을 모르는 채로 기다리게 두는 것이 제일 나쁘다.
    assert "스스로 되살립니다" in message
    assert "조용히 기다리지 마세요" in message
    release.set()


def test_it_goes_back_to_normal_once_the_stuck_call_finishes(tmp_path) -> None:
    """물린 것이 풀리면 저절로 정상이다 — 사람이 뭘 안 해도 된다."""
    worker = _worker(tmp_path)
    release = threading.Event()
    with pytest.raises(RuntimeError, match="browser_action_timeout"):
        worker._submit(lambda: release.wait(30))

    release.set()
    for _ in range(50):  # 스레드가 실제로 끝나기를 잠깐 기다린다
        if worker._stuck_future.done():
            break
        time.sleep(0.05)

    assert worker._submit(lambda: "이제 된다") == "이제 된다"
    assert worker._stuck_future is None


def test_a_healthy_worker_is_untouched(tmp_path) -> None:
    worker = _worker(tmp_path)
    assert worker._submit(lambda: 7) == 7
    assert worker._stuck_future is None


def test_a_second_call_never_queues_while_the_first_is_still_within_its_deadline(tmp_path) -> None:
    """라이브에서 찾은 timeout **전** 사각지대.

    첫 호출이 아직 자기 상한 안에 있으면 ``_stuck_future`` 는 비어 있다. 예전 코드는
    이때 펌프와 health probe를 같은 단일 executor 뒤에 줄 세웠고, 그 보조 호출들이
    각자 timeout 나면서 실제 작업의 상태까지 덮었다. 바쁜 사실은 timeout 뒤가 아니라
    executor를 점유한 순간부터 막아야 한다.
    """
    worker = _worker(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    first_result: list[bool] = []

    def first_call() -> None:
        first_result.append(
            worker._submit(
                lambda: entered.set() or release.wait(10),
                timeout=10,
                operation="browser_open",
            )
        )

    thread = threading.Thread(target=first_call)
    thread.start()
    assert entered.wait(2), "첫 작업이 executor에 들어가지 않았다"

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="browser_busy_active"):
        worker._submit(lambda: "뒤 호출", timeout=5, operation="browser_tabs")
    assert time.monotonic() - started < 0.5, "timeout 전 후속 호출이 executor 뒤에 줄을 섰다"

    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert first_result == [True]


def test_health_uses_cached_browser_state_while_an_operation_is_active(tmp_path) -> None:
    """UI health는 브라우저 작업보다 먼저 살아 있어야 한다."""
    worker = _worker(tmp_path)
    worker._connected = True
    entered = threading.Event()
    release = threading.Event()

    thread = threading.Thread(
        target=lambda: worker._submit(
            lambda: entered.set() or release.wait(10),
            timeout=10,
            operation="browser_open",
        )
    )
    thread.start()
    assert entered.wait(2)

    started = time.monotonic()
    status = worker.status()
    assert time.monotonic() - started < 0.5, "health probe가 실행 중인 브라우저 뒤에 줄을 섰다"
    assert status["liveness"] == "cached"
    assert status["active_operation"]["name"] == "browser_open"

    release.set()
    thread.join(timeout=2)


def test_foreground_waits_for_a_short_background_pump_instead_of_failing(tmp_path) -> None:
    """250ms CDP pump는 사용자 작업을 실패시킬 이유가 아니다."""
    worker = _worker(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    thread = threading.Thread(
        target=lambda: worker._submit(
            lambda: entered.set() or release.wait(0.2),
            timeout=2,
            operation="browser_pump",
            background=True,
        )
    )
    thread.start()
    assert entered.wait(1)

    started = time.monotonic()
    assert worker._submit(lambda: "foreground", operation="browser_snapshot") == "foreground"
    waited = time.monotonic() - started

    assert waited < 0.75, f"짧은 펌프를 양보시키지 못했다({waited:.2f}초)"
    thread.join(timeout=1)


def test_background_probe_never_queues_behind_foreground_work(tmp_path) -> None:
    """health/pump가 긴 사용자 작업 뒤에 들어가 상태를 덮으면 안 된다."""
    worker = _worker(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    thread = threading.Thread(
        target=lambda: worker._submit(
            lambda: entered.set() or release.wait(10),
            timeout=10,
            operation="browser_open",
        )
    )
    thread.start()
    assert entered.wait(1)

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="browser_busy_active"):
        worker._submit(
            lambda: "probe",
            timeout=3,
            operation="browser_health_probe",
            background=True,
        )
    assert time.monotonic() - started < 0.2

    release.set()
    thread.join(timeout=1)


# ── 스스로 되살아난다 ────────────────────────────────────────────────────────


def _fast_recover(tmp_path):
    """5초만에 회복을 시도하는 워커(시험에서 60초를 기다릴 수는 없다)."""
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "out",
            browser_task_timeout_sec=1,
            browser_stuck_recover_after_sec=5,  # 아래 max(5, …) 의 바닥값
        )
    )


def test_it_revives_itself_instead_of_waiting_forever(tmp_path) -> None:
    """★ 오늘 사람이 세 번 손으로 한 일을, 자비스가 스스로 한다.

    실측(2026-08-16): 한 번 물리면 3분이 지나도 안 풀렸다 — 느린 것이 아니라
    영영 안 끝나는 것이었다. 기다리는 것은 답이 아니다.
    """
    worker = _fast_recover(tmp_path)
    release = threading.Event()
    with pytest.raises(RuntimeError, match="browser_action_timeout"):
        worker._submit(lambda: release.wait(60))
    old_executor = worker._executor

    worker._stuck_since = time.time() - 10  # 회복 시각이 지난 것으로 만든다
    assert worker._submit(lambda: "새 일꾼에서 돈다") == "새 일꾼에서 돈다"

    assert worker._executor is not old_executor, "일꾼을 안 갈았다"
    assert worker._recoveries == 1
    assert worker._stuck_future is None
    release.set()


def test_recovery_does_not_touch_the_wedged_connection(tmp_path) -> None:
    """★ `_shutdown()` 을 부르면 `context.close()` 가 **물린 그 연결**을 건드려
    새 스레드까지 같이 물린다. 회복하려다 회복 경로를 잃는 것이 제일 나쁘다.

    그래서 낡은 것은 **참조만 버린다**(닫지 않는다).
    """
    worker = _fast_recover(tmp_path)
    closed: list[str] = []

    class _WouldWedge:
        def close(self):
            closed.append("context")
            raise AssertionError("물린 연결을 건드렸다")

    worker._context = _WouldWedge()
    worker._playwright = _WouldWedge()

    worker._recover_from_stuck(waited=99)

    assert closed == [], "낡은 연결을 **이 스레드에서** 닫으려 했다 — 그러면 새 스레드도 물린다"
    assert worker._context is None and worker._playwright is None


def test_the_old_playwright_is_handed_to_the_doomed_thread(tmp_path) -> None:
    """★ 버리기만 하면 안 된다 (2026-08-16 실측).

    참조만 끊었더니 한 프로세스에 sync playwright 가 둘 살아 있게 됐고, 다음 시작이
    "Playwright Sync API inside the asyncio loop" 로 죽는 것을 봤다.

    그렇다고 여기서 `stop()` 을 부르면 물린 연결을 건드려 이 스레드까지 물린다.
    그래서 **정리를 죽은 쪽에 맡긴다** — 어차피 잃은 스레드이고, 우리는 안 기다린다.
    """
    worker = _fast_recover(tmp_path)
    stopped: list[str] = []

    class _OldPlaywright:
        def stop(self):
            stopped.append("stop")

    worker._playwright = _OldPlaywright()
    old_executor = worker._executor

    worker._recover_from_stuck(waited=99)

    old_executor.shutdown(wait=True)  # 죽은 쪽이 실제로 정리하는지 본다
    assert stopped == ["stop"], "낡은 playwright 를 아무도 안 닫았다"
    assert worker._playwright is None


def test_the_count_is_visible(tmp_path) -> None:
    """회복이 잦아지면 원인을 봐야 한다 — 안 세면 조용히 잦아진다."""
    worker = _fast_recover(tmp_path)
    worker._recover_from_stuck(waited=77)
    assert worker._recoveries == 1
    assert worker._last_recovery["stuck_sec"] == 77


def test_stuck_status_names_the_exact_operation_and_deadline(tmp_path) -> None:
    worker = _worker(tmp_path)
    release = threading.Event()

    with pytest.raises(RuntimeError, match="browser_action_timeout"):
        worker._submit(
            lambda: release.wait(30),
            operation="browser_click_confirmed",
            mutating=True,
        )

    status = worker.status()
    active = status["active_operation"]
    assert active["name"] == "browser_click_confirmed"
    assert active["mutating"] is True
    assert active["state"] == "timed_out_running"
    assert active["phase"] == "awaiting_late_completion"
    assert active["deadline_at"] >= active["started_at"]
    assert status["last_timeout"]["id"] == active["id"]
    release.set()


def test_a_late_result_from_an_abandoned_epoch_is_discarded(tmp_path) -> None:
    worker = _fast_recover(tmp_path)
    release = threading.Event()
    with pytest.raises(RuntimeError, match="browser_action_timeout"):
        worker._submit(
            lambda: release.wait(60),
            operation="browser_fill",
            mutating=True,
        )

    worker._stuck_since = time.time() - 10
    assert worker._submit(lambda: "fresh", operation="browser_tabs") == "fresh"
    assert worker._epoch == 1

    release.set()
    for _ in range(50):
        if worker._last_late_completion:
            break
        time.sleep(0.05)
    assert worker._last_late_completion["name"] == "browser_fill"
    assert worker._last_late_completion["epoch"] == 0


def test_three_recoveries_open_a_short_circuit_instead_of_retry_storming(tmp_path) -> None:
    worker = _fast_recover(tmp_path)
    worker._recover_from_stuck(waited=61)
    worker._recover_from_stuck(waited=62)
    worker._recover_from_stuck(waited=63)

    assert worker._circuit_open_until > time.time()
    with pytest.raises(RuntimeError, match="browser_circuit_open") as caught:
        worker._submit(lambda: "네 번째 자동 시도")
    assert "자동 재시도하지 않았습니다" in str(caught.value)


def test_two_hundred_calls_never_queue_or_duplicate_a_timed_out_mutation(tmp_path) -> None:
    worker = _worker(tmp_path)
    release = threading.Event()
    attempted: list[int] = []
    with pytest.raises(RuntimeError, match="browser_action_timeout"):
        worker._submit(
            lambda: release.wait(30),
            operation="browser_click_confirmed",
            mutating=True,
        )

    executor = worker._executor
    started = time.monotonic()
    for index in range(200):
        with pytest.raises(RuntimeError, match="browser_busy_stuck"):
            worker._submit(
                lambda i=index: attempted.append(i),
                operation="browser_click_confirmed",
                mutating=True,
            )

    assert time.monotonic() - started < 1.0
    assert attempted == []
    assert worker._executor is executor
    release.set()


# ── 놀고 있을 때도 이벤트를 돌린다 ───────────────────────────────────────────
#
# 2026-08-16 라이브로 증명한 자리다:
#
#     자비스 놀고 있음  -> 사람이 연 구글 로그인 팝업이 about:blank 에서 죽음
#     자비스 바쁨(20초)  -> 같은 버튼에 팝업이 정상으로 뜸
#
# 플레이라이트 동기 API 는 **호출이 도는 동안에만** CDP 이벤트를 처리하는데,
# CDP 로 붙으면 새 창은 "디버거가 붙을 때까지 멈춤"으로 태어난다. 자비스가 조용하면
# 그 멈춤을 풀어 줄 사람이 없다. 사용자님이 아침 내내 "로그인이 안 된다"고 한 것의
# 진짜 원인이 이것이다 — 사람이 못 누른 게 아니라 자비스가 조용해서 창이 안 열렸다.


class _Page:
    def __init__(self) -> None:
        self.waits: list[int] = []

    def is_closed(self):
        return False

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


def test_the_pump_turns_the_loop_while_idle(tmp_path) -> None:
    worker = _worker(tmp_path)
    page = _Page()
    worker._page = page
    worker._pump_once()
    assert page.waits == [worker._PUMP_MS], "기다리는 호출이 곧 펌프다"


def test_the_pump_is_quiet_when_there_is_no_page(tmp_path) -> None:
    worker = _worker(tmp_path)
    worker._page = None
    worker._pump_once()  # 터지지 않으면 된다


def test_the_pump_starts_and_stops_with_the_browser(tmp_path) -> None:
    worker = _worker(tmp_path)
    worker._start_pump()
    assert worker._pump_thread is not None and worker._pump_thread.is_alive()
    worker._start_pump()  # 두 번 불러도 하나만 돈다
    assert threading.active_count() >= 1

    worker._pump_stop.set()
    worker._pump_thread.join(timeout=3)
    assert not worker._pump_thread.is_alive(), "내려갈 때 멈춰야 한다"


def test_the_pump_does_not_fight_recovery(tmp_path) -> None:
    """물려 있으면 `_submit` 이 즉시 거절한다 — 박동이 회복을 방해하면 안 된다."""
    worker = _worker(tmp_path)
    release = threading.Event()
    with pytest.raises(RuntimeError, match="browser_action_timeout"):
        worker._submit(lambda: release.wait(30))

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="browser_busy_stuck"):
        worker._submit(worker._pump_once, 5)
    assert time.monotonic() - started < 0.5, "박동이 줄을 섰다"
    release.set()


def test_attached_navigation_opens_a_reconnect_budget_without_touching_chrome(tmp_path) -> None:
    worker = BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "out",
            browser_reconnect_after_navigations=2,
        )
    )

    class _Page:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def goto(self, url, *, wait_until):
            self.urls.append(url)
            return {"url": url, "wait_until": wait_until}

    page = _Page()
    worker._connect_mode = "attached"
    worker._goto_page(page, "https://one.test/", wait_until="domcontentloaded")
    assert worker._reconnect_pending is False
    worker._goto_page(page, "https://two.test/", wait_until="domcontentloaded")

    assert worker._reconnect_pending is True
    assert worker._navigation_count == 2
    assert page.urls == ["https://one.test/", "https://two.test/"]


def test_reconnect_collects_the_closed_playwright_generation_before_starting_next(
    tmp_path, monkeypatch
) -> None:
    import weakref

    worker = _worker(tmp_path)
    order: list[str] = []

    class _Page:
        url = "https://example.test/"

        def is_closed(self):
            return False

    worker._connect_mode = "attached"
    worker._page = _Page()
    old_page = weakref.ref(worker._page)
    worker._navigation_count = 50

    def shutdown(*, keep_chrome: bool = False):
        order.append("shutdown")
        worker._page = None

    worker._shutdown = shutdown  # type: ignore[method-assign]
    worker._ensure_started = lambda: order.append("start")  # type: ignore[method-assign]

    def collect():
        order.append("gc")
        assert old_page() is None, "재연결 지역변수가 옛 Page를 쥔 채 수거를 불렀다"

    monkeypatch.setattr("alture_jarvis.browser.gc.collect", collect)

    worker._reconnect_attached()

    assert order == ["shutdown", "gc", "start"]
    assert worker._reconnections == 1


def test_a_restarted_pump_uses_a_fresh_stop_event(tmp_path) -> None:
    worker = _worker(tmp_path)
    worker._start_pump()
    old_event = worker._pump_stop
    old_thread = worker._pump_thread
    old_event.set()

    worker._start_pump()

    assert worker._pump_stop is not old_event
    assert worker._pump_thread is not old_thread
    worker._pump_stop.set()
    if old_thread:
        old_thread.join(timeout=3)
    if worker._pump_thread:
        worker._pump_thread.join(timeout=3)


def test_a_nameless_internal_call_names_its_caller(tmp_path) -> None:
    """이름 없는 내부 동작이 막으면 **누가** 막았는지 메시지에 나와야 한다 (2026-10-01).

    네이버 서치어드바이저 판: 로그인 버튼을 누른 직후 다음 걸음 둘이 「앞 동작(browser_internal)을 0초째」로
    거절됐는데, 이름 없이 부르는 자리가 열 곳이 넘어 범인을 못 찾았다.
    """
    worker = _worker(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def wall_like_caller() -> None:
        worker._submit(lambda: entered.set() or release.wait(10), timeout=10)

    thread = threading.Thread(target=wall_like_caller)
    thread.start()
    assert entered.wait(2)
    with pytest.raises(RuntimeError, match=r"browser_internal:wall_like_caller"):
        worker._submit(lambda: "뒤 호출", timeout=5, operation="browser_tabs")
    release.set()
    thread.join(timeout=2)
