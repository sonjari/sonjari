"""조사 판의 「파일을 만들 차례」는 **무언가 읽은 뒤에** 건다 (2026-10-12).

창 32K 의 9B 로 가격 조사를 돌린 판(eb13a02d): 검색 한 번 뒤 모델이 도구 없이 한마디 했고(작은 모델에 흔하다),
되받기가 한 번 나가자 그때부터 파일 쓰는 손만 받았다. 가게 페이지를 열려는 호출 둘이 `not_this_stage` 로 되돌아가
25초 · 3걸음 만에 「산출물 없음」으로 끝났다 — **읽은 것이 하나도 없는데 쓸 차례**였다. 같은 날 세 판이 모두 이 문에서 끝났다.

그 차례를 둔 까닭(2026-10-02 · 9d6942f2)은 「글 6개를 읽고도 더 열기만 하다 엑셀을 못 썼다」였다. 읽은 것이 있는 판의 일이다.
"""

from __future__ import annotations

from alture_jarvis.tool_roster import _artifact_turn_is_due


def test_a_research_job_that_has_read_nothing_is_not_told_to_write_yet() -> None:
    assert _artifact_turn_is_due(stage_says=True, deliver_turn=False, web_research=True, read_sources=0) is False


def test_once_something_was_read_the_turn_is_due_as_before() -> None:
    assert _artifact_turn_is_due(stage_says=True, deliver_turn=False, web_research=True, read_sources=1) is True
    assert _artifact_turn_is_due(stage_says=True, deliver_turn=False, web_research=True, read_sources=6) is True


def test_jobs_that_are_not_research_are_unchanged() -> None:
    # 「보고서 써 줘」처럼 읽을 것이 없는 일은 읽은 것이 0 이어도 쓸 차례다.
    assert _artifact_turn_is_due(stage_says=True, deliver_turn=False, web_research=False, read_sources=0) is True
    assert _artifact_turn_is_due(stage_says=False, deliver_turn=False, web_research=False, read_sources=0) is False


def test_the_turn_given_before_the_budget_runs_out_still_holds() -> None:
    # 걸음이 바닥나기 전에 주는 차례는 그대로다 — 읽은 것이 없어도 그 자리에서는 못 했다고 적어 내는 것이 맞다.
    assert _artifact_turn_is_due(stage_says=False, deliver_turn=True, web_research=True, read_sources=0) is True


def test_without_the_stage_or_the_last_turn_nothing_is_due() -> None:
    assert _artifact_turn_is_due(stage_says=False, deliver_turn=False, web_research=True, read_sources=9) is False
