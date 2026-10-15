"""재는 꾸러미가 **판 사이의 흔들림**과 「이 차이를 가려내려면 몇 판」을 같이 적는다 (2026-10-13).

밖에서 받은 지적: 한 조건을 세 번 재고 두 조건을 견줬는데, 같은 조건 여덟 판이 평균 4.6줄 · 흔들림 2.2줄로 오르내렸다.
그 흔들림에서 2줄 차이를 가려내려면 조건마다 열아홉 판이 든다 — 세 판으로는 차이인지 우연인지 모른다.

    조건마다 필요한 판 수 ≈ 16 × (흔들림 ÷ 가려내려는 차이)²

합계 한 줄(「온전한 줄 5/9」)만 적으면 읽는 사람이 그 숫자를 믿을 만한지 알 길이 없다. 그래서 결과 파일과 끝 인사에
판마다의 합 · 평균 · 흔들림 · 더 잴 판 수 · 모자란 줄의 까닭을 같이 싣는다. 숫자와 정해진 낱말뿐이다.
"""
from __future__ import annotations

import math

from alture_jarvis import measure_kit as kit


def _run(round_no: int, task: str, states: tuple[str, str, str]) -> dict[str, object]:
    shops = dict(zip(kit.SHOPS, states))
    return {"task": task, "round": round_no, "shops": shops, "whole_rows": sum(1 for state in states if state == "온전")}


def _rounds(per_round: list[int]) -> list[dict[str, object]]:
    """판마다 과제 셋 · 온전한 줄 합이 주어진 값이 되게."""
    runs = []
    tasks = list(kit.PRICE_TASKS)[:3]
    for number, total in enumerate(per_round, 1):
        left = total
        for task in tasks:
            whole = min(3, left)
            left -= whole
            runs.append(_run(number, task, tuple(["온전"] * whole + ["줄 없음"] * (3 - whole))))  # type: ignore[arg-type]
    return runs


def test_the_summary_gives_each_round_the_mean_and_the_spread() -> None:
    summary = kit.price_summary(_rounds([2, 7, 5, 4, 7, 3, 6, 3]))

    assert summary["per_round"] == [2, 7, 5, 4, 7, 3, 6, 3] and summary["out_of"] == 9
    assert summary["mean"] == 4.6
    assert summary["spread"] == 1.9, "표본 표준편차 — 판마다의 합이 오르내리는 폭"


def test_it_says_how_many_rounds_a_difference_would_take() -> None:
    summary = kit.price_summary(_rounds([2, 7, 5, 4, 7, 3, 6, 3]))
    spread = summary["spread"]

    assert summary["rounds_to_tell"] == {"2": math.ceil(16 * (spread / 2) ** 2), "3": math.ceil(16 * (spread / 3) ** 2)}
    assert summary["rounds_to_tell"]["2"] > summary["rounds_to_tell"]["3"], "작은 차이일수록 더 많이 재야 한다"


def test_fewer_than_three_rounds_claim_no_spread() -> None:
    """두 판의 차이로 흔들림을 말하면 그 숫자가 다시 우연이다."""
    for per_round in ([5], [5, 6]):
        summary = kit.price_summary(_rounds(per_round))
        assert summary["mean"] is not None
        assert summary["spread"] is None and summary["rounds_to_tell"] is None


def test_rounds_that_never_wobbled_do_not_promise_that_one_round_is_enough() -> None:
    summary = kit.price_summary(_rounds([9, 9, 9]))

    assert summary["spread"] == 0.0
    assert summary["rounds_to_tell"] == {"2": 3, "3": 3}, "흔들림 0 은 그 판들에서 본 것일 뿐이다 — 세 판보다 적게 말하지 않는다"


def test_a_round_with_a_skipped_task_is_left_out_of_the_spread() -> None:
    runs = _rounds([4, 6, 5])
    runs.append(_run(4, list(kit.PRICE_TASKS)[0], ("온전", "온전", "온전")))   # 넷째 판은 과제 하나만 돌았다

    summary = kit.price_summary(runs)

    assert summary["per_round"] == [4, 6, 5], "과제가 빠진 판의 합은 다른 판과 견줄 수 없다"
    assert summary["incomplete_rounds"] == 1


def test_the_reasons_rows_fell_short_are_counted_in_the_kits_own_words() -> None:
    runs = [_run(1, "mouse", ("온전", "줄 없음", "값이 글에 없음")), _run(1, "buds", ("주소 틀림", "줄 없음", "온전"))]

    assert kit.price_summary(runs)["short_rows"] == {"줄 없음": 2, "값이 글에 없음": 1, "주소 틀림": 1}


def test_no_price_runs_give_an_empty_summary() -> None:
    assert kit.price_summary([]) == {}


def test_the_closing_lines_say_it_in_plain_words() -> None:
    lines = kit.summary_lines(kit.price_summary(_rounds([2, 7, 5, 4, 7, 3, 6, 3])))
    said = "\n".join(lines)

    assert "평균 4.6" in said and "1.9" in said
    assert "2줄" in said and "판" in said
    one = "\n".join(kit.summary_lines(kit.price_summary(_rounds([5]))))
    assert "3판" in one, "한 판만 쟀으면 흔들림을 모른다고 말한다"
