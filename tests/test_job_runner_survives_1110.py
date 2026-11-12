"""11-10 맥 27시간 사고 — 일꾼이 오류 하나로 조용히 죽어 그 뒤의 일이 하나도 시작되지 않았다.

뿌리: 파일 열기 한도(맥 launchd 256)가 차 `claim_next` 의 DB 열기가 OperationalError → 받는 곳이 없어 스레드 사망.
/health 는 계속 ok. 여기서는 ① 바퀴의 오류에 안 죽음 ② 죽으면 감시가 다시 띄움 ③ 취소 뒤 안 끝나는 판은 버리고
새 일꾼 ④ 상태에 일꾼이 살았는지 실림 ⑤ 예약 일꾼도 같은 오류에 안 죽음 — 을 양방향으로 본다.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobRunner, JobStore
from alture_jarvis.models import JobStatus


def _wait(pred, sec: float = 5.0) -> bool:
    end = time.time() + sec
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _runner(tmp_path: Path) -> tuple[JobStore, JobRunner]:
    store = JobStore(tmp_path / "jarvis.db")
    runner = JobRunner(store, EventBus(), poll_sec=0.01)
    runner.WATCH_SEC = 0.05
    return store, runner


def test_a_db_error_in_claim_does_not_kill_the_runner(tmp_path: Path) -> None:
    store, runner = _runner(tmp_path)
    runner.register("chat", lambda job: {"answer": "ok"})
    real = store.claim_next
    fails = {"n": 2}

    def flaky():
        if fails["n"] > 0:
            fails["n"] -= 1
            raise sqlite3.OperationalError("unable to open database file")
        return real()

    store.claim_next = flaky  # type: ignore[method-assign]
    runner.start()
    try:
        job = store.create_job("chat", "after the error", {})
        assert _wait(lambda: (store.get_job(job["id"]) or {}).get("status") == JobStatus.COMPLETED.value)
        assert runner.health()["alive"] is True
        assert "OperationalError" in runner.health()["last_error"]
    finally:
        runner.stop()


def test_old_loop_shape_really_died_on_that_error() -> None:
    """양방향: 바퀴 보호가 없으면 같은 오류에 스레드가 죽는다(시험이 헛돌지 않는지)."""
    def old_run():
        raise sqlite3.OperationalError("unable to open database file")

    t = threading.Thread(target=old_run, daemon=True)
    t.start()
    t.join(2)
    assert not t.is_alive()


def test_the_watch_restarts_a_dead_runner(tmp_path: Path) -> None:
    store, runner = _runner(tmp_path)
    runner.register("chat", lambda job: {"answer": "ok"})
    runner._stop.clear()
    runner._thread = threading.Thread(target=lambda: None)  # 이미 끝난 스레드 = 죽은 일꾼
    runner._thread.start()
    runner._thread.join()
    assert runner.health()["alive"] is False
    assert runner.check() == "restarted"
    try:
        job = store.create_job("chat", "after restart", {})
        assert _wait(lambda: (store.get_job(job["id"]) or {}).get("status") == JobStatus.COMPLETED.value)
        assert runner.health()["restarts"] == 1
    finally:
        runner.stop()


def test_a_cancelled_job_that_never_returns_no_longer_blocks_the_queue(tmp_path: Path) -> None:
    store, runner = _runner(tmp_path)
    release = threading.Event()

    def handler(job):
        if job.get("title") == "hangs":
            release.wait(10)  # 글자가 안 나오는 구간 · 브라우저 동작처럼 멈춤을 못 듣는 기다림
        return {"answer": job.get("title")}

    runner.register("chat", handler)
    runner.start()
    try:
        stuck = store.create_job("chat", "hangs", {})
        assert _wait(lambda: (store.get_job(stuck["id"]) or {}).get("status") == JobStatus.RUNNING.value)
        store.cancel(stuck["id"])
        nxt = store.create_job("chat", "next", {})
        time.sleep(0.2)
        assert (store.get_job(nxt["id"]) or {})["status"] == JobStatus.QUEUED.value  # 아직 막혀 있다(예전 모습)
        assert runner.check() == ""  # 유예 시간 안에는 그대로
        assert runner.check(now=time.time() + runner.CANCEL_GRACE_SEC + 1) == "abandoned"
        assert _wait(lambda: (store.get_job(nxt["id"]) or {}).get("status") == JobStatus.COMPLETED.value)
        release.set()
        time.sleep(0.2)
        assert (store.get_job(stuck["id"]) or {})["status"] == JobStatus.CANCELLED.value  # 버린 판이 상태를 덮지 않는다
        assert runner.health()["abandoned"] == 1
    finally:
        release.set()
        runner.stop()


def test_a_running_job_that_was_not_cancelled_is_left_alone(tmp_path: Path) -> None:
    store, runner = _runner(tmp_path)
    release = threading.Event()
    runner.register("chat", lambda job: (release.wait(5), {"answer": "ok"})[1])
    runner.start()
    try:
        job = store.create_job("chat", "long but alive", {})
        assert _wait(lambda: (store.get_job(job["id"]) or {}).get("status") == JobStatus.RUNNING.value)
        assert runner.check(now=time.time() + 10_000) == ""  # 오래 걸려도 취소 안 했으면 버리지 않는다
    finally:
        release.set()
        runner.stop()


def test_scheduler_loop_survives_a_db_error(tmp_path: Path) -> None:
    from alture_jarvis import scheduler as sch

    class Fake(sch.ScheduleRunner if hasattr(sch, "ScheduleRunner") else object):
        pass

    cls = next(v for v in vars(sch).values() if isinstance(v, type) and hasattr(v, "_claim_due") and hasattr(v, "_run"))
    obj = cls.__new__(cls)
    obj._stop = threading.Event()
    obj._thread = None
    calls = {"n": 0}

    def claim():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise sqlite3.OperationalError("unable to open database file")
        obj._stop.set()
        return None

    obj._claim_due = claim
    obj._collect_delivered = lambda: None
    obj._stop.wait = lambda sec=None: obj._stop.is_set()  # 쉬지 않고 바로
    obj._run()
    assert calls["n"] == 3
    assert "OperationalError" in obj.last_error


def test_open_file_limit_helper_never_crashes() -> None:
    from alture_jarvis.__main__ import raise_open_file_limit

    out = raise_open_file_limit()
    assert out is None or (isinstance(out, tuple) and out[1] >= out[0])
