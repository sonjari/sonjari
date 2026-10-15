"""오래된 승인 대기 판은 재시작 뒤에 남지 않는다 (2026-10-01 시험판).

몇 시간 전에 승인 카드를 띄워 둔 판이 앱을 다시 켠 뒤에도 waiting_approval 로 남아 「새 대화」를 막았다.
재시작 정리(`recover_interrupted`)는 running 만 봤다. 같은 규칙(창 15분)으로 승인 대기도 접고, 그 카드도 닫는다.
"""

from __future__ import annotations

import time

from alture_jarvis.jobs import JobStore
from alture_jarvis.models import JobStatus


def test_an_old_approval_wait_is_folded_and_a_fresh_one_stays(tmp_path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    old = store.create_job("chat", "옛날", {"prompt": "몇 시간 전 판"})
    fresh = store.create_job("chat", "방금", {"prompt": "방금 판"})
    for job in (old, fresh):
        store.set_status(job["id"], JobStatus.WAITING_APPROVAL)
        store.create_approval(nonce=f"n-{job['id']}", job_id=job["id"], tool_name="local_write_file",
                              arguments={}, expires_at=time.time() + 24 * 3600)
    with store._connect() as conn:  # noqa: SLF001 — 시간을 되돌리는 것은 시험만 한다
        conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (time.time() - 3 * 3600, old["id"]))

    store.recover_interrupted()

    folded = store.get_job(old["id"])
    assert folded["status"] == "cancelled" and folded["error"] == "stale_after_restart"
    assert store.get_job(fresh["id"])["status"] == "waiting_approval"
    with store._connect() as conn:  # noqa: SLF001
        states = dict(conn.execute("SELECT job_id, status FROM approvals").fetchall())
    assert states[old["id"]] == "expired"
    assert states[fresh["id"]] == "pending"
