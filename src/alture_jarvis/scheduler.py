from __future__ import annotations

import json
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
#: 루틴 한 회차를 돌리는 손 — (설명서, 결과 파일) → `routine.run_routine` 결과. 시험은 네트워크 없는 것으로 바꿔 끼운다.
RoutineRunner = Callable[[dict[str, Any], Path], dict[str, Any]]


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
        routine_runner: RoutineRunner | None = None,
        send_discord: Callable[[str], None] | None = None,
    ) -> None:
        # 정해진 문구를 디스코드 홈 채널로 보내는 손(2026-10-26 「매일 아침 정해진 시각 알림」 요청). 없으면 이 PC 디스코드 봇으로.
        self.send_discord = send_discord
        self.database_path = database_path
        self.routine_runner = routine_runner or self._run_routine_without_model
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
            # ★ 「루틴」 종류(2026-10-23 · 전략안 §55-39). prompt 대신 루틴 설명서(JSON)를 저장해 **모델 없이** 돈다.
            #   last_result 는 마지막 회차의 작은 줄(건수 · 깨짐 · 파일) — 앱 화면 예약 목록이 그대로 보여 준다.
            add_column_if_missing(connection, "schedules", "kind", "TEXT NOT NULL DEFAULT 'prompt'")
            add_column_if_missing(connection, "schedules", "routine", "TEXT NOT NULL DEFAULT ''")
            add_column_if_missing(connection, "schedules", "last_result", "TEXT NOT NULL DEFAULT ''")
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

    # ── 루틴 (모델 없이 도는 예약 · 2026-10-23 · 전략안 §55-39 · §55-40 첫 칸) ──────────
    #
    # prompt 예약은 돌 때마다 모델이 판을 새로 짠다(채용 봇 판 하나 17분 · 43걸음 — 하루 3번이면 PC 가 50분 붙잡힌다).
    # 루틴은 레시피 주소로 받아 정해진 칸만 읽는다 — 매번 똑같이 돌고, 몇 번 돌았는지 · 몇 번 깨졌는지를 셀 수 있다.

    def _recipe_dir(self) -> Path | None:
        value = getattr(self.config, "site_recipe_dir", None)
        return Path(value) if value else None

    def _routine_dir(self, schedule_id: str) -> Path:
        base = getattr(self.config, "data_dir", None)
        return (Path(base) if base else self.database_path.parent) / "routines" / schedule_id

    def _routine_spec(self, raw: Any) -> dict[str, str] | None:
        if raw in (None, "", {}):
            return None
        from .routine import RoutineRefused, build_url, load_recipe, normalize_spec

        try:
            spec = json.loads(raw) if isinstance(raw, str) else raw
            clean = normalize_spec(spec)
            build_url(load_recipe(clean["recipe"], self._recipe_dir()), clean)  # 주소만 만들어 본다 — 받지는 않는다
        except (RoutineRefused, ValueError) as exc:
            raise ValueError(f"routine_refused — {exc}") from exc
        return {key: value for key, value in clean.items() if value}

    def _run_routine_without_model(self, spec: dict[str, Any], out: Path) -> dict[str, Any]:
        from .routine import run_routine

        return run_routine(spec, out, recipe_dir=self._recipe_dir())

    def _dispatch_routine(self, row: dict[str, Any]) -> str:
        """루틴 한 회차. 결과의 작은 줄을 `last_result` 에, 회차 기록을 `runs.jsonl` 에 남긴다. 늘 "ran" 을 돌려준다."""
        from .routine import command_line, summary

        out = self._routine_dir(str(row["id"])) / "latest.json"
        try:
            spec = json.loads(str(row.get("routine") or "{}"))
        except ValueError:
            spec = {}
        try:
            result = self.routine_runner(spec, out)
        except Exception as exc:  # noqa: BLE001 — 실행기가 넘어져도 예약 줄은 남는다(조용히 사라지지 않는다)
            result = {"status": "failed", "problems": [f"루틴 실행기가 넘어졌다: {type(exc).__name__}: {str(exc)[:200]}"]}
        small = summary(result)
        small["at"] = time.time()
        try:
            small["command"] = command_line(spec, out)
        except Exception:  # noqa: BLE001
            small["command"] = ""
        # 회차 기록 — 「모델 없이 성공 / 손자리가 고침 / 틀린 값」을 셀 재료(§55-39 ④ 사흘 9회).
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            with (out.parent / "runs.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"schedule_id": row["id"], **small}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        with self._connect() as connection:
            connection.execute(
                "UPDATE schedules SET last_result=?, updated_at=? WHERE id=?",
                (json.dumps(small, ensure_ascii=False), time.time(), row["id"]),
            )
        self.events.publish("routine_ran", {"schedule_id": row["id"], "title": row.get("title", ""), **small})
        if small["status"] == "broken":
            self._repair_with_model(row, small)
        return "ran"

    def _repair_with_model(self, row: dict[str, Any], small: dict[str, Any]) -> dict[str, Any]:
        """깨진 회차만 손자리(모델)에게 넘기는 **자리**. 아직 연결하지 않았다 — 다음 일(§55-39 고리 4).

        연결할 때 지킬 것: 그 회차만 · 고친 레시피는 사람이 「응」 한 뒤에만 저장(`save_learned` 와 같은 규칙) ·
        고친 뒤 같은 표본으로 다시 읽혀 건수가 맞는지 본다(고친 레시피가 틀린 값을 굳히지 않게).
        """
        note = {"schedule_id": row["id"], "problems": small.get("problems", []), "repair": "not_connected"}
        self.events.publish("routine_broken", note)
        return note

    def create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # 꺼져 있으면 **만드는 것부터 거절한다.** 만들어만 두면 「예약했습니다」라고
        # 답해 놓고 그 시각에 아무 일도 안 일어난다 — 초소와 같은 이유다.
        if not getattr(self.config, "scheduler_enabled", True):
            raise RuntimeError(
                "scheduler_disabled — 이 PC 에서는 예약 실행이 꺼져 있다"
                "(JARVIS_SCHEDULER_ENABLED=false). 만들어도 그 시각에 안 돈다."
                " 사용자에게 '예약은 지금 꺼져 있다'고 말하고, 필요하면 켜 달라고 해라."
            )
        if str(arguments.get("kind") or "").strip().lower() == "message":
            return self._create_message(arguments)
        # 루틴 설명서는 **만드는 지금** 검사한다 — 모르는 지역 · 레시피 밖 주소는 새벽 7시가 아니라 사람이 있는 지금 거절된다.
        routine_spec = self._routine_spec(arguments.get("routine"))
        title = str(arguments.get("title") or "예약 작업").strip()[:200]
        prompt = str(arguments.get("prompt") or "").strip()[:12000]
        if routine_spec and not prompt:
            # 화면 · 목록이 읽는 한 줄. 돌 때는 이 글을 쓰지 않는다(모델에게 안 간다).
            prompt = "루틴(모델 없이): " + " · ".join(
                part for part in (routine_spec["recipe"], routine_spec["query"], routine_spec.get("region", "")) if part)
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
        if routine_spec and deliver_to:
            # 메일 배달은 모델 답(잡의 answer)을 보낸다. 루틴 결과를 메일로 보내는 길은 아직 없다 — 받아 놓고 안 보내지 않는다.
            raise ValueError("routine_delivery_not_supported — 루틴 결과는 아직 메일로 못 보낸다. 결과는 예약 목록과 파일에 남는다.")

        schedule_id = uuid.uuid4().hex
        now = time.time()
        session_id = str(arguments.get("session_id") or "office-main")[:80]
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO schedules(id,title,prompt,session_id,run_at,status,created_at,updated_at,"
                "repeat_every,deliver_to,kind,routine) VALUES(?,?,?,?,?,'pending',?,?,?,?,?,?)",
                (
                    schedule_id, title, prompt, session_id, run_at, now, now,
                    repeat_every, ",".join(deliver_to),
                    "routine" if routine_spec else "prompt",
                    json.dumps(routine_spec, ensure_ascii=False) if routine_spec else "",
                ),
            )
        result = self.get(schedule_id)
        self.events.publish("schedule_created", result)
        return result

    def _create_message(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """정해진 문구 알림 — 모델 없이, 그 시각에 글 그대로 디스코드 홈 채널로 보낸다(2026-10-26).

        모델에게 가지 않으니 매번 같은 글이 간다. 받는 곳은 지금 「디스코드 홈 채널」 하나 — 이 PC 디스코드 봇이 든 서버의 그 채널.
        """
        message = str(arguments.get("message") or arguments.get("prompt") or "").strip()[:2000]
        if not message:
            raise ValueError("message_required — 보낼 문구가 비어 있다.")
        channel = str(arguments.get("channel") or "discord").strip().lower()
        if channel not in {"discord", "discord:home"}:
            raise ValueError(f"unknown_channel:{channel} — 지금은 디스코드 홈 채널(discord)만 받는다.")
        title = str(arguments.get("title") or "정해진 알림").strip()[:200]
        run_at = self._parse_run_at(arguments.get("run_at"), arguments.get("delay_minutes"))
        if run_at < time.time() - 5:
            raise ValueError("run_at_is_in_the_past")
        repeat_every = str(arguments.get("repeat_every") or "none").strip().lower()
        if repeat_every not in {"none", "daily", "weekday", "weekly"}:
            raise ValueError(f"unknown_repeat:{repeat_every}")
        schedule_id = uuid.uuid4().hex
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO schedules(id,title,prompt,session_id,run_at,status,created_at,updated_at,"
                "repeat_every,deliver_to,kind,routine) VALUES(?,?,?,?,?,'pending',?,?,?,?,?,?)",
                (schedule_id, title, message, "", run_at, now, now, repeat_every, "discord:home", "message", ""),
            )
        result = self.get(schedule_id)
        self.events.publish("schedule_created", result)
        return result

    def _default_discord_sender(self) -> Callable[[str], None]:
        def send(text: str) -> None:
            from .messaging import credentials
            from .messaging.discord_config import SETTINGS_FILE, DiscordSettings
            from .messaging.service import DiscordRest

            data_dir = Path(getattr(self.config, "data_dir", "") or self.database_path.parent)
            settings = DiscordSettings.load(data_dir / SETTINGS_FILE)
            if not settings.home_channel_id:
                raise RuntimeError("discord_home_channel_missing — 디스코드 홈 채널이 정해져 있지 않다.")
            token = credentials.load_bot_token(credentials.default_store())
            if not token:
                raise RuntimeError("discord_token_missing — 이 PC 에 디스코드 봇이 연결돼 있지 않다.")
            # 우리가 쓴 글이라도 아무도 부르지 않는다(@everyone 등 막음) — `send_dm` 과 같은 원칙.
            DiscordRest(token).call("POST", f"/channels/{settings.home_channel_id}/messages",
                                    {"content": text[:2000], "allowed_mentions": {"parse": []}})
        return send

    def _dispatch_message(self, row: dict[str, Any]) -> str:
        """정해진 문구 한 번 보내기. 실패해도 「돈 것」(ran) — 다음 회차는 그대로, 깨짐은 last_result 에(루틴과 같은 규칙)."""
        sender = self.send_discord or self._default_discord_sender()
        try:
            sender(str(row.get("prompt") or ""))
            note = {"ok": True, "sent_at": time.time()}
            self.events.publish("schedule_message_sent", {"schedule_id": row["id"]})
        except Exception as exc:  # noqa: BLE001 — 알림 하나 못 보냈다고 예약기를 멈추지 않는다
            note = {"ok": False, "error": str(exc)[:300]}
            self.events.publish("schedule_message_failed", {"schedule_id": row["id"], "error": str(exc)[:300]})
        with self._connect() as connection:
            connection.execute("UPDATE schedules SET last_result=?, updated_at=? WHERE id=?",
                               (json.dumps(note, ensure_ascii=False), time.time(), row["id"]))
        return "ran"

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
        if str(row.get("kind") or "prompt") == "routine":
            # 모델 없이 — 잡을 만들지 않는다(job_id 없음). 결과는 last_result 에.
            status, job_id = self._dispatch_routine(row), ""
        elif str(row.get("kind") or "") == "message":
            status, job_id = self._dispatch_message(row), ""
        else:
            status, job_id = self._dispatch_prompt(row)
        self._after_dispatch(row, status, job_id)

    def _dispatch_prompt(self, row: dict[str, Any]) -> tuple[str, str]:
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
        return status, job_id

    def _after_dispatch(self, row: dict[str, Any], status: str, job_id: str) -> None:
        # 반복이면 **다음 시각을 잡아 다시 pending 으로.** 지난 것은 안 몰아 돈다.
        # 루틴은 깨진 회차도 「돈 것」이다(ran) — 다음 회차는 그대로 잡고, 깨짐은 last_result 에 남는다.
        repeat_every = str(row.get("repeat_every") or "none")
        next_at = float(row["run_at"])
        if status in {"dispatched", "ran"} and repeat_every != "none":
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
                "결과를 메일로 보낸다. 생성에는 승인이 필요하다. "
                "레시피가 있는 사이트의 목록 모으기(예: 사람인 채용 공고)는 routine 을 주면 돌 때 모델 없이 "
                "레시피 주소로 받아 칸만 읽는다 — 이때 prompt 는 화면에 보일 한 줄 설명이다.",
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
                    "routine": {
                        "type": "object",
                        "description": "모델 없이 도는 루틴의 조건 칸. recipe(지금은 saramin) · query(검색어) · "
                                       "region(지역 **이름** — 서울·부산·경기…, 번호를 짐작해 넣지 않는다). "
                                       "주소는 넣지 않는다 — 레시피에서만 나온다",
                        "properties": {
                            "recipe": {"type": "string"},
                            "query": {"type": "string"},
                            "region": {"type": "string"},
                        },
                    },
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
