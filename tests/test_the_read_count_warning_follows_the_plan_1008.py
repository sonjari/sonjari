"""읽은 개수 경고는 계획의 판정을 그대로 받는다 (2026-10-08 전수조사 4-6).

「N개 중 M개만 실제로 열어 읽었습니다」 경고가 요청을 **따로 다시 뽑고** 있었다. 본 계획과 인자가 달라 다른 요구가 나왔고,
화면의 대조표는 「✅ 3개 읽음」인데 그 아래에 「3개 중 2개만 읽었습니다」가 붙는 판이 생겼다.
최근 3주 이 경고가 붙은 23판 중 9판이 계획과 어긋났다(계획의 개수 칸은 충족 5 · 계획에 개수 칸이 없음 4).

판 끝에서는 계획이 **못 채웠다고 한 요구**만 본다. 계획 없이 부르는 옛 길(시험·다른 호출처)은 그대로다.
"""
from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.plan import Requirement

_FOUR = "두 곳에서 공고를 최소 4개는 직접 열어 읽고 예산·기간을 표로 정리해줘"


def _read(url: str) -> dict[str, Any]:
    return {"tool": "browser_extract", "ok": True, "error": "", "status": "", "arguments": {}, "evidence": {"url": url}}


_TWO_READ = [_read("https://jobs.example/project/1"), _read("https://jobs.example/project/2")]
_COUNT = Requirement("count", "4개 이상 직접 열어 읽기", 4, True)
_ARTIFACT = Requirement("artifact", "실제 산출물 파일 만들기", "")


def test_without_a_plan_it_still_reads_the_request_itself() -> None:
    assert "4개 중 2개" in BrowserAgent._goal_shortfall_check(_FOUR, _TWO_READ)


def test_a_count_the_plan_calls_unmet_is_still_said_out_loud() -> None:
    note = BrowserAgent._goal_shortfall_check(_FOUR, _TWO_READ, plan_results=[(_COUNT, False, "2개 읽음")])
    assert "4개 중 2개" in note


def test_a_count_the_plan_calls_met_draws_no_contradicting_note() -> None:
    assert BrowserAgent._goal_shortfall_check(_FOUR, _TWO_READ, plan_results=[(_COUNT, True, "4개 읽음 · 답에 4개")]) == ""


def test_a_plan_without_a_count_draws_no_count_note() -> None:
    assert BrowserAgent._goal_shortfall_check(_FOUR, _TWO_READ, plan_results=[(_ARTIFACT, False, "파일 0개")]) == ""
    assert BrowserAgent._goal_shortfall_check(_FOUR, _TWO_READ, plan_results=[]) == ""


def test_an_unmet_list_only_count_is_still_left_alone() -> None:
    listed = Requirement("count", "25개 목록으로 정리", 25, False, "", "", True)
    assert BrowserAgent._goal_shortfall_check(_FOUR, _TWO_READ, plan_results=[(listed, False, "답에 3개")]) == ""
