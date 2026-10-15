from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from .jobs import _decode, _json


# The statuses that mean "this work is already done, do not do it again".
# One tuple so a new settled status cannot be added without every commit site
# seeing it -- there are six of them.
SETTLED_STATUSES = ("committed", "duplicate")


class ExternalActionStore:
    """Persisted prepare -> approve -> commit store for external-write tools.

    Shares JobStore's sqlite file but owns an independent table. Approval
    (ToolGateway nonce, single-use) and commit-exactly-once (this store's
    prepared -> committing -> committed transition) are two separate guards:
    the nonce protects against replaying a chat/voice "approve", this store
    protects against a commit handler running twice (crash mid-commit, a
    replayed action_id, or a job re-running after restart).
    """

    def __init__(self, path: Path, *, dedupe_window_sec: int = 600) -> None:
        self.path = Path(path)
        self.dedupe_window_sec = max(0, int(dedupe_window_sec))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS external_actions (
                    action_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    result_json TEXT,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    used_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_external_actions_kind_status
                    ON external_actions(kind, status);
                CREATE INDEX IF NOT EXISTS idx_external_actions_expires
                    ON external_actions(status, expires_at);
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["payload"] = _decode(data.pop("payload_json", None), {})
        data["preview"] = _decode(data.pop("preview_json", None), {})
        data["result"] = _decode(data.pop("result_json", None), None)
        return data

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()

    def create_prepared_action(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        preview: dict[str, Any],
        ttl_sec: int,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        action_id = secrets.token_urlsafe(24)
        now = time.time()
        payload_hash = self._hash(payload)
        # The column existed from the start and was never written to -- always
        # "". So on 2026-08-20 one instruction produced two events 69 seconds
        # apart with an identical payload_hash, both committed, and nothing
        # objected. Deriving the key here is what makes the column mean
        # something; an explicit key from the caller still wins.
        key = idempotency_key or f"{kind}:{payload_hash}"
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO external_actions
                   (action_id, kind, payload_json, payload_hash, preview_json, status,
                    idempotency_key, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, 'prepared', ?, ?, ?)""",
                (
                    action_id,
                    kind,
                    _json(payload),
                    payload_hash,
                    _json(preview),
                    key,
                    now,
                    now + max(30, ttl_sec),
                ),
            )
        action = self.get_prepared_action(action_id)
        if action is None:
            raise RuntimeError("external_action_not_created")
        return action

    def get_prepared_action(self, action_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM external_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
        return self._row(row)

    def latest_prepared_of_kind(self, kind: str, *, now: float | None = None) -> dict[str, Any] | None:
        """Newest still-live prepared action of a kind, or None.

        Only ever safe for tiers that have no side effect. A commit tier must
        keep resolving the exact action_id it was given, because that id is
        what the approval nonce was issued against -- see NaverBlogTools.
        """
        now = now if now is not None else time.time()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM external_actions
                   WHERE kind = ? AND status = 'prepared' AND expires_at > ?
                   ORDER BY created_at DESC LIMIT 1""",
                (kind, now),
            ).fetchone()
        return self._row(row)

    def public_preview(self, action_id: str) -> dict[str, Any] | None:
        """UI-safe subset: never exposes payload or payload_hash."""
        action = self.get_prepared_action(action_id)
        if action is None:
            return None
        return {
            "action_id": action["action_id"],
            "kind": action["kind"],
            "preview": action["preview"],
            "status": action["status"],
            "created_at": action["created_at"],
            "expires_at": action["expires_at"],
        }

    def _committed_twin(
        self, conn: sqlite3.Connection, row: sqlite3.Row, action_id: str, now: float
    ) -> sqlite3.Row | None:
        """A DIFFERENT action that already committed the same thing, recently.

        `claim_for_commit` alone only ever protected one action_id from being
        committed twice. The 2026-08-20 double booking slipped past it because
        there were two action_ids: prepare ran twice (approval polling pressed
        it, but a human pressing the card twice does the same), and each id was
        claimable on its own.

        Empty keys never match each other -- every row written before this
        change has `idempotency_key = ''`, and treating those as equal would
        make any two commits of the same kind look like duplicates.
        """
        key = str(row["idempotency_key"] or "")
        if not key or self.dedupe_window_sec <= 0:
            return None
        return conn.execute(
            """SELECT action_id, result_json FROM external_actions
               WHERE kind = ? AND idempotency_key = ? AND idempotency_key != ''
                 AND status = 'committed' AND action_id != ?
                 AND used_at IS NOT NULL AND used_at > ?
               ORDER BY used_at DESC LIMIT 1""",
            (str(row["kind"]), key, action_id, now - self.dedupe_window_sec),
        ).fetchone()

    def claim_for_commit(self, action_id: str) -> dict[str, Any] | None:
        """Atomically transition prepared -> committing.

        Returns the action dict with an extra "claimed" bool that is True only
        when THIS call performed the prepared->committing transition. Callers
        must only execute the external side effect when claimed is True;
        a settled status ("committed", or "duplicate" for a twin caught here)
        means the work already happened and the cached result should be
        returned instead of re-executing.
        """
        now = time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM external_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            status = str(row["status"])
            claimed = False
            if status == "prepared" and float(row["expires_at"]) < now:
                conn.execute(
                    "UPDATE external_actions SET status = 'expired' WHERE action_id = ?",
                    (action_id,),
                )
            elif status == "prepared":
                twin = self._committed_twin(conn, row, action_id, now)
                if twin is not None:
                    # Adopt the twin's result so the caller answers with what
                    # really exists, and keep the ledger honest about which of
                    # the two ids did the work.
                    conn.execute(
                        """UPDATE external_actions
                           SET status = 'duplicate', result_json = ?, used_at = ?, error = ?
                           WHERE action_id = ?""",
                        (twin["result_json"], now, f"duplicate_of:{twin['action_id']}", action_id),
                    )
                else:
                    conn.execute(
                        """UPDATE external_actions SET status = 'committing', used_at = ?
                           WHERE action_id = ?""",
                        (now, action_id),
                    )
                    claimed = True
            conn.commit()
        finally:
            conn.close()
        action = self.get_prepared_action(action_id)
        if action is not None:
            action["claimed"] = claimed
        return action

    def _transition(
        self, action_id: str, status: str, *, result: Any = None, error: str = ""
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE external_actions SET status = ?, result_json = ?, error = ?
                   WHERE action_id = ? AND status = 'committing'""",
                (
                    status,
                    _json(result) if result is not None else None,
                    error[:2000],
                    action_id,
                ),
            )
        return self.get_prepared_action(action_id)

    def mark_committed(self, action_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
        return self._transition(action_id, "committed", result=result)

    def mark_failed(self, action_id: str, error: str) -> dict[str, Any] | None:
        return self._transition(action_id, "failed", error=error)

    def mark_unknown(self, action_id: str, error: str) -> dict[str, Any] | None:
        """Ambiguous outcome (e.g. network timeout after the request may have
        landed). Never auto-retried; a fresh prepare/action_id is required."""
        return self._transition(action_id, "unknown", error=error)

    def cleanup_expired(self, *, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE external_actions SET status = 'expired'
                   WHERE status = 'prepared' AND expires_at < ?""",
                (now,),
            ).rowcount
        return int(changed)
