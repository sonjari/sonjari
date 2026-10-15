"""우리가 가진 데이터를 자비스가 볼 수 있는가.

2026-08-13 인수인계 4-1. `nas_server/app/high_thinking_tools.py` 에 입시·진로
조회 도구가 20 여 개 등록돼 있는데 **자비스 도구 목록에는 0 건**이었다. 그래서
입시 질문을 받으면 자비스가 고를 수 있는 길이 둘뿐이었다 — 기억에서 답하거나
(창작), 웹을 뒤지거나(느리고 부정확). 우리가 직접 쌓은 76k 실컷을 두고.

여기서 지키는 것 셋:

  1. **라우팅** — 학교·학과를 대고 우리가 가진 종류의 값을 물으면 에이전트로 간다.
     옛 갈래(웹 조사·출처 지목)는 이걸 못 잡는다. "~에서"가 없고 "찾아봐"도 없다.
  2. **도구가 없으면 갈래도 없다** — 갈래만 만들고 도구를 안 주면 에이전트가
     조회 없이 입시 질문을 받아 결국 웹을 뒤진다. 오늘 고친 병 ⑩ 과 같은 모양이다.
  3. **프롬프트에 이름이 실린다** — 도구를 만들어도 순서에 없으면 안 불린다
     (`test_tools_are_in_the_prompt.py` 와 같은 규율). 다만 그 문단은 실제 도구
     목록에서 만들어지므로, NAS 화이트리스트가 바뀌면 문단도 같이 바뀐다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import (
    NAMED_SOURCE_MAX_CHARS,
    asks_inhouse_data,
    inhouse_prompt_section,
)
from alture_jarvis.runtime import JarvisRuntime


# 우리 DB 가 원천인 질문들. 웹에도 비슷한 숫자가 굴러다니지만 그건 남의 작년 카더라다.
OURS_TO_ANSWER = [
    "중앙대 소프트웨어학부 작년 경쟁률 알려줘",
    "경희대학교 컴퓨터공학과 합격선이 어떻게 돼?",
    "내신 2.3인데 어느 대학 갈 수 있어?",
    "부산대 정보컴퓨터공학부 합격 확률 얼마나 될까",
    "간호학과 취업률 어때?",
    "기계공학과 나오면 연봉 어느 정도야",
    "수시 학생부종합으로 지원 가능한 곳 추천해줘",
    "이 학과 중도 탈락률이 높다던데 정말이야",
]


@pytest.mark.parametrize("prompt", OURS_TO_ANSWER)
def test_questions_about_our_own_data_go_to_the_tools(prompt: str) -> None:
    assert asks_inhouse_data(prompt), prompt


@pytest.mark.parametrize("prompt", OURS_TO_ANSWER)
def test_the_older_branches_never_caught_them(prompt: str) -> None:
    """왜 갈래가 하나 더 필요한지를 시험이 직접 보여 준다.

    이 단정이 깨지는 날은 좋은 날이다(옛 갈래가 넓어졌다는 뜻). 그때는 이 시험을
    지우면 되고, 다만 **왜 지우는지 알고** 지우게 된다.
    """
    assert not JarvisRuntime._requires_web_research(prompt), prompt
    assert not JarvisRuntime._requires_named_source(prompt), prompt


# 학교 이야기가 나와도 우리 DB 가 답할 것이 아닌 말들.
NOT_OURS = [
    "고려대 나온 친구가 그러는데 요즘 취업이 어렵대",
    "대학교 앞에 맛집 좀 알려줘",
    "연봉 협상 어떻게 하는 게 좋을까",
    "수능 날 도시락 뭐 싸가지",
    "내일 학부모 상담 일정 잡아줘",
]


@pytest.mark.parametrize("prompt", NOT_OURS)
def test_ordinary_talk_does_not_go_looking_up_cutoffs(prompt: str) -> None:
    assert not asks_inhouse_data(prompt), prompt


def test_a_pasted_record_is_out_of_scope() -> None:
    """붙여넣은 생기부에는 이 낱말이 전부 들어 있다.

    `named_sources` 가 이미 같은 이유로 길이 제한을 갖고 있다.
    """
    pasted = "3학년 1학기 세부능력 및 특기사항: 수학 교과 전형 관련 탐구 활동. " * 12
    pasted += "경쟁률"
    assert len(pasted) > NAMED_SOURCE_MAX_CHARS
    assert not asks_inhouse_data(pasted)


def test_both_signals_are_required() -> None:
    """대상만·값만으로는 안 걸린다. 한쪽만 보면 잡담이 통째로 걸려 온다."""
    assert not asks_inhouse_data("중앙대 소프트웨어학부 어때?")  # 대상만
    assert not asks_inhouse_data("경쟁률이 뭐야?")  # 값만
    assert asks_inhouse_data("중앙대 소프트웨어학부 경쟁률 어때?")


# ── 도구가 없으면 갈래도 없다 ────────────────────────────────────────────────


class _NoTools:
    names: set[str] = set()


class _SomeTools:
    names = {"admission_quant_lookup"}


def test_the_branch_stays_shut_when_no_tool_is_attached() -> None:
    """NAS 가 안 뜨거나 키가 없으면 조회 도구가 0 개다.

    그 상태로 이 갈래를 열면 에이전트는 **못 하는 일**을 받는다 — 조회 없이 입시
    질문을 쥐고 결국 웹을 뒤지거나 지어낸다. 갈래만 만들고 도구를 안 준 것이
    오늘 고친 병(⑩ select_option·undo_action)과 같은 모양이다.
    """
    runtime = object.__new__(JarvisRuntime)
    runtime.inhouse = _NoTools()
    assert not runtime._requires_inhouse_data("중앙대 소프트웨어학부 경쟁률 알려줘")

    runtime.inhouse = _SomeTools()
    assert runtime._requires_inhouse_data("중앙대 소프트웨어학부 경쟁률 알려줘")


# ── 순서에 이름이 없으면 안 불린다 ───────────────────────────────────────────


def test_attached_tools_are_named_in_the_procedure() -> None:
    section = inhouse_prompt_section({"admission_quant_lookup", "career_strategy_lookup"})
    assert "admission_quant_lookup" in section
    assert "career_strategy_lookup" in section
    # 안 붙은 도구는 안 실린다 — 없는 도구를 시키면 걸음만 버린다.
    assert "admission_probability_simulate" not in section


def test_no_tools_means_no_paragraph() -> None:
    """도구가 없는데 '우리 데이터로 답하라'고 적어 두면 그게 곧 창작 지시다."""
    assert inhouse_prompt_section(set()) == ""
    assert inhouse_prompt_section({"browser_open"}) == ""
