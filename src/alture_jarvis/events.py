from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from .models import EventRecord


class EventBus:
    """Thread-safe bounded event history for the backend and future HUD."""

    def __init__(self, max_events: int = 1000) -> None:
        self._events: deque[EventRecord] = deque(maxlen=max_events)
        self._seq = 0
        self._condition = threading.Condition()
        self._listeners: list[Callable[[EventRecord], None]] = []

    def publish(self, event: str, payload: dict[str, Any] | None = None) -> EventRecord:
        with self._condition:
            self._seq += 1
            record = EventRecord(
                seq=self._seq,
                event=event,
                timestamp=time.time(),
                payload=dict(payload or {}),
            )
            self._events.append(record)
            self._condition.notify_all()
            listeners = list(self._listeners)
        # 청취자는 **잠금 밖에서** 부른다 — 느리거나 죽어도 발행과 다른 청취를 막지 않는다.
        for listener in listeners:
            try:
                listener(record)
            except Exception:  # noqa: BLE001
                pass
        return record

    def add_listener(self, listener: Callable[[EventRecord], None]) -> None:
        """발행될 때마다 부를 함수를 등록한다. 예외는 삼킨다."""
        with self._condition:
            self._listeners.append(listener)

    def get_since(self, after: int = 0, limit: int = 200) -> list[EventRecord]:
        with self._condition:
            return [event for event in self._events if event.seq > after][: max(1, min(limit, 500))]

    def wait_since(self, after: int, timeout: float = 10.0) -> list[EventRecord]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._seq <= after:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._condition.wait(timeout=remaining)
            return [event for event in self._events if event.seq > after]

    @property
    def sequence(self) -> int:
        with self._condition:
            return self._seq

