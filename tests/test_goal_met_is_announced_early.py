"""「다 채웠다」가 **채운 그때** 나가는지 본다.

## 무엇이 고장이었나

`plan.satisfied_note` 는 진작 있었다. 그런데 `agent` 가 그것을 **예산이 바닥난
자리에서만** 만들었다(`if now >= deadline or len(steps) + 1 >= step_limit:`).
그래서 요구를 다 채운 뒤에도 아무도 멈추라고 안 했고, 모델은 시간이 다 될 때까지
계속 팠다.

2026-08-23 실측(대학알리미, 세 모델이 같은 판을 돎):

    젬마4 26B-A4B    4걸음   43초   ← 스스로 멈췄다
    젬마4 31B-QAT   10걸음  266초   ← 답을 쥐고 6걸음 더 팠다
    퀀3.8-27B       11걸음   90초   ← 같다

셋 다 **똑같은 4걸음**(open → site_search → open_result → extract)에 답에 닿았다.
차이는 실력이 아니라 **멈출 줄 알았느냐**였다. 그러니 "26B 가 가장 빠르다"는
"26B 가 가장 일찍 포기한다"와 구별이 안 됐다 — 눈금이 게으름을 실력으로 읽고 있었다.

## 여기서 지키는 것

요구가 다 채워지면 **그 턴에** `[시스템] ★ 시킨 것을 다 채웠다…` 가 대화에 들어간다.
예산이 남아 있어도 들어가야 한다. 그게 이 검사의 전부다.
"""

from __future__ import annotations

from alture_jarvis.plan import (
    Requirement,
    all_met as plan_all_met,
    check as check_plan,
    extract as extract_plan,
    remaining_note,
    satisfied_note,
)


def _results(reqs, sources, steps):
    return check_plan(reqs, sources=sources, steps=steps)


def test_satisfied_note_appears_the_moment_the_site_requirement_is_met() -> None:
    """대학알리미 판 그대로 — 그 사이트를 한 번 읽으면 곧바로 「다 채웠다」."""
    reqs = extract_plan(
        "대학알리미에서 취업률 지표를 어디서 볼 수 있는지 찾아서 알려줘",
        has_named_source=True,
        known_sites={"대학알리미": ("academyinfo.go.kr",)},
    )
    assert reqs, "이 문장에서는 요구가 하나는 나와야 한다(사이트 지목)"

    # 아직 아무것도 안 읽었다 → 남은 것이 있다고 말해야 한다.
    before = _results(reqs, [], [])
    assert not plan_all_met(before)
    assert remaining_note(before)
    assert satisfied_note(before) == ""

    # 그 사이트를 실제로 읽었다 → 곧바로 「다 채웠다」로 바뀐다.
    after = _results(
        reqs,
        ["https://academyinfo.go.kr/intro/intro0200/intro.do"],
        [{"tool": "browser_extract", "ok": True}],
    )
    assert plan_all_met(after)
    note = satisfied_note(after)
    assert note, "다 채웠으면 멈추라는 말이 있어야 한다"
    assert "더 찾지 말고" in note


def test_the_agent_loop_checks_satisfaction_outside_the_budget_branch() -> None:
    """★ 진짜 불변식: 그 판정이 **예산 가지 안에만** 살면 안 된다.

    위 검사는 plan.py 만 본다. 고장은 agent.py 가 그것을 언제 부르느냐였으므로,
    루프 머리에서도 부르는지 **소스에서** 확인한다. 되돌아가면 여기서 걸린다.
    """
    import inspect

    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent)
    loop_head = source.index(
        "while (auto_continue_budget or len(steps) < step_limit) and not finish_now:"
    )
    budget_branch = source.index("if now >= deadline or len(steps) + 1 >= step_limit:")
    early = source[loop_head:budget_branch]
    assert "plan_all_met" in early, (
        "충족 판정이 예산 소진 가지에만 있다 — 다 채우고도 시간이 다 될 때까지 판다"
    )
    assert "satisfied_note" in early, "다 채웠다는 말이 그 자리에서 나가야 한다"


def test_an_empty_plan_is_not_treated_as_done() -> None:
    """요구를 못 뽑은 요청은 「다 됐다」가 아니라 「모른다」다.

    이게 깨지면 문체·구성처럼 애초에 안 뽑는 요구가 걸린 요청이 첫 걸음에 끝난다.
    """
    assert not plan_all_met([])
    assert satisfied_note([]) == ""


def test_a_partly_met_plan_still_says_what_is_left() -> None:
    reqs = [
        Requirement(kind="count", label="3개 이상 직접 열어 읽기", target=3),
        Requirement(kind="site", label="무신사에서 하기", target=("musinsa.com",)),
    ]
    results = _results(
        reqs,
        ["https://www.musinsa.com/products/1"],
        [{"tool": "browser_extract", "ok": True}],
    )
    assert not plan_all_met(results)
    assert "3개 이상" in remaining_note(results)
    assert satisfied_note(results) == ""
