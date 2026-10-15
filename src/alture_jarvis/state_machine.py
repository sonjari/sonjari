from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .events import EventBus
from .models import JarvisState


_ALLOWED: dict[JarvisState, set[JarvisState]] = {
    JarvisState.IDLE: {JarvisState.LISTENING, JarvisState.ROUTING, JarvisState.WORKING, JarvisState.ERROR, JarvisState.STOPPED},
    JarvisState.LISTENING: {JarvisState.TRANSCRIBING, JarvisState.IDLE, JarvisState.ERROR, JarvisState.STOPPED},
    JarvisState.TRANSCRIBING: {JarvisState.ROUTING, JarvisState.IDLE, JarvisState.ERROR, JarvisState.STOPPED},
    JarvisState.ROUTING: {JarvisState.WORKING, JarvisState.SPEAKING, JarvisState.WAITING_APPROVAL, JarvisState.WAITING_CONTINUATION, JarvisState.IDLE, JarvisState.ERROR, JarvisState.STOPPED},
    JarvisState.WORKING: {JarvisState.SPEAKING, JarvisState.WAITING_APPROVAL, JarvisState.WAITING_CONTINUATION, JarvisState.IDLE, JarvisState.ERROR, JarvisState.STOPPED},
    JarvisState.SPEAKING: {JarvisState.LISTENING, JarvisState.IDLE, JarvisState.ERROR, JarvisState.STOPPED},
    JarvisState.WAITING_APPROVAL: {JarvisState.WORKING, JarvisState.IDLE, JarvisState.ERROR, JarvisState.STOPPED},
    JarvisState.WAITING_CONTINUATION: {JarvisState.WORKING, JarvisState.IDLE, JarvisState.ERROR, JarvisState.STOPPED},
    JarvisState.ERROR: {JarvisState.IDLE, JarvisState.STOPPED},
    JarvisState.STOPPED: set(),
}


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    state: JarvisState
    changed_at: float
    reason: str


class InvalidStateTransition(RuntimeError):
    pass


class StateMachine:
    def __init__(self, events: EventBus, initial: JarvisState = JarvisState.IDLE) -> None:
        self._events = events
        self._lock = threading.RLock()
        self._snapshot = StateSnapshot(initial, time.time(), "startup")

    def transition(self, target: JarvisState, reason: str = "") -> StateSnapshot:
        with self._lock:
            source = self._snapshot.state
            if target == source:
                return self._snapshot
            if target not in _ALLOWED[source]:
                raise InvalidStateTransition(f"{source.value} -> {target.value} is not allowed")
            self._snapshot = StateSnapshot(target, time.time(), reason)
            self._events.publish(
                "state_changed",
                {"from": source.value, "to": target.value, "reason": reason},
            )
            return self._snapshot

    def fail(self, reason: str) -> StateSnapshot:
        with self._lock:
            if self._snapshot.state == JarvisState.STOPPED:
                return self._snapshot
            if self._snapshot.state == JarvisState.ERROR:
                self._snapshot = StateSnapshot(JarvisState.ERROR, time.time(), reason)
                return self._snapshot
        return self.transition(JarvisState.ERROR, reason)

    def reset(self, reason: str = "reset") -> StateSnapshot:
        with self._lock:
            if self._snapshot.state == JarvisState.IDLE:
                return self._snapshot
        return self.transition(JarvisState.IDLE, reason)

    def snapshot(self) -> StateSnapshot:
        with self._lock:
            return self._snapshot
