from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class JarvisState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    ROUTING = "routing"
    WORKING = "working"
    SPEAKING = "speaking"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_CONTINUATION = "waiting_continuation"
    ERROR = "error"
    STOPPED = "stopped"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_CONTINUATION = "waiting_continuation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class RiskLevel(IntEnum):
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4

    @classmethod
    def parse(cls, value: Any) -> "RiskLevel":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        text = str(value or "L0").upper().strip()
        if text.startswith("L"):
            text = text[1:]
        return cls(int(text))

    def label(self) -> str:
        return f"L{int(self)}"


@dataclass(slots=True)
class EventRecord:
    seq: int
    event: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolResult:
    ok: bool
    tool: str
    status: str = "completed"
    result: Any = None
    error: str = ""
    approval_nonce: str = ""
    risk_level: str = "L0"
    #: 이 도구가 실제로 돈 시간(ms). **핸들러 호출만** 재고 승인 대기는 안 센다.
    #
    # ★ 없던 값이다 (2026-09-09). `Observation.took_ms` 칸은 처음부터 있었는데
    #   아무도 안 채워 **전부 0** 이었다. 그래서 판이 456초 걸렸을 때 그것이
    #   도구 때문인지 모델 생각 때문인지 가를 수가 없었다 — 편차를 고치려는데
    #   무엇을 고쳐야 하는지 모르는 상태였다.
    took_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
