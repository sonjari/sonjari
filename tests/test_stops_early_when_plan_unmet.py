"""시킨 것이 남았는데 멈추면 **되받는다.**

## 무엇이었나 (2026-08-13 벤치 10판)

웹 과제 7개 중 **5개가 목록 화면의 값을 옮겨 적고 끝냈다.** 본문을 연 것은 0이다.

    크몽    2 걸음   (예산 12)
    쿠팡    3 걸음
    교보문고 4 걸음

계획 층은 그것을 알고 있었다 — 개수 요구는 `_sources_read`(본문을 연 주소)로 재니까
미달이었다. 그런데 **한마디도 못 했다.** `remaining_note` 는 예산이 바닥날 때만
흘러 들어가는데, 모델은 바닥 근처까지 가지도 않고 멈추기 때문이다.

끝난 뒤에 답에 ⚠ 를 붙이는 것은 정직할 뿐 도움이 안 된다. 아직 할 수 있을 때
말해 줘야 한다 — `remaining_note` 의 docstring 이 원래 그렇게 적혀 있다.

## 여기서 지키는 것

  1. 요구가 남았고 예산이 남았으면 → **되받는다**(그리고 되받는 횟수는 묶여 있다).
  2. 요구를 다 채웠으면 → 되받지 않는다. 다 한 사람을 붙잡는 것은 낭비다.
  3. 뽑아낸 요구가 없으면 → 되받지 않는다. **모르는 것을 못 했다고 하면 안 된다.**
  4. 되받는 말에는 **다음 수가 붙는다.** 남은 것만 알려 주면 같은 방법을 다시 쓴다.
"""

from __future__ import annotations

from alture_jarvis.agent import (
    _OPEN_THE_BODY_HINT,
    _PLAN_PUSHBACK_LIMIT,
    BrowserAgent,
    named_sources,
)
from alture_jarvis.plan import all_met, check, extract, remaining_note


def _read_steps(count: int) -> list[dict]:
    """본문을 `count` 개 연 걸음들."""
    return [
        {
            "tool": "browser_extract",
            "ok": True,
            "evidence": {"url": f"https://kmong.com/gig/{index}"},
        }
        for index in range(count)
    ]


def _list_only_steps() -> list[dict]:
    """목록만 본 걸음들 — 벤치의 크몽 판이 정확히 이 모양이다."""
    return [
        {"tool": "browser_open", "ok": True, "evidence": {"url": "https://kmong.com/"}},
        {"tool": "browser_site_search", "ok": True, "evidence": {}},
    ]


PROMPT = "크몽에서 AI 에이전트 개발 서비스 3개의 제목과 가격을 알려줘"


def _plan():
    """에이전트가 부르는 것과 **같은 방식**으로 뽑는다.

    ★ 이 시험을 처음 쓸 때 `extract(PROMPT)` 만 불렀다가, 개수 요구가 안 나와서
    시험이 깨졌다 — 그리고 그게 진짜 버그였다. 여기서 지름길을 쓰면 실제 경로와
    다른 것을 재게 된다.
    """
    return extract(PROMPT, has_named_source=bool(named_sources(PROMPT)))


def test_the_count_requirement_is_seen_at_all() -> None:
    """읽기 동사 없이 출처만 댄 문장에서도 개수 요구가 나와야 한다.

    이것이 안 되면 아래 것들이 전부 무의미하다 — 계획 층이 셀 것이 없으니
    되받을 것도 없고, 걸음 예산도 안 늘고, "다 채웠나" 판정도 안 돈다.
    """
    kinds = {item.kind for item in _plan()}
    assert "count" in kinds, "출처+개수를 읽기 요구로 안 본다"
    assert "site" in kinds
    # 지름길(예전 판)로는 안 나온다 — 무엇이 달라졌는지 시험이 직접 보여 준다.
    assert "count" not in {item.kind for item in extract(PROMPT)}


def test_reading_the_list_does_not_satisfy_the_count() -> None:
    """이게 성립해야 되받을 이유가 생긴다."""
    plan = _plan()
    steps = _list_only_steps()
    sources = BrowserAgent._sources_read(steps)
    results = check(plan, sources=sources, steps=steps)
    assert results, "요구를 하나도 못 뽑았다 — 그러면 이 갈래가 통째로 안 돈다"
    assert not all_met(results)
    assert remaining_note(results)


def test_opening_three_bodies_does_satisfy_it() -> None:
    """되받음이 **멈출 줄도** 알아야 한다. 안 그러면 영영 붙잡는다."""
    plan = _plan()
    steps = _list_only_steps() + _read_steps(3)
    results = check(plan, sources=BrowserAgent._sources_read(steps), steps=steps)
    assert all_met(results)
    assert remaining_note(results) == ""


def test_the_pushback_carries_the_next_move() -> None:
    """남은 것만 알려 주면 모델은 같은 방법을 다시 쓴다(목록을 한 번 더 읽는다).

    이 저장소가 실패마다 다음 수를 같이 주는 것과 같은 규율이다.
    """
    assert "browser_open_result" in _OPEN_THE_BODY_HINT
    assert "browser_extract" in _OPEN_THE_BODY_HINT
    assert "목록" in _OPEN_THE_BODY_HINT


def test_the_pushback_is_bounded() -> None:
    """못 하는 일을 계속 시키면 같은 말만 오간다."""
    assert 1 <= _PLAN_PUSHBACK_LIMIT <= 3


# ── 헛돎 판정: 아직 말도 안 해 준 것을 포기로 세지 않는다 ────────────────────


class _Agent:
    """`_autonomous_extension` 만 떼어 본다 — 브라우저도 모델도 필요 없다."""

    class _Config:
        agent_autonomous_max_steps = 40
        agent_autonomous_lease_sec = 900
        browser_task_timeout_sec = 180

    config = _Config()

    _is_stuck = staticmethod(lambda steps: True)  # 제자리라고 치고
    _did_something_irreversible = staticmethod(lambda steps: "")


def _extension(plan_results, *, plan_told: bool):
    return BrowserAgent._autonomous_extension(
        _Agent(), steps=[{"tool": "browser_click", "ok": True}] * 8,
        elapsed=10.0, plan_results=plan_results, plan_told=plan_told,
    )


def _unmet():
    plan = _plan()
    return check(plan, sources=[], steps=_list_only_steps())


def test_first_stuck_with_an_unmet_goal_gets_one_more_window() -> None:
    """다나와 정렬 판이 이 모양이었다 — 정렬까지 걸어 놓고 목록은 한 줄도 안 읽었는데
    `wrapped_up:no_progress` 로 끝났다. 그때까지 무엇이 남았는지 들은 적이 없다."""
    extra, why = _extension(_unmet(), plan_told=False)
    assert extra > 0
    assert why == "stuck_but_goal_unmet_first_notice"


def test_stuck_after_being_told_does_end() -> None:
    """듣고도 제자리면 접는다. 안 그러면 11.7분 헛돎이 돌아온다."""
    extra, why = _extension(_unmet(), plan_told=True)
    assert extra == 0
    assert why == "no_progress"


def test_stuck_with_nothing_to_measure_still_ends() -> None:
    """요구를 못 뽑은 요청까지 붙잡으면, 모르는 것을 핑계로 시간을 쓰는 것이다."""
    extra, why = _extension([], plan_told=False)
    assert extra == 0
    assert why == "no_progress"
