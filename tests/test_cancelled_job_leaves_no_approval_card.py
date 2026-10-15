"""취소한 판의 승인 카드는 남지 않는다 (2026-09-30 홈페이지 촬영 판).

앞 판이 「문서 만들기 — 승인」 카드 앞에서 멈춘 채 취소됐는데, 그 승인은 기다림으로 남아 **다음 판 위에 카드가 떠
있었다.** 촬영 스크립트가 그 카드를 눌렀고, 기록에는 **취소된 판이 「승인됨」** 으로 남았다(아무 일도 안 일어났다).
사람이었다면 「눌렀는데 왜 안 되지」가 됐다.
"""

from __future__ import annotations

import inspect
import time

from alture_jarvis.jobs import JobStore


def _parked_job(tmp_path) -> tuple[JobStore, str, str]:
    store = JobStore(tmp_path / "j.db")
    job = store.create_job("chat", "엑셀로 정리", {"prompt": "교보문고에서 파이썬 책 3권"})
    store.create_approval(nonce="n1", job_id=job["id"], tool_name="local_write_document",
                          arguments={"path": "책.xlsx"}, expires_at=time.time() + 1800)
    return store, job["id"], "n1"


def test_cancelling_the_job_expires_its_waiting_approval(tmp_path) -> None:
    store, job_id, nonce = _parked_job(tmp_path)

    assert store.cancel(job_id) is True

    assert store.get_approval(nonce)["status"] == "expired"
    assert store.list_approvals(10, "pending") == []


def test_pressing_the_stale_card_does_not_approve_a_dead_job(tmp_path) -> None:
    store, job_id, nonce = _parked_job(tmp_path)
    store.cancel(job_id)

    decision = store.decide_approval(nonce, True)

    assert decision["status"] == "expired"
    assert store.get_job(job_id)["status"] == "cancelled"


def test_the_screen_drops_the_card_when_its_job_ends() -> None:
    """화면 쪽 배선(소스에서 확인) — 끝난 판의 카드만 닫고, 다른 판의 카드는 두어야 한다."""
    from pathlib import Path

    app = (Path(__file__).resolve().parents[1] / "ui" / "src" / "WorkspaceApp.tsx").read_text(encoding="utf-8")
    assert "setApproval((current) => current?.job_id === jobId ? null : current);" in app
    assert "ApprovalStatus.EXPIRED.value, job_id, ApprovalStatus.PENDING.value" in inspect.getsource(JobStore.cancel)
