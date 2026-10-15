"""**못 끝내는 일 하나가 할 수 있는 일까지 막으면 안 된다.**

## 실제로 일어난 일 (2026-09-10)

사슬 벤치에서 세 판이 조사를 다 하고 표까지 짜 놓고 **파일을 안 만들고** 끝났다.

    r1 사람인   16걸음 · 574초 (예산 900) · 읽기 5곳 · 파일 0
    r1 yes24    30걸음 · 387초             · 읽기 6곳 · 파일 0
    r2 위시켓   16걸음 · 250초             · 읽기 3곳 · 파일 0

셋 다 `artifact` 요구가 있었고 걸음·시간 예산도 남아 있었는데 되받기를 **한 번도**
못 받았다. 원인은 `_plan_focus_stage` 였다 — `count` 가 안 끝나면 늘 `"read"` 를
돌려주는데, 셋의 `count` 는 「답 항목 중 읽은 원문에 없는 이름 있음」이라 끝날 수가
없었다. 읽기 되받기 두 번을 거기 다 쓰면 바깥 `if` 가 통째로 거짓이 되고
**산출물 단계는 자기 차례를 영영 못 받는다.**
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Req:
    kind: str


def _results(*unmet: str) -> list[tuple[_Req, bool, str]]:
    """든 것은 미달, 안 든 것은 충족."""
    every = ("count", "site", "artifact", "verify", "action")
    return [(_Req(kind), kind not in unmet, "") for kind in every]


def test_read_comes_first_while_it_still_has_budget() -> None:
    from alture_jarvis.agent import _PLAN_PUSHBACK_LIMIT, _plan_focus_stage

    stage = _plan_focus_stage(
        _results("count", "artifact"), spent={}, limit=_PLAN_PUSHBACK_LIMIT
    )
    assert stage == "read"


def test_a_spent_stage_yields_to_the_next_one() -> None:
    """읽기 예산을 다 썼으면 **산출물이 자기 차례를 받는다.**"""
    from alture_jarvis.agent import _PLAN_PUSHBACK_LIMIT, _plan_focus_stage

    stage = _plan_focus_stage(
        _results("count", "artifact"),
        spent={"read": _PLAN_PUSHBACK_LIMIT},
        limit=_PLAN_PUSHBACK_LIMIT,
    )
    assert stage == "artifact", "못 끝내는 읽기가 산출물을 굶겼다"


def test_when_everything_is_spent_it_names_the_first_gap_not_unknown() -> None:
    """전부 다 썼으면 첫 미달 단계를 돌려준다.

    여기서 `unknown` 을 내면 바깥 예산 검사가 `unknown` 몫으로 **없던 되받기를 두 번
    더** 내준다 — 못 하는 일을 두 번 더 시키는 것이다.
    """
    from alture_jarvis.agent import _PLAN_PUSHBACK_LIMIT, _plan_focus_stage

    stage = _plan_focus_stage(
        _results("count", "artifact"),
        spent={"read": _PLAN_PUSHBACK_LIMIT, "artifact": _PLAN_PUSHBACK_LIMIT},
        limit=_PLAN_PUSHBACK_LIMIT,
    )
    assert stage == "read"


def test_the_old_call_shape_still_answers() -> None:
    """예산을 안 넘기면 옛 동작 그대로다 — 화면·눈금이 이 이름을 읽는다."""
    from alture_jarvis.agent import _plan_focus_stage

    assert _plan_focus_stage(_results("artifact")) == "artifact"
    assert _plan_focus_stage(_results("verify")) == "verify"
    assert _plan_focus_stage(_results("action")) == "action"
    assert _plan_focus_stage(_results()) == "unknown"
