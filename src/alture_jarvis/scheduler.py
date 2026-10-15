from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .events import EventBus
from .models import RiskLevel
from .sqlite_schema import add_column_if_missing
from .tool_gateway import ToolGateway, ToolSpec


EnqueueCallback = Callable[[str, str, dict[str, Any], RiskLevel], dict[str, Any]]


class TaskScheduler:
    """Durable one-shot scheduler backed by the JARVIS SQLite database."""

    def __init__(
        self,
        database_path: Path,
        events: EventBus,
        enqueue: EnqueueCallback,
        *,
        config: Any = None,
        job_lookup: Callable[[str], dict[str, Any] | None] | None = None,
        send_mail: Callable[[list[str], str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.database_path = database_path
        self.events = events
        self.enqueue = enqueue
        self.config = config
        # 끝난 잡을 다시 읽어 답을 꺼내는 길. 없으면 배달을 안 한다(초소와 같은 모양).
        self.job_lookup = job_lookup
        self.send_mail = send_mail
        # 배달을 기다리는 잡: job_id -> schedule_id
        self._awaiting: dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._init_schema()
        self._definitions = self._build_definitions()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    run_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_job_id TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(status, run_at)"
            )
            # 반복과 배달은 나중에 붙었다. 옛 DB 에도 이 자가 돌아야 하므로
            # 칸이 없을 때만 더한다(있으면 sqlite 가 예외를 던지고, 그건 정상이다).
            # ★ 확인과 추가를 한 문으로 — 같은 새 DB 를 둘이 동시에 열면 둘 다 「없다」를 보고 한쪽이 죽었다
            #   (2026-10-06, `sqlite_schema.py`).
            add_column_if_missing(connection, "schedules", "repeat_every", "TEXT NOT NULL DEFAULT 'none'")
            add_column_if_missing(connection, "schedules", "deliver_to", "TEXT NOT NULL DEFAULT ''")
            # A crash can occur after claiming but before enqueueing. Re-queue
            # those rows so the next JARVIS start resumes them exactly once.
            connection.execute(
                "UPDATE schedules SET status='pending', updated_at=? WHERE status='dispatching'",
                (time.time(),),
            )

    @staticmethod
    def _parse_run_at(value: Any, delay_minutes: Any = None) -> float:
        if delay_minutes not in (None, ""):
            return time.time() + max(0.0, float(delay_minutes)) * 60
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("run_at_or_delay_minutes_required")
        try:
            return float(raw)
        except ValueError:
            pass
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.timestamp()

    # 반복 주기. 「매달」은 일부러 없다 — 31일에 만든 예약이 2월에 어디로 가야
    # 하는지 답이 하나가 아니고, 지금 필요한 것도 아니다.
    REPEAT_SECONDS = {
        "daily": 24 * 3600,
        "weekly": 7 * 24 * 3600,
        "weekday": 0,  # 아래에서 따로 센다
    }

    @classmethod
    def _next_run(cls, previous: float, repeat_every: str, *, now: float | None = None) -> float:
        """다음에 돌 시각. **지난 것을 몰아서 돌지 않는다.**

        ★ PC 가 일주일 꺼져 있었다고 해서 매일 예약이 일곱 번 터지면 안 된다.
        그건 복구가 아니라 사고다. 그래서 「밀린 횟수」가 아니라 **지금보다 뒤에
        오는 첫 시각**을 찾는다 — 시각(예: 아침 7시)은 그대로 지킨다.
        """
        now = now if now is not None else time.time()
        if repeat_every == "weekday":
            nxt = previous
            while True:
                nxt += 24 * 3600
                # 월(0)~금(4) 만. 토·일은 건너뛴다.
                if datetime.fromtimestamp(nxt).weekday() < 5 and nxt > now:
                    return nxt
        step = cls.REPEAT_SECONDS.get(repeat_every, 0)
        if step <= 0:
            raise ValueError(f"unknown_repeat:{repeat_every}")
        nxt = previous
        while nxt <= now:
            nxt += step
        return nxt

    def allowed_recipients(self) -> set[str]:
        """사람 없이 결과를 보내도 되는 주소. 설정에만 있고 코드에는 없다."""
        raw = str(getattr(self.config, "scheduled_mail_recipients", "") or "")
        return {part.strip().lower() for part in raw.split(",") if part.strip()}

    def _check_delivery(self, deliver_to: list[str]) -> list[str]:
        """보낼 주소를 **예약을 만드는 지금** 검사한다.

        ★ 왜 여기서 막나. `google_gmail_send` 는 L2 이고 되돌리기가 없다 — 보낸
        메일은 못 지운다. 그런데 예약이 도는 아침 7시에는 승인해 줄 사람이 없다.
        그러니 승인은 **사람이 있는 시점**에 받아야 하고, 그게 지금이다.

        허용목록에 없는 주소는 **거절한다.** 「나중에 승인 카드를 띄우자」로 하면
        그 카드는 아무도 없는 새벽에 떠서 5분 뒤 만료된다(승인 만료가 실제로
        29%다). 지금 거절하고 사람이 직접 보내게 하는 편이 정직하다.
        """
        if not deliver_to:
            return []
        allowed = self.allowed_recipients()
        if not allowed:
            raise ValueError(
                "scheduled_mail_disabled — 사람 없이 메일을 보낼 주소가 설정되어 있지 "
                "않습니다(JARVIS_SCHEDULED_MAIL_RECIPIENTS). 예약은 만들 수 있지만 "
                "배달은 못 합니다."
            )
        rejected = [item for item in deliver_to if item.lower() not in allowed]
        if rejected:
            raise ValueError(
                f"recipient_not_allowed:{','.join(rejected)} — 사람 없이 보낼 수 있는 "
                f"주소는 {', '.join(sorted(allowed))} 뿐입니다. 다른 곳으로 보내려면 "
                "예약 말고 직접 시켜 주세요(그때는 승인 카드가 뜹니다)."
            )
        return deliver_to

    def create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # 꺼져 있으면 **만드는 것부터 거절한다.** 만들어만 두면 「예약했습니다」라고
        # 답해 놓고 그 시각에 아무 일도 안 일어난다 — 초소와 같은 이유다.
        if not getattr(self.config, "scheduler_enabled", True):
            raise RuntimeError(
                "scheduler_disabled — 이 PC 에서는 예약 실행이 꺼져 있다"
                "(JARVIS_SCHEDULER_ENABLED=false). 만들어도 그 시각에 안 돈다."
                " 사용자에게 '예약은 지금 꺼져 있다'고 말하고, 필요하면 켜 달라고 해라."
            )
        title = str(arguments.get("title") or "예약 작업").strip()[:200]
        prompt = str(arguments.get("prompt") or "").strip()[:12000]
        if not prompt:
            raise ValueError("prompt_required")
        run_at = self._parse_run_at(arguments.get("run_at"), arguments.get("delay_minutes"))
        if run_at < time.time() - 5:
            raise ValueError("run_at_is_in_the_past")

        repeat_every = str(arguments.get("repeat_every") or "none").strip().lower()
        if repeat_every not in {"none", "daily", "weekday", "weekly"}:
            raise ValueError(f"unknown_repeat:{repeat_every}")

        raw_to = arguments.get("deliver_to") or []
        if isinstance(raw_to, str):
            raw_to = [part.strip() for part in raw_to.replace(";", ",").split(",") if part.strip()]
        deliver_to = self._check_delivery([str(item).strip() for item in raw_to if str(item).strip()])

        schedule_id = uuid.uuid4().hex
        now = time.time()
        session_id = str(arguments.get("session_id") or "office-main")[:80]
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO schedules(id,title,prompt,session_id,run_at,status,created_at,updated_at,"
                "repeat_every,deliver_to) VALUES(?,?,?,?,?,'pending',?,?,?,?)",
                (
                    schedule_id, title, prompt, session_id, run_at, now, now,
                    repeat_every, ",".join(deliver_to),
                ),
            )
        result = self.get(schedule_id)
        self.events.publish("schedule_created", result)
        return result

    def get(self, schedule_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
            ).fetchone()
        if row is None:
            raise ValueError("schedule_not_found")
        return dict(row)

    def list(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}
        limit = max(1, min(int(arguments.get("limit") or 50), 200))
        status = str(arguments.get("status") or "").strip()
        query = "SELECT * FROM schedules"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY run_at ASC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return {"action": "schedule_list", "count": len(rows), "schedules": [dict(row) for row in rows]}

    def cancel(self, arguments: dict[str, Any]) -> dict[str, Any]:
        schedule_id = str(arguments.get("schedule_id") or "")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE schedules SET status='cancelled', updated_at=? WHERE id=? AND status='pending'",
                (time.time(), schedule_id),
            )
        if cursor.rowcount != 1:
            raise ValueError("schedule_not_pending")
        result = self.get(schedule_id)
        self.events.publish("schedule_cancelled", result)
        return result

    def _claim_due(self) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM schedules WHERE status='pending' AND run_at<=? ORDER BY run_at LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            cursor = connection.execute(
                "UPDATE schedules SET status='dispatching', updated_at=? WHERE id=? AND status='pending'",
                (now, row["id"]),
            )
            connection.commit()
        return dict(row) if cursor.rowcount == 1 else None

    def _dispatch(self, row: dict[str, Any]) -> None:
        try:
            job = self.enqueue(
                "chat",
                f"예약: {row['title']}",
                {
                    "prompt": row["prompt"],
                    "session_id": row["session_id"],
                    "delivery": "screen",
                    "origin": "chat",
                    "agent_mode": "auto",
                    "attachments": [],
                    "scheduled": True,
                    "notify": True,
                    "schedule_id": row["id"],
                },
                RiskLevel.L0,
            )
            status, job_id = "dispatched", str(job["id"])
            self.events.publish("schedule_dispatched", {"schedule_id": row["id"], "job_id": job_id})
            if str(row.get("deliver_to") or ""):
                self._awaiting[job_id] = str(row["id"])
        except Exception as exc:
            status, job_id = "pending", ""
            self.events.publish("schedule_dispatch_failed", {"schedule_id": row["id"], "error": str(exc)[:300]})

        # 반복이면 **다음 시각을 잡아 다시 pending 으로.** 지난 것은 안 몰아 돈다.
        repeat_every = str(row.get("repeat_every") or "none")
        next_at = float(row["run_at"])
        if status == "dispatched" and repeat_every != "none":
            try:
                next_at = self._next_run(float(row["run_at"]), repeat_every)
                status = "pending"
            except ValueError:
                # 알 수 없는 주기다. 되풀이하지 않고 그 자리에 세운다 — 매초
                # 다시 도는 것보다 한 번 안 도는 편이 낫다.
                self.events.publish(
                    "schedule_repeat_failed",
                    {"schedule_id": row["id"], "repeat_every": repeat_every},
                )

        with self._connect() as connection:
            connection.execute(
                "UPDATE schedules SET status=?, last_job_id=?, updated_at=?, run_at=? WHERE id=?",
                (status, job_id, time.time(), next_at, row["id"]),
            )

    # ── 배달 ─────────────────────────────────────────────────────────────────
    #
    # 예약은 잡을 던지고 끝난다. 그 잡이 끝나기를 여기서 지켜보다가 답을 메일로
    # 보낸다 — 관찰 초소(`watch_service._collect_finished`)와 같은 모양이다.
    #
    # ★ **끝난 판만 보낸다.** 취소·실패한 판의 빈손을 보내면 받는 사람은 그것을
    #   「오늘은 별일 없었다」로 읽는다. 초소가 같은 자리에서 눈을 감았던 적이 있다.

    def _collect_delivered(self) -> None:
        if not self._awaiting or not self.job_lookup or not self.send_mail:
            return
        for job_id, schedule_id in list(self._awaiting.items()):
            job = self.job_lookup(job_id)
            if not job:
                self._awaiting.pop(job_id, None)
                continue
            if str(job.get("status")) not in {"completed", "failed", "cancelled"}:
                continue
            self._awaiting.pop(job_id, None)
            if str(job.get("status")) != "completed":
                self.events.publish(
                    "schedule_delivery_skipped",
                    {"schedule_id": schedule_id, "job_id": job_id, "why": str(job.get("status"))},
                )
                continue
            try:
                row = self.get(schedule_id)
            except ValueError:
                continue
            to = [item for item in str(row.get("deliver_to") or "").split(",") if item]
            answer = str((job.get("result") or {}).get("answer") or "").strip()
            if not to or not answer:
                self.events.publish(
                    "schedule_delivery_skipped",
                    {"schedule_id": schedule_id, "job_id": job_id, "why": "no_answer" if to else "no_recipient"},
                )
                continue
            try:
                # 보내기 직전에 **한 번 더** 허용목록을 본다. 예약을 만든 뒤에
                # 설정에서 주소를 뺐다면 그 뜻을 따라야 한다.
                self._check_delivery(to)
                sent = self.send_mail(to, f"[Sonjari 예약] {row['title']}", answer)
                self.events.publish(
                    "schedule_delivered",
                    {"schedule_id": schedule_id, "job_id": job_id, "to": to, "ok": True, **(sent or {})},
                )
            except Exception as exc:
                self.events.publish(
                    "schedule_delivery_failed",
                    {"schedule_id": schedule_id, "job_id": job_id, "error": str(exc)[:300]},
                )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._collect_delivered()
            except Exception:  # noqa: BLE001 — 배달이 실패해도 예약은 계속 돈다
                pass
            row = self._claim_due()
            if row:
                self._dispatch(row)
                continue
            self._stop.wait(1.0)

    @staticmethod
    def _function(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required or []}}}

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function("schedule_list", "예약되어 있거나 실행된 손자리 작업 목록을 확인한다.", {"status": {"type": "string"}, "limit": {"type": "integer"}}),
            self._function(
                "schedule_create",
                "사용자가 요청한 작업을 지정 시각(또는 몇 분 뒤)에 실행하도록 영구 저장한다. "
                "repeat_every 로 매일·평일·매주 반복할 수 있고, deliver_to 를 주면 끝난 뒤 "
                "결과를 메일로 보낸다. 생성에는 승인이 필요하다.",
                {
                    "title": {"type": "string"},
                    "prompt": {"type": "string"},
                    "run_at": {"type": "string", "description": "ISO 8601 현지 시각"},
                    "delay_minutes": {"type": "number"},
                    "repeat_every": {
                        "type": "string",
                        "enum": ["none", "daily", "weekday", "weekly"],
                        "description": "기본 none(한 번만). weekday 는 월~금",
                    },
                    "deliver_to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "끝난 뒤 결과를 받을 메일 주소. 미리 허용된 주소만 된다 — "
                                       "다른 주소를 주면 예약 자체가 거절된다",
                    },
                    "session_id": {"type": "string"},
                },
                ["prompt"],
            ),
            self._function("schedule_cancel", "아직 실행되지 않은 예약 작업을 취소한다. 승인이 필요하다.", {"schedule_id": {"type": "string"}}, ["schedule_id"]),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def register(self, gateway: ToolGateway) -> None:
        handlers = {"schedule_list": self.list, "schedule_create": self.create, "schedule_cancel": self.cancel}
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(ToolSpec(name=name, description=str(definition["function"]["description"]), risk_level=RiskLevel.L0 if name == "schedule_list" else RiskLevel.L2, handler=handlers[name], enabled=True, parameters=dict(definition["function"].get("parameters") or {})))
