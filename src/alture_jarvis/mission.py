"""장기 작업이 판을 건너도 잃지 말아야 할 작은 임무 장부.

새 플래너가 아니다. ``plan.py``가 결정론적으로 뽑고 대조한 사실을 기존
``agent_checkpoints.state_json`` 안에 사람이 읽을 수 있는 형태로 같이 저장한다.
DB schema와 실행 루프를 바꾸지 않는 것이 이 모듈의 경계다.
"""

from __future__ import annotations

import time
from typing import Any

from .plan import Requirement, check


_CONTEXT_MARKER = "[MISSION CHECKPOINT]"
_INVARIANTS = [
    "이미 성공한 외부 쓰기를 반복하지 않는다",
    "실행됐지만 확인하지 못한 쓰기를 자동 재시도하지 않는다",
    "로그인·봇 확인을 우회하지 않고 사람 문으로 넘긴다",
    "완료라고 말하기 전에 done_when을 실제 증거와 대조한다",
]


def build_mission(
    *,
    prompt: str,
    requirements: list[Requirement],
    sources: list[str],
    steps: list[dict[str, Any]],
    fingerprints: dict[str, int],
) -> dict[str, Any]:
    """현재까지 확인된 사실로 직렬화 가능한 임무 상태를 만든다."""
    results = check(requirements, sources=sources, steps=steps)
    done_when = [requirement.label for requirement in requirements]
    if not done_when:
        done_when = ["사용자 요청에 근거 있는 최종 답을 반환한다"]
    remaining = [requirement.label for requirement, ok, _ in results if not ok]
    last_verified_step = 0
    for position, step in enumerate(steps, start=1):
        if step.get("ok") and step.get("evidence"):
            try:
                last_verified_step = int(step.get("step") or position)
            except (TypeError, ValueError):
                last_verified_step = position
    return {
        "goal": str(prompt or "")[:4000],
        "done_when": done_when,
        "remaining": remaining,
        "invariants": list(_INVARIANTS),
        "last_verified_step": last_verified_step,
        "attempt_budget": {
            "max_same_call": 3,
            "used": {str(key): int(value) for key, value in fingerprints.items()},
        },
        "updated_at": time.time(),
    }


def resume_goal(current_prompt: str, checkpoint: dict[str, Any]) -> str:
    """재개 호출의 짧은 문구보다 저장된 원래 목표를 우선한다."""
    mission = dict(checkpoint.get("mission") or {})
    return str(mission.get("goal") or checkpoint.get("prompt") or current_prompt)


def inject_mission_context(
    messages: list[dict[str, Any]], mission: dict[str, Any]
) -> list[dict[str, Any]]:
    """재개 문맥에 임무를 정확히 한 벌만 넣는다."""
    if not mission:
        return list(messages)
    kept = [
        dict(item)
        for item in messages
        if _CONTEXT_MARKER not in str(item.get("content") or "")
    ]
    done_when = "\n".join(f"- {item}" for item in mission.get("done_when") or [])
    remaining_items = list(mission.get("remaining") or [])
    remaining = (
        "\n".join(f"- {item}" for item in remaining_items)
        if remaining_items
        else "- 결정론적으로 대조 가능한 남은 항목 없음; 최종 답 전 전체 목표를 다시 확인"
    )
    invariants = "\n".join(f"- {item}" for item in mission.get("invariants") or [])
    kept.append(
        {
            "role": "system",
            "content": (
                f"{_CONTEXT_MARKER}\n"
                f"원래 목표: {str(mission.get('goal') or '')[:2000]}\n"
                f"완료 조건:\n{done_when}\n"
                f"남은 항목:\n{remaining}\n"
                f"불변 조건:\n{invariants}\n"
                f"마지막 검증 단계: {int(mission.get('last_verified_step') or 0)}\n"
                "이미 끝낸 mutation을 되풀이하지 말고 남은 항목부터 이어가라."
            ),
        }
    )
    return kept
