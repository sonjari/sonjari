"""승인된 외부 쓰기를 실행 전 대상과 실행 후 증거에 묶는 공통 계약."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ProofSpec:
    capture_before: Callable[[dict[str, Any]], dict[str, Any]]
    same_target: Callable[[dict[str, Any], dict[str, Any]], bool]
    finalize: Callable[[dict[str, Any], Any], dict[str, Any]]
    capture_current: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    capture_after: Callable[[dict[str, Any], Any], dict[str, Any]] | None = None

    def recapture(self, arguments: dict[str, Any]) -> dict[str, Any]:
        capture = self.capture_current or self.capture_before
        return dict(capture(arguments) or {})

    def after(self, arguments: dict[str, Any], result: Any) -> dict[str, Any]:
        if self.capture_after is None:
            return {}
        return dict(self.capture_after(arguments, result) or {})


def same_fingerprint(before: dict[str, Any], current: dict[str, Any]) -> bool:
    """빈 지문은 같다고 치지 않는다. 모르면 실행하지 않는다."""
    expected = str(before.get("fingerprint") or "")
    actual = str(current.get("fingerprint") or "")
    return bool(expected) and expected == actual


def finalize_proof(before: dict[str, Any], result: Any) -> dict[str, Any]:
    """도구 결과를 before/after 한 봉투로 묶는다."""
    out = dict(result) if isinstance(result, dict) else {"value": result}
    verified = out.get("verified") is True
    after = {
        "url": str(out.get("url") or "")[:1000],
        "verified": verified,
        "verification": out.get("verification"),
        "what_changed": list(out.get("what_changed") or []),
    }
    out["verified"] = verified
    out["proof"] = {"before": dict(before), "after": after}
    if not verified:
        out.setdefault(
            "instruction",
            "쓰기 동작은 실행됐지만 결과를 확인하지 못했다. 같은 동작을 다시 실행하지 마라.",
        )
    return out
