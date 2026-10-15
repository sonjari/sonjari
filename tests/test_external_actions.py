from __future__ import annotations

import time

from alture_jarvis.external_actions import ExternalActionStore
from alture_jarvis.jobs import JobStore


def _store(tmp_path) -> ExternalActionStore:
    return ExternalActionStore(tmp_path / "jarvis.db")


def test_create_and_get_round_trip(tmp_path):
    store = _store(tmp_path)
    action = store.create_prepared_action(
        kind="gmail_send",
        payload={"to": ["a@example.com"], "subject": "hi"},
        preview={"to": ["a@example.com"], "subject": "hi"},
        ttl_sec=300,
    )
    assert action["status"] == "prepared"
    assert action["kind"] == "gmail_send"
    fetched = store.get_prepared_action(action["action_id"])
    assert fetched is not None
    assert fetched["payload"] == {"to": ["a@example.com"], "subject": "hi"}
    assert fetched["payload_hash"]


def test_public_preview_excludes_payload_and_hash(tmp_path):
    store = _store(tmp_path)
    action = store.create_prepared_action(
        kind="calendar_create",
        payload={"secret_field": "should_not_leak"},
        preview={"summary": "회의"},
        ttl_sec=300,
    )
    preview = store.public_preview(action["action_id"])
    assert preview is not None
    assert preview["preview"] == {"summary": "회의"}
    assert "payload" not in preview
    assert "payload_hash" not in preview


def test_hash_is_stable_for_same_payload(tmp_path):
    store = _store(tmp_path)
    payload = {"b": 2, "a": 1}
    action1 = store.create_prepared_action(
        kind="gmail_send", payload=payload, preview={}, ttl_sec=300
    )
    action2 = store.create_prepared_action(
        kind="gmail_send", payload={"a": 1, "b": 2}, preview={}, ttl_sec=300
    )
    assert action1["payload_hash"] == action2["payload_hash"]


def test_claim_for_commit_exactly_once(tmp_path):
    store = _store(tmp_path)
    action = store.create_prepared_action(
        kind="gmail_send", payload={"to": ["a@example.com"]}, preview={}, ttl_sec=300
    )
    action_id = action["action_id"]

    first = store.claim_for_commit(action_id)
    assert first is not None
    assert first["claimed"] is True
    assert first["status"] == "committing"

    second = store.claim_for_commit(action_id)
    assert second is not None
    assert second["claimed"] is False
    assert second["status"] == "committing"


def test_claim_for_commit_missing_action_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store.claim_for_commit("does-not-exist") is None


def test_claim_for_commit_expired_returns_expired_status(tmp_path):
    store = _store(tmp_path)
    action = store.create_prepared_action(
        kind="gmail_send", payload={}, preview={}, ttl_sec=30
    )
    action_id = action["action_id"]
    claimed = store.claim_for_commit(action_id)
    assert claimed is not None and claimed["claimed"] is True
    # Force it back to a fresh "prepared" row in the past to exercise expiry.
    with store._connect() as conn:
        conn.execute(
            "UPDATE external_actions SET status = 'prepared', expires_at = ? WHERE action_id = ?",
            (time.time() - 5, action_id),
        )
    result = store.claim_for_commit(action_id)
    assert result is not None
    assert result["claimed"] is False
    assert result["status"] == "expired"


def test_mark_committed_then_reclaim_returns_cached_result(tmp_path):
    store = _store(tmp_path)
    action = store.create_prepared_action(
        kind="gmail_send", payload={}, preview={}, ttl_sec=300
    )
    action_id = action["action_id"]
    claimed = store.claim_for_commit(action_id)
    assert claimed["claimed"] is True
    store.mark_committed(action_id, {"message_id": "abc123"})

    reclaimed = store.claim_for_commit(action_id)
    assert reclaimed is not None
    assert reclaimed["claimed"] is False
    assert reclaimed["status"] == "committed"
    assert reclaimed["result"] == {"message_id": "abc123"}


