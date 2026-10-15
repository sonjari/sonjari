"""화면에서 해 달라는 말은 손이 있는 길로 · 사람이 대화에서 준 숫자는 근거다 (2026-10-07 대표 실사용).

1. 「…로그인창까지 들어가줄 수 있나」를 모델 라우터가 대화로 보냈고, 도구 없는 그 갈래는 도구 0번으로 「로그인 페이지가
   열렸습니다」라고 답했다(두 판). 화면에서 하는 일은 머릿속에서 할 수 없다.
2. 사람이 자기 이력서를 붙여넣고 자기소개서를 같이 고치던 판마다 「읽은 자료에 없는 금액: …」이 붙었다.
   그 숫자는 사람이 이 대화에서 준 것이다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import BrowserAgent, said_by_the_person
from alture_jarvis.runtime import _asks_to_act_on_screen


@pytest.mark.parametrize("prompt", [
    "그러면 그 서점 로그인 화면까지 들어가줄수있나",
    "아니 로그인은 내가 할 테니 로그인 화면으로가줘",
    "보내지는 말고 우선 칸에 채워만줘",
    "그래 들어가자",
    "음 그러면 관리 화면으로 가줄수는있나",
    "그러면 그 사이트 MY페이지까지 들어가줄 수 있나",
    "거기 임시저장 단추 눌러줘",
])
def test_asking_to_do_it_on_the_screen_goes_to_the_hands(prompt: str) -> None:
    assert _asks_to_act_on_screen(prompt) is True


@pytest.mark.parametrize("prompt", [
    "집고양이가 숲에 들어가면 어떻게 되는 거야",                # 조건 — 해 달라는 말이 아니다
    "그 폴더 들어가면 보일 건데",
    "네가 서버를 열어줄 수 있다 아이가 그게 요점이거든",         # 진술
    "오늘 기분 어때",
    "자기소개서 문장을 매끄럽게 이어줘",                       # 글 고치기 — 화면 일이 아니다
])
def test_talk_that_only_mentions_those_verbs_stays_a_conversation(prompt: str) -> None:
    assert _asks_to_act_on_screen(prompt) is False


def test_a_long_pasted_text_is_not_judged_by_one_verb_inside_it() -> None:
    assert _asks_to_act_on_screen("지난 회의록입니다. " + "담당자가 창고에 들어가라 했고 그대로 진행했습니다. " * 30) is False


GIVEN = "제 경력입니다. 30억 원 규모 공사의 자재를 맡았고, 1,450만 원어치 중복 발주를 납품 전에 찾아 바로잡았습니다."


def _conversation() -> list[dict]:
    return [
        {"role": "system", "content": "…"},
        {"role": "user", "content": GIVEN},
        {"role": "assistant", "content": "잘 읽었습니다."},
        {"role": "user", "content": "[시스템] 계획에 남은 것: 5,880만원 급여 칸을 확인하라"},
        {"role": "user", "content": "이걸로 자기소개서 지원동기를 써줘"},
    ]


def test_what_the_person_gave_excludes_our_own_notes() -> None:
    said = said_by_the_person(_conversation())

    assert "1,450만 원" in said and "자기소개서" in said
    assert "5,880만원" not in said, "우리가 끼워 넣은 말의 숫자는 근거가 아니다"


def test_money_the_person_gave_earlier_is_not_flagged() -> None:
    answer = "저는 30억 원 규모 공사의 자재를 맡았고 1,450만 원 중복 발주를 사전에 바로잡았습니다."

    assert BrowserAgent._money_grounding_check("이걸로 자기소개서 지원동기를 써줘", answer, _conversation()) == ""


def test_money_nobody_gave_is_still_flagged() -> None:
    answer = "저는 30억 원 규모 공사를 맡았고, 귀사의 평균 연봉은 6,400만 원으로 알고 있습니다."

    warning = BrowserAgent._money_grounding_check("이걸로 자기소개서 지원동기를 써줘", answer, _conversation())

    assert "6,400만" in warning
    assert "30억" not in warning
