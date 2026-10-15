"""레시피 정기 실행 — 정해 둔 시각에 **모델 없이** 레시피를 돌리고, 지난번보다 나빠졌을 때만 부른다 (2026-09-27 · 게임 팩).

## 왜 (전략안 §50 「공짜 반복」)

클로드·코덱스는 부를 때만, 토큰을 쓸 때만 돈다. 새벽 3시에 아무도 안 부르면 안 돈다. 온텔릭은 한 번 받은 레시피를
매일 공짜로 돌린다 — 여기에는 **모델이 한 번도 끼지 않는다.** 레시피는 고정된 C# 이고 값은 사람이 정해 둔 것이다.
그래서 작은 모델·모델 없음으로도 결과가 같다.

## 판정 규칙 (관찰 초소 `watch.py` 와 같은 셈법)

- 모델에게 「나빠졌나」를 묻지 않는다. 레시피가 적어 둔 숫자(`watch`)를 **지난번 숫자**와 비교한다.
- 늘었을 때만 부른다. 처음 도는 판은 기준만 잡고 조용히 있는다.
- 에디터가 그 프로젝트를 열고 있으면(배치 모드가 못 연다) **미룬다** — 그날 안에 닫히면 그때 돈다. 대신 닫지 않는다.
- 만드는 것·지우는 것은 사람만(설정 화면). 도구로 모델에게 주지 않는다 — 스스로 도는 일감을 만드는 것은 사람의 동의다.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .unity_tools import editor_is_open

_TICK_SEC = 60
_HISTORY = 20
_DAYS = ("daily", "weekday", "weekly")


def watch_numbers(result: dict[str, Any], keys: dict[str, str] | list[str]) -> dict[str, float]:
    """레시피 결과에서 지켜볼 숫자만 뽑는다. `max:목록.필드`·`sum:목록.필드` 는 목록을 모아 센다."""
    out: dict[str, float] = {}
    for key in keys:
        value: Any = None
        if ":" in key:
            how, path = key.split(":", 1)
            field, _, sub = path.partition(".")
            items = result.get(field) if isinstance(result.get(field), list) else []
            numbers = [float(item.get(sub)) for item in items if isinstance(item, dict) and isinstance(item.get(sub), (int, float))]
            if numbers:
                value = max(numbers) if how == "max" else sum(numbers)
        elif isinstance(result.get(key), (int, float)) and not isinstance(result.get(key), bool):
            value = float(result[key])
        if value is not None:
            out[key] = value
    return out


class RecipeSchedule:
    def __init__(
        self,
        config: Any,
        unity_tools: Any,
        *,
        attention: Any = None,
        events: Any = None,
        now: Callable[[], datetime] = datetime.now,
        project_open: Callable[[Path], bool] = editor_is_open,
    ) -> None:
        self.config = config
        self.unity = unity_tools
        self.attention = attention
        self.events = events
        self.now = now
        self.project_open = project_open
        self.path = Path(config.data_dir) / "packs" / "game" / "schedules.json"
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running: set[str] = set()

    # ── 장부 ─────────────────────────────────────────────────────────────
    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [item for item in data.get("schedules") or [] if isinstance(item, dict) and item.get("id")]

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schedules": items}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def listing(self) -> list[dict[str, Any]]:
        with self._lock:
            items = self._load()
        recipes = self.unity.recipes()
        for item in items:
            recipe = recipes.get(item["recipe"]) or {}
            item["title"] = str(recipe.get("title") or item["recipe"])
            item["watch_labels"] = dict(recipe.get("watch") or {})
            item["running"] = item["id"] in self._running
        return items

    def add(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """**사람만** 부른다(설정 화면). 레시피·프로젝트·값을 지금 검사한다 — 새벽에 처음 실패하지 않게."""
        recipe_name = str(arguments.get("recipe") or "").strip()
        recipe = self.unity.recipes().get(recipe_name)
        if recipe is None:
            raise ValueError(f"unknown_recipe: {recipe_name}")
        if str(recipe.get("risk") or "L2").upper() not in {"L0", "L1"}:
            # 바꾸는 레시피를 아무도 안 보는 새벽에 돌리지 않는다 — 승인할 사람이 없다.
            raise ValueError("schedule_read_only: 정기 실행은 읽기만 하는 레시피만 됩니다")
        params = self.unity._params(recipe, arguments.get("params") if isinstance(arguments.get("params"), dict) else {})  # noqa: SLF001
        project = self.unity._project({"project": arguments.get("project")}, write=True)  # noqa: SLF001
        at = str(arguments.get("at") or "03:00").strip()
        try:
            hour, minute = (int(part) for part in at.split(":", 1))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except ValueError as exc:
            raise ValueError("schedule_time: at 은 HH:MM (예: 03:00)") from exc
        days = str(arguments.get("days") or "daily")
        if days not in _DAYS:
            raise ValueError(f"schedule_days: {list(_DAYS)}")
        item = {
            "id": uuid.uuid4().hex[:10], "recipe": recipe_name, "project": str(project), "params": params,
            "at": f"{hour:02d}:{minute:02d}", "days": days, "enabled": True, "created_at": time.time(),
            "last_date": "", "last": None, "baseline": None, "history": [], "deferred": "",
        }
        with self._lock:
            items = self._load()
            items.append(item)
            self._save(items)
        return item

    def remove(self, schedule_id: str) -> dict[str, Any]:
        with self._lock:
            items = self._load()
            kept = [item for item in items if item["id"] != schedule_id]
            if len(kept) == len(items):
                raise ValueError(f"unknown_schedule: {schedule_id}")
            self._save(kept)
        return {"ok": True, "removed": schedule_id}

    def set_enabled(self, schedule_id: str, on: bool) -> dict[str, Any]:
        with self._lock:
            items = self._load()
            for item in items:
                if item["id"] == schedule_id:
                    item["enabled"] = bool(on)
                    self._save(items)
                    return item
        raise ValueError(f"unknown_schedule: {schedule_id}")

    # ── 돌기 ─────────────────────────────────────────────────────────────
    def _due(self, item: dict[str, Any], now: datetime) -> bool:
        if not item.get("enabled") or item["id"] in self._running:
            return False
        today = now.strftime("%Y-%m-%d")
        if item.get("last_date") == today:
            return False
        if item.get("days") == "weekday" and now.weekday() >= 5:
            return False
        if item.get("days") == "weekly" and now.weekday() != datetime.fromtimestamp(float(item.get("created_at") or 0)).weekday():
            return False
        hour, minute = (int(part) for part in str(item.get("at") or "03:00").split(":", 1))
        return (now.hour, now.minute) >= (hour, minute)

    def tick(self) -> list[dict[str, Any]]:
        if self.unity.packs is not None and not self.unity.enabled():
            return []
        now = self.now()
        with self._lock:
            due = [item for item in self._load() if self._due(item, now)]
        return [self.run(item["id"], scheduled=True) for item in due]

    def run(self, schedule_id: str, *, scheduled: bool = False) -> dict[str, Any]:
        with self._lock:
            item = next((row for row in self._load() if row["id"] == schedule_id), None)
            if item is None:
                raise ValueError(f"unknown_schedule: {schedule_id}")
            if schedule_id in self._running:
                return {"ok": False, "reason": "already_running"}
            self._running.add(schedule_id)
        try:
            return self._run(item, scheduled=scheduled)
        finally:
            self._running.discard(schedule_id)

    def _run(self, item: dict[str, Any], *, scheduled: bool) -> dict[str, Any]:
        now = self.now()
        project = Path(item["project"])
        if self.project_open(project):
            # 사람이 에디터로 일하는 중이다 — 닫지 않고 미룬다. 그날 안에 닫히면 다음 째깍에 돈다.
            self._update(item["id"], deferred=f"{now:%H:%M} 에디터가 열려 있어 미룸")
            return {"ok": False, "deferred": True, "reason": "editor_open"}
        started = time.time()
        try:
            outcome = self.unity.run_recipe({"recipe": item["recipe"], "project": item["project"], "params": item.get("params") or {}})
        except Exception as exc:  # noqa: BLE001 — 한 판의 실패가 초소를 죽이면 안 된다
            outcome = {"verified": False, "failure": f"{type(exc).__name__}: {str(exc)[:200]}", "result": {}}
        recipe = self.unity.recipes().get(item["recipe"]) or {}
        labels = dict(recipe.get("watch") or {})
        numbers = watch_numbers(outcome.get("result") or {}, labels) if outcome.get("verified") else {}
        previous = dict((item.get("last") or {}).get("numbers") or {})
        worse = {key: [previous[key], value] for key, value in numbers.items() if key in previous and value > previous[key]}
        run = {
            "at": started, "scheduled": scheduled, "verified": bool(outcome.get("verified")),
            "failure": str(outcome.get("failure") or ""), "elapsed_sec": outcome.get("elapsed_sec"),
            "numbers": numbers, "worse": worse, "result_file": outcome.get("result_file", ""),
        }
        history = [run, *(item.get("history") or [])][:_HISTORY]
        changes: dict[str, Any] = {"history": history, "deferred": "", "last_date": now.strftime("%Y-%m-%d")}
        if run["verified"]:
            changes["last"] = run
            if item.get("baseline") is None:
                changes["baseline"] = run
        self._update(item["id"], **changes)
        self._tell(item, recipe, run, labels)
        return {"ok": run["verified"], **run}

    def _update(self, schedule_id: str, **changes: Any) -> None:
        with self._lock:
            items = self._load()
            for row in items:
                if row["id"] == schedule_id:
                    row.update(changes)
            self._save(items)

    def _tell(self, item: dict[str, Any], recipe: dict[str, Any], run: dict[str, Any], labels: dict[str, str]) -> None:
        title = str(recipe.get("title") or item["recipe"])
        project = Path(item["project"]).name
        if self.events is not None:
            try:
                self.events.publish("unity_schedule_ran", {"schedule_id": item["id"], "recipe": item["recipe"], "project": project,
                                                           "verified": run["verified"], "worse": run["worse"]})
            except Exception:  # noqa: BLE001
                pass
        if self.attention is None:
            return
        if run["worse"]:
            parts = [f"{labels.get(key, key)} {_fmt(old)}→{_fmt(new)}" for key, (old, new) in run["worse"].items()]
            note = ", ".join(parts)
            message = f"{project} 프로젝트의 「{title}」 정기 점검에서 지난번보다 늘었습니다: {note}. 설정 › 팩 › 게임 팩에서 결과를 보실 수 있습니다."
            speech = f"{project} 정기 점검에서 {parts[0]} 로 늘었습니다."
        elif not run["verified"] and run["scheduled"]:
            message = f"{project} 프로젝트의 「{title}」 정기 점검이 끝나지 못했습니다: {run['failure'] or '결과 없음'}."
            speech = f"{project} 정기 점검이 실패했습니다."
            note = "실패"
        else:
            return
        try:
            self.attention.announce(code="unity_schedule", tool=f"unity_schedule:{item['id']}",
                                    title=f"게임 팩 정기 점검 — {title}", message=message, speech=speech, detail=note)
        except Exception:  # noqa: BLE001 — 못 부르면 이벤트만 남는다
            pass

    # ── 스레드 ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ontelic-unity-schedule", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(_TICK_SEC):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — 다음 째깍에 다시
                pass


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


__all__ = ["RecipeSchedule", "watch_numbers"]