def test_mark_failed_and_unknown(tmp_path):
    store = _store(tmp_path)
    for kind, marker in (("failed", "boom"), ("unknown", "timeout")):
        action = store.create_prepared_action(
            kind="gmail_send", payload={}, preview={}, ttl_sec=300
        )
        action_id = action["action_id"]
        store.claim_for_commit(action_id)
        if kind == "failed":
            result = store.mark_failed(action_id, marker)
        else:
            result = store.mark_unknown(action_id, marker)
        assert result is not None
        assert result["status"] == kind
        assert result["error"] == marker


def test_cleanup_expired(tmp_path):
    store = _store(tmp_path)
    action = store.create_prepared_action(
        kind="gmail_send", payload={}, preview={}, ttl_sec=30
    )
    with store._connect() as conn:
        conn.execute(
            "UPDATE external_actions SET expires_at = ? WHERE action_id = ?",
            (time.time() - 5, action["action_id"]),
        )
    changed = store.cleanup_expired()
    assert changed == 1
    fetched = store.get_prepared_action(action["action_id"])
    assert fetched["status"] == "expired"


def test_coexists_with_jobstore_in_same_sqlite_file(tmp_path):
    db_path = tmp_path / "jarvis.db"
    job_store = JobStore(db_path)
    action_store = ExternalActionStore(db_path)

    job = job_store.create_job("chat", "hello", {"prompt": "hi"})
    action = action_store.create_prepared_action(
        kind="gmail_send", payload={}, preview={}, ttl_sec=300
    )

    assert job_store.get_job(job["id"]) is not None
    assert action_store.get_prepared_action(action["action_id"]) is not None


def test_latest_prepared_of_kind_picks_the_newest_live_row_only(tmp_path):
    """Backs the plan-tier recovery in NaverBlogTools: the model retypes an
    action_id from chat history and gets it wrong, so the newest live plan of
    that kind has to be findable. Expired rows, other kinds and already
    committed rows must never be it."""
    store = _store(tmp_path)
    old = store.create_prepared_action(kind="naver_blog_post_plan", payload={"n": 1}, preview={}, ttl_sec=300)
    time.sleep(0.01)
    newest = store.create_prepared_action(kind="naver_blog_post_plan", payload={"n": 2}, preview={}, ttl_sec=300)
    store.create_prepared_action(kind="naver_blog_save_draft", payload={"n": 3}, preview={}, ttl_sec=300)

    found = store.latest_prepared_of_kind("naver_blog_post_plan")
    assert found is not None
    assert found["action_id"] == newest["action_id"]

    with store._connect() as conn:
        conn.execute(
            "UPDATE external_actions SET expires_at = ? WHERE action_id = ?",
            (time.time() - 5, newest["action_id"]),
        )
    assert store.latest_prepared_of_kind("naver_blog_post_plan")["action_id"] == old["action_id"]

    store.claim_for_commit(old["action_id"])
    store.mark_committed(old["action_id"], {"done": True})
    assert store.latest_prepared_of_kind("naver_blog_post_plan") is None


def test_latest_prepared_of_kind_returns_none_for_unknown_kind(tmp_path):
    assert _store(tmp_path).latest_prepared_of_kind("nothing_like_this") is None


# ---------------------------------------------------------------------------
# idempotency_key. The column shipped with the table and was never written to,
# so it was always "" -- on both sides. 2026-08-20 is what that cost.
# ---------------------------------------------------------------------------


def test_identical_payload_gets_the_same_key_and_a_different_one_does_not(tmp_path):
    store = _store(tmp_path)
    a = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    b = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    c = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "다른 회의"}, preview={}, ttl_sec=300
    )
    assert a["idempotency_key"]
    assert a["idempotency_key"] == b["idempotency_key"]
    assert a["idempotency_key"] != c["idempotency_key"]


