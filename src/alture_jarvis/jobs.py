from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import store_owner
from .config import axis_build_ids, build_id
from .events import EventBus
from .models import ApprovalStatus, JobStatus, RiskLevel
from .sqlite_schema import add_column_if_missing


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decode(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class JobStore:
    def __init__(self, path: Path, *, owner: bool = False) -> None:
        self.path = Path(path)
        # 돌고 있는 설치본의 DB 를 다른 프로세스가 여는 것을 여기서 거절한다 — 폴더도 파일도 건드리기 **전에**.
        #   서버(`owner=True`)는 늘 지나가고, 연 뒤에 주인 자리를 적는다. 까닭과 좁힌 조건은 `store_owner` 머리말에.
        store_owner.admit(self.path, owner=owner)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 승인 만료로 **저장소가 직접** 취소한 잡을 알릴 곳. 러너의 종료 리스너(이어받기·알림)에 이어 붙는다 —
        # 안 그러면 만료로 끝난 잡은 아무도 모른다(이어받기 #5 가 5시간 째 「이어 작업 중」으로 남았다, 2026-09-21).
        self.on_jobs_expired: Callable[[list[str]], None] | None = None
        self._init_db()
        if owner:
            with self._connect() as conn:
                store_owner.claim(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk_level INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    -- 이 잡을 돌린 코드의 지문. 위임률(L4)을 판별로 갈라 보려면
                    -- 도구 실적뿐 아니라 **잡**에도 판이 붙어 있어야 한다.
                    build TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                    ON jobs(status, created_at);

                CREATE TABLE IF NOT EXISTS approvals (
                    nonce TEXT PRIMARY KEY,
                    job_id TEXT,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    proof_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    consumed_at REAL,
                    answer TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_status_expires
                    ON approvals(status, expires_at);

                -- `build` 는 이 줄을 남긴 **코드의 지문**이다(config.build_id).
                -- 빈 문자열은 이 칸이 생기기 전(2026-08-13 이전)에 쌓인 줄이라는 뜻이고,
                -- 눈금은 그것을 "판을 모르는 표본"으로 따로 센다.
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    subject_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    build TEXT NOT NULL DEFAULT ''
                );

                -- 방금 한 일을 되돌릴 손잡이. 승인(approvals)과 짝을 이룬다:
                -- 승인은 **하기 전에** 묻는 것이고, 이건 **한 뒤에** 무를 수 있게
                -- 남기는 것이다. 되돌릴 수 있으면 미리 묻지 않아도 되므로, 이 표가
                -- 채워질수록 승인 카드는 줄어든다.
                -- 판(build) 하나가 **축별로 어떤 지문이었는지** 적어 둔다.
                --
                -- `build` 는 패키지 전체 해시라 화면 한 줄만 고쳐도 바뀐다. 그래서
                -- 「지금 판만」 표본이 늘 0~4 건이었다(2026-08-21 실측: 3일치 128건이
                -- 판 29종에 흩어짐). 축별 지문을 같이 남겨 두면, 조사 성능은
                -- `browser.py`·`agent.py` 가 안 바뀐 **여러 판을 묶어** 볼 수 있다.
                --
                -- 판마다 한 줄. 기동 때 한 번 쓰고 만다.
                CREATE TABLE IF NOT EXISTS build_manifest (
                    build TEXT PRIMARY KEY,
                    axes_json TEXT NOT NULL,
                    first_seen REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS undo_offers (
                    undo_id TEXT PRIMARY KEY,
                    tool TEXT NOT NULL,
                    job_id TEXT NOT NULL DEFAULT '',
                    label TEXT NOT NULL DEFAULT '',
                    handle_json TEXT NOT NULL DEFAULT '{}',
                    manual_hint TEXT NOT NULL DEFAULT '',
                    automatic INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'live',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_undo_offers_live
                    ON undo_offers(status, expires_at);

                -- 그 절차의 역동작이 **실제로 성공한 적이 있는가.**
                --
                -- ★ 이 표가 왜 레시피 파일이 아니라 여기 있나 (2026-08-15).
                --
                -- 레시피는 손자리가 스스로 초안을 쓴다. 그러니 "나 되돌릴 수 있으니
                -- 승인 빼줘"를 레시피가 적을 수 있으면, 그건 **손자리가 자기 승인
                -- 등급을 쓰는 것**이다. `_approved` 인자로 뚫려 있던 구멍과 같은
                -- 모양이고, `dynamic_risk` 를 "올리기만" 하도록 만든 이유이기도 하다.
                --
                -- 그래서 강등의 근거는 **주장이 아니라 실적**이다. 되돌리기가 진짜로
                -- 돌아서 증거까지 읽은 적이 있을 때만 이 표에 한 줄이 생기고,
                -- 그 줄이 있을 때만 L2 를 안 올린다(바닥 L1 은 등록이 계속 지킨다).
                --
                -- fingerprint 는 그 절차와 그것이 쓰는 셀렉터·주소를 함께 해싱한 값이다.
                -- 레시피가 바뀌면 지문이 달라져 **옛 실적이 새 절차를 덮지 못한다** —
                -- 같은 이름으로 다른 일을 하게 만드는 것이 제일 쉬운 우회로다.
                CREATE TABLE IF NOT EXISTS recipe_inverse_proofs (
                    site TEXT NOT NULL,
                    action TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    undo_id TEXT NOT NULL DEFAULT '',
                    verified_at REAL NOT NULL,
                    PRIMARY KEY (site, action)
                );

                -- 어느 사이트에서 몇 번 막혔는가. **레시피를 어디에 쓸지 정하는 근거다.**
                --
                -- 레시피는 자율이 저절로 늘어나는 유일한 축인데(사람이 한 번 뚫으면
                -- 다음부터 안 막힌다), 지금 recipes/ 에는 naver_blog 하나뿐이다.
                -- 무엇을 쓸지 모르기 때문이고, 무엇을 쓸지 모르는 이유는 어디서
                -- 아픈지 아무도 안 세고 있었기 때문이다.
                CREATE TABLE IF NOT EXISTS site_friction (
                    host TEXT NOT NULL,
                    code TEXT NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 0,
                    last_url TEXT NOT NULL DEFAULT '',
                    last_goal TEXT NOT NULL DEFAULT '',
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    PRIMARY KEY (host, code)
                );

                CREATE TABLE IF NOT EXISTS agent_checkpoints (
                    job_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                """
            )
            # 이미 있는 DB 에는 `CREATE TABLE IF NOT EXISTS` 가 칸을 안 붙인다.
            # 옛 줄은 build 가 빈 문자열로 남고, 그게 "판을 모르는 표본"이라는 뜻이다.
            # ★ 확인과 추가는 한 문으로(`sqlite_schema.py`) — 같은 새 DB 를 둘이 동시에 열어도 죽지 않는다.
            for table in ("audit_log", "jobs"):
                add_column_if_missing(conn, table, "build", "TEXT NOT NULL DEFAULT ''")
            add_column_if_missing(conn, "approvals", "proof_json", "TEXT NOT NULL DEFAULT '{}'")
            # 질문 카드(`ask_user`)에서 사람이 고른 답. 승인·거절만 있던 틀에 **말 한 줄**을 싣는다(2026-09-30).
            add_column_if_missing(conn, "approvals", "answer", "TEXT")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        if "payload_json" in data:
            data["payload"] = _decode(data.pop("payload_json"), {})
        if "result_json" in data:
            data["result"] = _decode(data.pop("result_json"), None)
        if "arguments_json" in data:
            data["arguments"] = _decode(data.pop("arguments_json"), {})
        if "proof_json" in data:
            data["proof"] = _decode(data.pop("proof_json"), {})
        if "risk_level" in data:
            data["risk_level"] = RiskLevel.parse(data["risk_level"]).label()
        return data

    def create_job(
        self,
        kind: str,
        title: str,
        payload: dict[str, Any],
        risk_level: RiskLevel = RiskLevel.L0,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO jobs
                   (id, kind, title, payload_json, status, risk_level, created_at, updated_at, build)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id, kind, title, _json(payload), JobStatus.QUEUED.value,
                    int(risk_level), now, now, build_id(),
                ),
            )
        return self.get_job(job_id) or {}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row(row)

    def list_jobs(self, limit: int = 50, status: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row(row) or {} for row in rows]

    # 화면이 목록에 쓰는 것만 담은 줄. **본문(payload·result)을 싣지 않는다.**
    #
    # ★ 재기 전에 짐작하지 않았다 (2026-08-19 실측). `/v1/jobs?limit=50` 이 지금
    # **455KB** 다. 그중 payload 는 다 합쳐 18KB 뿐이고 **299KB 가 result_json**
    # 이었다 — 답변 전문과 도구 걸음 전부가 목록에 실려 나가고 있었다. 목록은
    # 한 줄에 제목·상태·소요·걸음수만 그리므로 그 전부가 버려진다.
    #
    # 첨부가 있는 잡이면 더 나쁘다: `payload.attachments[].data_base64` 가
    # 그대로 들어 있어서(한 개 상한 48MB) 목록 한 번이 수백 MB 가 될 수 있다.
    # 지금 DB 에 그런 줄이 0개라 안 터졌을 뿐이다. 사고 N 과 같은 모양이라
    # 여기서 막는다 — 목록은 미리보기만, 본문은 고를 때 따로.
    _SUMMARY_SQL = """
        SELECT id, kind, title, status, risk_level, error, created_at, updated_at,
               started_at, finished_at, attempts, build,
               COALESCE(json_extract(payload_json, '$.session_id'), '') AS session_id,
               COALESCE(json_extract(payload_json, '$.origin'), '')     AS origin,
               -- 그 판이 어느 모드로 · 어느 폴더에서 도는가. 바깥 AI 가 맡긴 판은 사람이 화면에서 고른 것과 다르다(2026-10-09).
               COALESCE(json_extract(payload_json, '$.workspace_mode'), '') AS workspace_mode,
               COALESCE(substr(json_extract(payload_json, '$.code_workspace'), 1, 400), '') AS code_workspace,
               COALESCE(json_array_length(result_json, '$.agent_trace.steps'), 0) AS steps,
               COALESCE(json_extract(result_json, '$.completion_state'), '') AS completion_state
        FROM jobs
    """

    def list_job_summaries(self, limit: int = 50, status: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        query = self._SUMMARY_SQL + (" WHERE status = ?" if status else "")
        query += " ORDER BY created_at DESC LIMIT ?"
        params: tuple[Any, ...] = (status, limit) if status else (limit,)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["risk_level"] = RiskLevel.parse(data["risk_level"]).label()
            out.append(data)
        return out

    def claim_next(self) -> dict[str, Any] | None:
        now = time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # ★ 사람이 시킨 일이 바깥 AI 가 맡긴 일보다 먼저다 (2026-10-09). 맡긴 코드 일은 시간 제한 없이 끝까지 간다 —
            #   그 뒤에 사람의 요청이 줄을 서면 30분을 기다린다. 줄에 둘이 같이 있으면 사람 것을 먼저 꺼낸다.
            #   같은 쪽끼리는 지금까지처럼 들어온 순서다. (줄은 짧다 — 손자리는 한 번에 한 판이다.)
            rows = conn.execute(
                "SELECT id, payload_json FROM jobs WHERE status = ? ORDER BY created_at",
                (JobStatus.QUEUED.value,),
            ).fetchall()
            row = next((item for item in rows if not _delegated_payload(item["payload_json"])), rows[0] if rows else None)
            if not row:
                conn.rollback()
                return None
            job_id = str(row["id"])
            updated = conn.execute(
                """UPDATE jobs SET status = ?, started_at = ?, updated_at = ?, attempts = attempts + 1
                   WHERE id = ? AND status = ?""",
                (JobStatus.RUNNING.value, now, now, job_id, JobStatus.QUEUED.value),
            ).rowcount
            if updated != 1:
                conn.rollback()
                return None
            conn.commit()
        finally:
            conn.close()
        return self.get_job(job_id)

    def person_is_waiting(self) -> bool:
        """줄에 **바깥 AI 가 맡긴 일이 아닌 것**이 서 있는가 — 돌고 있는 맡긴 판이 비켜 줄지 정할 때 묻는다."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM jobs WHERE status = ?", (JobStatus.QUEUED.value,)
            ).fetchall()
        return any(not _delegated_payload(row["payload_json"]) for row in rows)

    def requeue_yielded(self, job_id: str) -> bool:
        """비켜 준 판을 다시 줄에 세운다. 돌고 있던 판만 — 그 사이 멈춘(취소된) 판은 건드리지 않는다."""
        now = time.time()
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ?, error = '' WHERE id = ? AND status = ?",
                (JobStatus.QUEUED.value, now, job_id, JobStatus.RUNNING.value),
            ).rowcount
        return changed == 1

    def attach_result(self, job_id: str, result: Any) -> None:
        """상태는 그대로 두고 **결과만** 붙인다.

        실패하려는 판이 "여기까지 갔다"를 남기는 자리다. 상태를 안 건드리므로
        곧이어 도는 러너의 `set_status(FAILED, ...)` 와 싸우지 않는다.
        """
        if result is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET result_json = ?, updated_at = ? WHERE id = ?",
                (_json(result), time.time(), job_id),
            )

    def set_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: Any = None,
        error: str = "",
    ) -> dict[str, Any] | None:
        now = time.time()
        finished_at = now if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED} else None
        with self._connect() as conn:
            conn.execute(
                # ★ `result=None` 은 "지워라"가 아니라 **"건드리지 마라"**다 (2026-08-29).
                #
                # 실패 경로가 `set_status(FAILED, error=...)` 로 끝나는데, 예전에는
                # 그때 result_json 이 NULL 로 덮여 **그 판이 어디까지 갔는지가 통째로
                # 사라졌다.** 관찰 초소 6건이 600초에 죽었을 때 걸음을 못 봐서
                # 원인을 못 찾았다(그리고 없는 걸 `0걸음`으로 오독했다 — 벤치에서
                # 이미 한 번 고친 그 거짓말이다).
                #
                # 이제 실패 직전에 `attach_result` 로 붙여 둔 부분 장부가 살아남는다.
                """UPDATE jobs SET status = ?, result_json = COALESCE(?, result_json),
                   error = ?, updated_at = ?, finished_at = ?
                   WHERE id = ?""",
                (status.value, _json(result) if result is not None else None, error[:2000], now, finished_at, job_id),
            )
        return self.get_job(job_id)

    def cancel(self, job_id: str) -> bool:
        now = time.time()
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE jobs SET status = ?, updated_at = ?, finished_at = ?
                   WHERE id = ? AND status IN (?, ?, ?, ?)""",
                (
                    JobStatus.CANCELLED.value,
                    now,
                    now,
                    job_id,
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.WAITING_APPROVAL.value,
                    JobStatus.WAITING_CONTINUATION.value,
                ),
            ).rowcount
            if changed:
                conn.execute("DELETE FROM agent_checkpoints WHERE job_id = ?", (job_id,))
                # 취소한 판의 기다리던 승인은 만료로 — 남겨 두면 다음 판 위에 카드가 떠 있고, 누르면 죽은 판이
                # 「승인됨」이 된다(2026-09-30 촬영 판). 바깥 요약·화면이 그 카드를 더는 안 내보인다.
                conn.execute(
                    "UPDATE approvals SET status = ? WHERE job_id = ? AND status = ?",
                    (ApprovalStatus.EXPIRED.value, job_id, ApprovalStatus.PENDING.value),
                )
        return changed == 1

    def save_agent_checkpoint(
        self, job_id: str, state: dict[str, Any], *, ttl_sec: int = 1800
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO agent_checkpoints(job_id, state_json, created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(job_id) DO UPDATE SET
                     state_json = excluded.state_json,
                     updated_at = excluded.updated_at,
                     expires_at = excluded.expires_at""",
                (job_id, _json(state), now, now, now + max(60, ttl_sec)),
            )

    def get_agent_checkpoint(self, job_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json, expires_at FROM agent_checkpoints WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) < now:
                conn.execute("DELETE FROM agent_checkpoints WHERE job_id = ?", (job_id,))
                return None
        return _decode(str(row["state_json"]), {})

    def delete_agent_checkpoint(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM agent_checkpoints WHERE job_id = ?", (job_id,))

    def resume_agent_checkpoint(self, job_id: str, state: dict[str, Any]) -> bool:
        now = time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                """UPDATE jobs SET status = ?, updated_at = ?, error = ''
                   WHERE id = ? AND status = ?""",
                (
                    JobStatus.QUEUED.value,
                    now,
                    job_id,
                    JobStatus.WAITING_CONTINUATION.value,
                ),
            ).rowcount
            if changed != 1:
                conn.rollback()
                return False
            conn.execute(
                "UPDATE agent_checkpoints SET state_json = ?, updated_at = ? WHERE job_id = ?",
                (_json(state), now, job_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def has_live_work(self) -> bool:
        """True while some job can still make progress on its own.

        A job parked on an approval or a continuation only counts while the
        thing it waits for is still answerable; once the approval or the
        checkpoint has expired nothing will ever move that job again, and the
        runtime state machine must not stay busy on its behalf.
        """
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM jobs j
                   WHERE j.status IN (?, ?)
                      OR (j.status = ? AND EXISTS (
                            SELECT 1 FROM approvals a
                            WHERE a.job_id = j.id AND a.status = ? AND a.expires_at > ?))
                      OR (j.status = ? AND EXISTS (
                            SELECT 1 FROM agent_checkpoints c
                            WHERE c.job_id = j.id AND c.expires_at > ?))
                   LIMIT 1""",
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.WAITING_APPROVAL.value,
                    ApprovalStatus.PENDING.value,
                    now,
                    JobStatus.WAITING_CONTINUATION.value,
                    now,
                ),
            ).fetchone()
        return row is not None

    #: 다시 켰을 때 **이어서 할** 일의 나이 상한. 이보다 오래된 것은 이어받지 않고 접는다.
    RECOVER_WINDOW_SEC = 900.0

    def recover_interrupted(self, *, window_sec: float | None = None) -> int:
        """끊긴 일을 다시 줄 세운다 — **최근 것만.**

        ★ 2026-09-16: 온텔릭을 다시 켤 때마다 **몇 시간 전에 하던 일**까지 되살아났다. 사용자는 시키지도 않았는데
          새벽에 크롬이 열려 옛 조사를 다시 하는 것을 봤고(실제 목격), 실측에서는 죽은 판의 일이 새 판 앞을
          가로막아 시간이 섞였다(하루에 세 번). 재시작은 몇 초~몇 분이다 — 그보다 한참 오래된 일은 사람이 이미
          떠난 일이므로 이어받지 않는다. 지우지는 않고 **왜 안 이어받았는지** 남긴다.
        """
        now = time.time()
        limit = now - float(self.RECOVER_WINDOW_SEC if window_sec is None else window_sec)
        with self._connect() as conn:
            stale = conn.execute(
                """UPDATE jobs SET status = ?, updated_at = ?, finished_at = ?, error = 'stale_after_restart'
                   WHERE status = ? AND COALESCE(updated_at, created_at) < ?""",
                (JobStatus.CANCELLED.value, now, now, JobStatus.RUNNING.value, limit),
            ).rowcount
            changed = conn.execute(
                """UPDATE jobs SET status = ?, updated_at = ?, error = 'recovered_after_restart'
                   WHERE status = ?""",
                (JobStatus.QUEUED.value, now, JobStatus.RUNNING.value),
            ).rowcount
            # ★ 승인 대기도 같은 규칙 (2026-10-01 시험판). 몇 시간 전에 승인 카드를 띄워 둔 판이 재시작 뒤에도
            #   waiting_approval 로 남아 「새 대화」를 막았다 — 위 정리는 running 만 봤다. 오래된 것은 사람이 이미 떠난 일이다.
            #   최근 것(창 안)은 둔다 — 사람이 아직 카드를 누를 수 있다. 접은 판의 승인 카드도 같이 닫는다(좀비 카드 방지).
            old_waiting = [
                str(row[0])
                for row in conn.execute(
                    "SELECT id FROM jobs WHERE status = ? AND COALESCE(updated_at, created_at) < ?",
                    (JobStatus.WAITING_APPROVAL.value, limit),
                ).fetchall()
            ]
            if old_waiting:
                marks = ",".join("?" for _ in old_waiting)
                conn.execute(
                    f"UPDATE jobs SET status = ?, updated_at = ?, finished_at = ?, error = 'stale_after_restart' "
                    f"WHERE id IN ({marks})",
                    (JobStatus.CANCELLED.value, now, now, *old_waiting),
                )
                conn.execute(
                    f"UPDATE approvals SET status = ? WHERE status = ? AND job_id IN ({marks})",
                    (ApprovalStatus.EXPIRED.value, ApprovalStatus.PENDING.value, *old_waiting),
                )
                stale += len(old_waiting)
        if stale:
            self._log_stale(int(stale))
        return int(changed)

    def _log_stale(self, count: int) -> None:
        """이어받지 않은 일이 몇 개인지 남긴다 — 조용히 사라지면 다음 사람이 「왜 안 이어졌지」를 한다."""
        try:
            print(f"[jobs] 재시작 전 일 {count}개는 너무 오래돼 이어받지 않았다(stale_after_restart)", flush=True)
        except Exception:  # noqa: BLE001
            pass

    # ---- 어디서 막히는가 -------------------------------------------------

    def note_site_friction(
        self, *, host: str, code: str, url: str = "", goal: str = ""
    ) -> int:
        """이 사이트에서 또 막혔다. 지금까지 몇 번째인지 돌려준다."""
        host = (host or "").strip().lower()
        if not host:
            return 0
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO site_friction(host, code, hits, last_url, last_goal,"
                " first_seen, last_seen) VALUES (?, ?, 1, ?, ?, ?, ?)"
                " ON CONFLICT(host, code) DO UPDATE SET"
                "   hits = hits + 1, last_url = excluded.last_url,"
                "   last_goal = excluded.last_goal, last_seen = excluded.last_seen",
                (host, code, url[:500], goal[:300], now, now),
            )
            row = conn.execute(
                "SELECT hits FROM site_friction WHERE host = ? AND code = ?", (host, code)
            ).fetchone()
        return int(row["hits"]) if row else 1

    def site_friction(self, limit: int = 20) -> list[dict[str, Any]]:
        """아픈 순서대로. 레시피를 쓸 곳을 고르는 목록이다."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM site_friction ORDER BY hits DESC, last_seen DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- 되돌리기 ------------------------------------------------------

    def add_undo_offer(
        self,
        *,
        tool: str,
        job_id: str,
        label: str,
        handle: dict[str, Any],
        manual_hint: str,
        automatic: bool,
        expires_at: float,
    ) -> dict[str, Any]:
        undo_id = secrets.token_urlsafe(18)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO undo_offers(undo_id, tool, job_id, label, handle_json,"
                " manual_hint, automatic, status, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'live', ?, ?)",
                (undo_id, tool, job_id, label, _json(handle), manual_hint,
                 1 if automatic else 0, now, expires_at),
            )
        return {
            "undo_id": undo_id,
            "tool": tool,
            "job_id": job_id,
            "label": label,
            "handle": handle,
            "manual_hint": manual_hint,
            "automatic": automatic,
            "created_at": now,
            "expires_at": expires_at,
        }

    def list_undo_offers(self, limit: int = 20) -> list[dict[str, Any]]:
        """아직 되돌릴 수 있는 것들. 최근 것이 앞이다."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM undo_offers WHERE status = 'live' AND expires_at > ?"
                " ORDER BY created_at DESC LIMIT ?",
                (time.time(), max(1, limit)),
            ).fetchall()
        return [self._undo_row(row) for row in rows]

    def claim_undo_offer(self, undo_id: str) -> dict[str, Any] | None:
        """되돌리기를 한 번만 쓰이게 집어 든다.

        승인 소비(consume_approval)와 같은 이유로 원자적이다 — 두 번 눌러
        두 번 되돌리면, 되돌리기가 스스로 새로운 사고가 된다.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM undo_offers WHERE undo_id = ? AND status = 'live'"
                " AND expires_at > ?",
                (undo_id, time.time()),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE undo_offers SET status = 'claimed' WHERE undo_id = ? AND status = 'live'",
                (undo_id,),
            )
            if conn.total_changes == 0:
                return None
        return self._undo_row(row)

    def finish_undo_offer(self, undo_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE undo_offers SET status = ? WHERE undo_id = ?", (status, undo_id)
            )

    # ---- 되돌릴 수 있다는 **실적** ------------------------------------------
    #
    # 표가 왜 여기 있는지는 스키마 주석에. 요약: 강등의 근거는 레시피가 적은 주장이
    # 아니라 실제로 되돌아간 기록이어야 한다.

    def record_inverse_proof(self, site: str, action: str, fingerprint: str, undo_id: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO recipe_inverse_proofs(site, action, fingerprint, undo_id, verified_at)"
                " VALUES(?,?,?,?,?)"
                " ON CONFLICT(site, action) DO UPDATE SET"
                "   fingerprint = excluded.fingerprint,"
                "   undo_id = excluded.undo_id,"
                "   verified_at = excluded.verified_at",
                (site, action, fingerprint, undo_id, time.time()),
            )

    def has_inverse_proof(self, site: str, action: str, fingerprint: str) -> bool:
        """**지문까지 같아야** 실적으로 친다.

        레시피가 바뀌었으면 같은 이름이어도 다른 일이다. 이름만 보면 "한 번
        되돌려 봤으니 승인 없이 돌려도 된다"가 **다른 절차에 상속된다.**
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT fingerprint FROM recipe_inverse_proofs WHERE site = ? AND action = ?",
                (site, action),
            ).fetchone()
        return bool(row) and str(row["fingerprint"]) == fingerprint

    def revoke_inverse_proof(self, site: str, action: str) -> None:
        """되돌리기가 한 번이라도 실패하면 실적을 회수한다.

        되돌아갈 줄 알았는데 안 되는 것이, 애초에 못 되돌린다고 알고 있는 것보다
        나쁘다 — 그 믿음 위에서 승인을 빼고 있었기 때문이다.
        """
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM recipe_inverse_proofs WHERE site = ? AND action = ?", (site, action)
            )

    def list_inverse_proofs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM recipe_inverse_proofs ORDER BY verified_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _undo_row(row: Any) -> dict[str, Any]:
        data = dict(row)
        try:
            data["handle"] = json.loads(data.pop("handle_json") or "{}")
        except Exception:
            data["handle"] = {}
            data.pop("handle_json", None)
        data["automatic"] = bool(data.get("automatic"))
        return data

    def record_build_manifest(self) -> dict[str, str]:
        """지금 판의 **축별 지문**을 남긴다. 기동 때 한 번.

        이게 없으면 나중에 축별로 표본을 묶을 수가 없다 — `build` 칸에는 전체
        해시만 있어서 되짚어 쪼갤 방법이 없기 때문이다. **판이 도는 그 순간에
        적어 두지 않으면 영원히 못 안다.**
        """
        axes = axis_build_ids()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO build_manifest(build, axes_json, first_seen)"
                " VALUES (?, ?, ?)",
                (build_id(), _json(axes), time.time()),
            )
        return axes

    def build_axes(self) -> dict[str, dict[str, str]]:
        """판 -> 축별 지문. 눈금이 표본을 묶을 때 쓴다."""
        with self._connect() as conn:
            rows = conn.execute("SELECT build, axes_json FROM build_manifest").fetchall()
        out: dict[str, dict[str, str]] = {}
        for row in rows:
            try:
                out[str(row[0])] = json.loads(row[1])
            except Exception:
                continue
        return out

    def add_audit(self, event: str, subject_id: str = "", payload: Any = None) -> None:
        # ★ 어느 코드가 낸 결과인지를 같이 적는다. 이게 없으면 낡은 실적과 방금 고친
        # 실적이 한 표에 섞이고, **섞였다는 사실조차 안 보인다**(config.build_id 참고).
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_log(event, subject_id, payload_json, created_at, build)"
                " VALUES (?, ?, ?, ?, ?)",
                (event, subject_id, _json(payload or {}), time.time(), build_id()),
            )

    def create_approval(
        self,
        *,
        nonce: str,
        job_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        proof: dict[str, Any] | None = None,
        expires_at: float,
    ) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO approvals
                   (nonce, job_id, tool_name, arguments_json, proof_json, status, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    nonce,
                    job_id,
                    tool_name,
                    _json(arguments),
                    _json(proof or {}),
                    ApprovalStatus.PENDING.value,
                    now,
                    expires_at,
                ),
            )
        approval = self.get_approval(nonce)
        if approval is None:
            raise RuntimeError("approval_not_created")
        return approval

    def get_approval(self, nonce: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE nonce = ?", (nonce,)).fetchone()
        return self._row(row)

    def find_approved(
        self, *, job_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM approvals
                   WHERE job_id = ? AND tool_name = ? AND arguments_json = ?
                     AND status = ? AND expires_at >= ?
                   ORDER BY created_at DESC LIMIT 1""",
                (job_id, tool_name, _json(arguments), ApprovalStatus.APPROVED.value, now),
            ).fetchone()
        return self._row(row)

    def decide_approval(
        self, nonce: str, approve: bool, answer: str | None = None
    ) -> dict[str, Any] | None:
        now = time.time()
        next_status = ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM approvals WHERE nonce = ?", (nonce,)).fetchone()
            if row is None:
                conn.rollback()
                return None
            if row["status"] != ApprovalStatus.PENDING.value or float(row["expires_at"]) < now:
                if row["status"] == ApprovalStatus.PENDING.value:
                    conn.execute(
                        "UPDATE approvals SET status = ? WHERE nonce = ?",
                        (ApprovalStatus.EXPIRED.value, nonce),
                    )
                    conn.commit()
                else:
                    conn.rollback()
                return self.get_approval(nonce)
            conn.execute(
                "UPDATE approvals SET status = ?, answer = ? WHERE nonce = ?",
                (next_status.value, answer if approve else None, nonce),
            )
            job_id = str(row["job_id"] or "")
            if job_id:
                if approve:
                    conn.execute(
                        "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                        (JobStatus.QUEUED.value, now, job_id, JobStatus.WAITING_APPROVAL.value),
                    )
                else:
                    conn.execute(
                        """UPDATE jobs SET status = ?, error = ?, updated_at = ?, finished_at = ?
                           WHERE id = ? AND status = ?""",
                        (
                            JobStatus.CANCELLED.value,
                            "approval_denied",
                            now,
                            now,
                            job_id,
                            JobStatus.WAITING_APPROVAL.value,
                        ),
                    )
            conn.commit()
        return self.get_approval(nonce)

    def consume_approval(self, nonce: str) -> bool:
        now = time.time()
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE approvals SET status = ?, consumed_at = ?
                   WHERE nonce = ? AND status = ? AND expires_at >= ?""",
                (
                    ApprovalStatus.CONSUMED.value,
                    now,
                    nonce,
                    ApprovalStatus.APPROVED.value,
                    now,
                ),
            ).rowcount
        return changed == 1

    def list_approvals(self, limit: int = 50, status: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        now = time.time()
        with self._connect() as conn:
            # 만료는 시간이 만드는 상태다. 사람이 나중에 결정 버튼을 눌러야만
            # `decide_approval` 에서 expired 로 바뀌게 두면, 아무도 누르지 않은
            # 승인이 DB와 목록 API에서 몇 주씩 pending 으로 남는다. 조회하기 전에
            # 장부를 현재 시각과 맞춘다 — 실행 가능 여부(has_live_work)는 이미 같은
            # expires_at 기준을 쓰므로 이것은 새 정책이 아니라 표시를 사실에 맞추는 일이다.
            expired_jobs = [
                str(row["job_id"] or "")
                for row in conn.execute(
                    "SELECT job_id FROM approvals WHERE status = ? AND expires_at < ? AND job_id != ''",
                    (ApprovalStatus.PENDING.value, now),
                ).fetchall()
            ]
            conn.execute(
                "UPDATE approvals SET status = ? WHERE status = ? AND expires_at < ?",
                (ApprovalStatus.EXPIRED.value, ApprovalStatus.PENDING.value, now),
            )
            # 승인만 만료시키고 잡을 waiting_approval에 두면 다시 승인할 nonce도,
            # 스스로 재개할 길도 없는 좀비가 된다. 만료는 거절과 같은 terminal
            # 결정으로 장부를 닫되, 실제 외부 동작은 당연히 실행하지 않는다.
            cancelled_now: list[str] = []
            if expired_jobs:
                placeholders = ",".join("?" for _ in expired_jobs)
                # 실제로 waiting_approval 이던 것만 — 이미 다른 상태로 끝난 잡을 만료가 건드렸다고 알리면 거짓 알림이다.
                cancelled_now = [
                    str(row["id"])
                    for row in conn.execute(
                        f"SELECT id FROM jobs WHERE status = ? AND id IN ({placeholders})",
                        (JobStatus.WAITING_APPROVAL.value, *expired_jobs),
                    ).fetchall()
                ]
                conn.execute(
                    f"UPDATE jobs SET status = ?, error = ?, updated_at = ?, finished_at = ? "
                    f"WHERE status = ? AND id IN ({placeholders})",
                    (
                        JobStatus.CANCELLED.value,
                        "approval_expired",
                        now,
                        now,
                        JobStatus.WAITING_APPROVAL.value,
                        *expired_jobs,
                    ),
                )
            if status:
                rows = conn.execute(
                    "SELECT * FROM approvals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        # 연결을 닫은 **뒤에** 알린다 — 리스너가 다시 저장소를 열어도 잠기지 않게. 알리다 죽어도 조회는 살아야 한다.
        if cancelled_now and self.on_jobs_expired is not None:
            try:
                self.on_jobs_expired(cancelled_now)
            except Exception:  # noqa: BLE001
                pass
        return [self._row(row) or {} for row in rows]


JobHandler = Callable[[dict[str, Any]], Any]


class ApprovalRequired(RuntimeError):
    def __init__(self, nonce: str) -> None:
        super().__init__(f"approval_required:{nonce}")
        self.nonce = nonce


class ContinuationRequired(RuntimeError):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__("agent_continuation_required")
        self.payload = payload


class YieldToPerson(RuntimeError):
    """바깥 AI 가 맡긴 판이 **사람의 요청에 자리를 비켜 준다** (2026-10-09).

    실패도 멈춤도 아니다. 판은 걸음 사이에서 멈춘 자리(대화 · 걸음)를 저장하고 다시 줄에 선다. 줄에서는 사람 것이 먼저
    나가고(`claim_next`), 그것이 끝나면 이 판이 저장한 자리에서 이어 간다. 사람이 다시 시킬 필요가 없다.
    """

    def __init__(self, job_id: str = "") -> None:
        super().__init__("yield_to_person")
        self.job_id = job_id


def _delegated_payload(payload_json: Any) -> bool:
    """이 일이 바깥 AI 가 맡긴 것인가(`origin: mcp`). 읽지 못하는 것은 맡긴 일로 치지 않는다 — 사람 쪽으로 기운다."""
    payload = _decode(str(payload_json or ""), {})
    return isinstance(payload, dict) and str(payload.get("origin") or "") == "mcp"


class JobRunner:
    def __init__(self, store: JobStore, events: EventBus, poll_sec: float = 0.2) -> None:
        self.store = store
        self.events = events
        self.poll_sec = poll_sec
        self._handlers: dict[str, JobHandler] = {}
        self._terminal_listeners: list[Callable[[dict[str, Any]], None]] = []
        # 승인 만료로 저장소가 잡을 취소하면 다른 종료와 **같은 길**로 리스너를 부른다.
        self.store.on_jobs_expired = lambda ids: [self._notify_terminal(job_id) for job_id in ids]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def add_terminal_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self._terminal_listeners.append(listener)

    def _notify_terminal(self, job_id: str) -> None:
        current = self.store.get_job(job_id)
        if current is None:
            return
        for listener in self._terminal_listeners:
            try:
                listener(current)
            except Exception:
                continue

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.recover_interrupted()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-job-runner", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next()
            if not job:
                self._stop.wait(self.poll_sec)
                continue
            job_id = str(job["id"])
            self.events.publish("job_started", {"job_id": job_id, "kind": job["kind"]})
            handler = self._handlers.get(str(job["kind"]))
            if handler is None:
                self.store.set_status(job_id, JobStatus.FAILED, error=f"unsupported_job_kind:{job['kind']}")
                self.events.publish("job_failed", {"job_id": job_id, "error": "unsupported_job_kind"})
                self._notify_terminal(job_id)
                continue
            try:
                result = handler(job)
                latest = self.store.get_job(job_id)
                if latest and latest["status"] == JobStatus.CANCELLED.value:
                    # 답을 다 만든 순간에 멈췄으면 그 결과를 버리지 않는다 — 상태는 「멈춤」 그대로 두고 결과만 붙인다
                    # (2026-09-30: 멈춘 판이 `steps: 0` 으로 보여 무엇을 했는지 대조할 수 없었다).
                    kept = latest.get("result") if isinstance(latest.get("result"), dict) else {}
                    if isinstance(result, dict) and not kept.get("agent_trace"):
                        self.store.attach_result(job_id, {**result, "cancelled": True})
                    self.events.publish("job_cancelled", {"job_id": job_id})
                    continue
                self.store.set_status(job_id, JobStatus.COMPLETED, result=result)
                self.events.publish("job_completed", {"job_id": job_id, "result": result})
                self._notify_terminal(job_id)
            except ApprovalRequired as exc:
                self.store.set_status(job_id, JobStatus.WAITING_APPROVAL)
                self.events.publish(
                    "job_waiting_approval", {"job_id": job_id, "approval_nonce": exc.nonce}
                )
            except ContinuationRequired as exc:
                # ★ 멈춘 이유(막힌 곳·해 주실 일)를 잡에 남긴다(2026-09-23). 화면 카드는 이벤트로 받지만 바깥 AI 는
                #   잡을 다시 읽어서만 안다 — 안 남기면 「계속할지 묻고 있다」만 전하고 **무엇을 해 달라는지**를 모른다.
                latest = self.store.get_job(job_id) or {}
                merged = dict(latest.get("result") or {}) if isinstance(latest.get("result"), dict) else {}
                merged["continuation"] = dict(exc.payload or {})
                self.store.set_status(job_id, JobStatus.WAITING_CONTINUATION, result=merged)
                self.events.publish("agent_continuation_requested", exc.payload)
            except YieldToPerson:
                # 맡긴 판이 사람에게 비켜 줬다 — 다시 줄에 세운다. 다음 바퀴의 `claim_next` 가 사람 것을 먼저 꺼낸다.
                self.store.requeue_yielded(job_id)
                self.events.publish("job_yielded", {"job_id": job_id})
            except Exception as exc:  # handlers are isolated from the runner
                latest = self.store.get_job(job_id)
                if latest and latest["status"] == JobStatus.CANCELLED.value:
                    self.events.publish("job_cancelled", {"job_id": job_id})
                    continue
                self.store.set_status(job_id, JobStatus.FAILED, error=str(exc))
                self.events.publish("job_failed", {"job_id": job_id, "error": str(exc)[:500]})
                self._notify_terminal(job_id)
