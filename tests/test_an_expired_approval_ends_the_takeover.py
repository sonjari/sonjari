"""승인이 만료돼 잡이 취소되면 **이어받기도 끝난다** (2026-09-21, 이어받기 실전 재검증).

## 어떻게 찾았나

지난 세션이 이어받기를 실전에서 굴렸고 이어받기 #5 가 이렇게 남아 있었다:

    takeovers #5   status = continuing   (갱신 후 298분 경과)     ← 화석
    연결된 잡      status = cancelled · error = approval_expired

잡은 5시간 전에 끝났는데 이어받기는 **계속 「이어 작업 중」** 이다. 가지(`jarvis/takeover-5-…`)와 작업 폴더도 그대로 남았다.

## 왜

잡의 종료는 `JobRunner._notify_terminal` 이 리스너(이어받기의 `on_job_terminal`·알림)를 부르며 알린다. 그런데 **승인 만료**는
`JobStore.list_approvals()` 가 조회할 때 **직접 SQL 로** 잡을 취소한다 — 러너를 거치지 않으니 리스너가 영원히 안 불린다.
이어받기가 스스로 `git diff` 같은 읽기 셸 명령을 쓰는데(셸은 항상 승인 카드), 사람이 30분 안에 못 누르면 이 길로 죽는다.

## 고친 것

1. 만료로 취소된 잡도 종료 리스너를 부른다(`JobStore.on_jobs_expired` → `JobRunner._notify_terminal`).
2. 이미 화석이 된 `continuing` 행은 **시작할 때 정리**한다(`reconcile_takeovers`) — 끝난 잡에 매달린 이어받기를 검토 대기로 옮긴다.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import ApprovalStatus, JobRunner, JobStatus, JobStore


def _expired_approval(store: JobStore, *, job_id: str) -> None:
    store.create_approval(nonce="nonce-1", job_id=job_id, tool_name="local_run_shell",
                          arguments={"command": "git diff --stat"}, expires_at=time.time() - 5)


def _waiting_job(store: JobStore, payload: dict | None = None) -> dict:
    job = store.create_job("chat", "이어받기 · 가지에서 이어 작업", payload or {})
    store.claim_next()
    store.set_status(job["id"], JobStatus.WAITING_APPROVAL)
    return job


def test_an_expired_approval_still_cancels_the_job_as_before(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    job = _waiting_job(store)
    _expired_approval(store, job_id=job["id"])

    store.list_approvals(10)

    current = store.get_job(job["id"])
    assert current["status"] == JobStatus.CANCELLED.value and current["error"] == "approval_expired"


def test_the_store_tells_the_listener_which_jobs_it_cancelled(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    job = _waiting_job(store)
    _expired_approval(store, job_id=job["id"])
    told: list[list[str]] = []
    store.on_jobs_expired = lambda ids: told.append(list(ids))  # type: ignore[attr-defined]

    store.list_approvals(10)
    store.list_approvals(10)  # 두 번째 조회는 이미 끝난 일이다 — 다시 알리면 안 된다

    assert told == [[job["id"]]]


def test_a_job_that_was_not_waiting_is_not_reported(tmp_path: Path) -> None:
    """이미 다른 상태로 끝난 잡을 만료가 건드렸다고 알리면 거짓 알림이다."""
    store = JobStore(tmp_path / "jarvis.db")
    job = store.create_job("chat", "x", {})
    store.claim_next()
    store.set_status(job["id"], JobStatus.COMPLETED)
    _expired_approval(store, job_id=job["id"])
    told: list[list[str]] = []
    store.on_jobs_expired = lambda ids: told.append(list(ids))  # type: ignore[attr-defined]

    store.list_approvals(10)

    assert told == []
    assert store.get_job(job["id"])["status"] == JobStatus.COMPLETED.value


def test_a_failing_listener_never_breaks_the_listing(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    job = _waiting_job(store)
    _expired_approval(store, job_id=job["id"])

    def boom(_ids):  # noqa: ANN001
        raise RuntimeError("listener died")

    store.on_jobs_expired = boom  # type: ignore[attr-defined]

    assert isinstance(store.list_approvals(10), list)


def test_the_runner_routes_expiry_to_its_terminal_listeners(tmp_path: Path) -> None:
    """이어받기·알림이 붙어 있는 바로 그 리스너 — 만료가 그 길을 타야 화석이 안 생긴다."""
    store = JobStore(tmp_path / "jarvis.db")
    runner = JobRunner(store, EventBus())
    seen: list[dict] = []
    runner.add_terminal_listener(lambda job: seen.append(job))
    job = _waiting_job(store, {"takeover_id": 5})
    _expired_approval(store, job_id=job["id"])

    store.list_approvals(10)

    assert [row["id"] for row in seen] == [job["id"]]
    assert seen[0]["status"] == JobStatus.CANCELLED.value
    assert seen[0]["payload"]["takeover_id"] == 5, "이어받기가 어느 것인지 알아야 한다"


def test_reconcile_moves_a_fossil_takeover_to_review(tmp_path: Path) -> None:
    """이미 화석이 된 `continuing` 행은 시작할 때 정리한다."""
    from alture_jarvis.runtime import JarvisRuntime

    store = JobStore(tmp_path / "jarvis.db")
    fossil = store.create_job("chat", "이어받기", {"takeover_id": 5})
    store.claim_next()
    store.set_status(fossil["id"], JobStatus.CANCELLED, error="approval_expired")
    live = store.create_job("chat", "이어받기 진행 중", {"takeover_id": 6})
    store.claim_next()

    finished: list[dict] = []
    takeover = SimpleNamespace(
        list=lambda status="": {"items": [
            {"id": 5, "job_id": fossil["id"], "status": "continuing"},
            {"id": 6, "job_id": live["id"], "status": "continuing"},
            {"id": 7, "job_id": "", "status": "continuing"},
        ]},
        on_job_terminal=lambda job: finished.append(job),
    )
    runtime = SimpleNamespace(takeover=takeover, store=store)

    fixed = JarvisRuntime.reconcile_takeovers(runtime)

    assert fixed == 1
    assert [job["id"] for job in finished] == [fossil["id"]], "끝난 잡만 정리하고 아직 도는 것은 건드리지 않는다"


def test_the_pieces_are_wired() -> None:
    """만들어 놓고 부르는 자리가 없으면 아무 일도 안 일어난다."""
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    assert "on_jobs_expired" in inspect.getsource(JobRunner.__init__)
    assert "reconcile_takeovers()" in inspect.getsource(JarvisRuntime.start)
    assert ApprovalStatus.EXPIRED.value