def test_the_key_is_scoped_to_kind(tmp_path):
    """The same body sent as a draft and as a publish are different acts."""
    store = _store(tmp_path)
    draft = store.create_prepared_action(
        kind="naver_blog_save_draft", payload={"body": "x"}, preview={}, ttl_sec=300
    )
    publish = store.create_prepared_action(
        kind="naver_blog_publish", payload={"body": "x"}, preview={}, ttl_sec=300
    )
    assert draft["idempotency_key"] != publish["idempotency_key"]


def test_second_action_with_the_same_payload_cannot_be_claimed(tmp_path):
    store = _store(tmp_path)
    first = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    second = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    assert store.claim_for_commit(first["action_id"])["claimed"] is True
    store.mark_committed(first["action_id"], {"event_id": "evt-1"})

    twin = store.claim_for_commit(second["action_id"])
    assert twin["claimed"] is False
    assert twin["status"] == "duplicate"
    assert twin["result"] == {"event_id": "evt-1"}


def test_a_failed_first_attempt_does_not_block_the_second(tmp_path):
    """Only a *committed* twin counts. Retrying after a failure must work."""
    store = _store(tmp_path)
    first = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    second = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    store.claim_for_commit(first["action_id"])
    store.mark_failed(first["action_id"], "boom")
    assert store.claim_for_commit(second["action_id"])["claimed"] is True


def test_an_unknown_outcome_does_not_block_the_second_either(tmp_path):
    """`unknown` means the write may or may not have landed. Blocking there
    would strand the operator with no way to proceed; the store's existing rule
    is that a fresh prepare is required, and that must still be claimable."""
    store = _store(tmp_path)
    first = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    second = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    store.claim_for_commit(first["action_id"])
    store.mark_unknown(first["action_id"], "timeout")
    assert store.claim_for_commit(second["action_id"])["claimed"] is True


def test_rows_written_before_this_change_never_match_each_other(tmp_path):
    """★ Every pre-existing row has idempotency_key = ''. If empty matched
    empty, any two commits of the same kind would look like duplicates and the
    guard would start refusing real work on the live database."""
    store = _store(tmp_path)
    first = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "A"}, preview={}, ttl_sec=300
    )
    second = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "B"}, preview={}, ttl_sec=300
    )
    with store._connect() as conn:
        conn.execute("UPDATE external_actions SET idempotency_key = ''")

    store.claim_for_commit(first["action_id"])
    store.mark_committed(first["action_id"], {"event_id": "evt-old"})
    assert store.claim_for_commit(second["action_id"])["claimed"] is True


def test_dedupe_expires_so_a_genuine_repeat_is_possible_later(tmp_path):
    store = ExternalActionStore(tmp_path / "jarvis.db", dedupe_window_sec=60)
    first = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "주간 회의"}, preview={}, ttl_sec=300
    )
    store.claim_for_commit(first["action_id"])
    store.mark_committed(first["action_id"], {"event_id": "evt-1"})
    with store._connect() as conn:
        conn.execute(
            "UPDATE external_actions SET used_at = ? WHERE action_id = ?",
            (time.time() - 3600, first["action_id"]),
        )
    later = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "주간 회의"}, preview={}, ttl_sec=300
    )
    assert store.claim_for_commit(later["action_id"])["claimed"] is True


def test_window_of_zero_turns_the_guard_off(tmp_path):
    store = ExternalActionStore(tmp_path / "jarvis.db", dedupe_window_sec=0)
    first = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    second = store.create_prepared_action(
        kind="calendar_create", payload={"summary": "회의"}, preview={}, ttl_sec=300
    )
    store.claim_for_commit(first["action_id"])
    store.mark_committed(first["action_id"], {"event_id": "evt-1"})
    assert store.claim_for_commit(second["action_id"])["claimed"] is True


def test_an_explicit_key_from_the_caller_still_wins(tmp_path):
    store = _store(tmp_path)
    action = store.create_prepared_action(
        kind="calendar_create",
        payload={"summary": "회의"},
        preview={},
        ttl_sec=300,
        idempotency_key="caller-chosen",
    )
    assert action["idempotency_key"] == "caller-chosen"
