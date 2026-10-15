"""답에 적힌 **금액**이 실제로 읽은 글에 있는지 대조한다.

2026-08-12 실측. 자비스가 한길남해항만공사 공고를 열어 회사명·직무·마감일을
**정확히** 옮겼는데, 급여 칸에만 "평균 연봉 약 5,880만원 내외"가 들어 있었다.
그 공고에는 급여가 아예 없다(원문을 두 번 확인했다).

★ 이게 제일 위험한 종류다 — **나머지가 다 맞아서 이것도 맞아 보인다.** 그리고
프롬프트에 "공고에 없는 조건을 지어내지 마라"라고 적어 놨는데도 들어갔다.

여기서 지키는 것 넷:

  1. 읽은 글에 없는 금액은 답에 그대로 두되 **경고를 붙인다**
  2. 사용자가 말한 금액은 근거다 ("3만원 이하로 찾아줘")
  3. 표기가 갈려도 같은 값이면 통과시킨다 (5,880만원 ↔ 58800000원)
  4. 개수·비율은 안 본다. 잦은 경고는 안 읽히는 경고다
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent

_check = BrowserAgent._money_grounding_check


def _read(text: str) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": "여수 공고 찾아줘"},
        {"role": "tool", "tool_name": "browser_extract", "content": text},
    ]


def test_a_number_that_is_not_in_the_source_is_flagged() -> None:
    messages = _read('{"text": "한길남해항만공사 7급 사무 회계 14명 접수마감 2025년 9월 18일"}')

    note = _check("공고 찾아줘", "급여는 평균 연봉 약 5,880만원 내외입니다.", messages)

    assert "5,880만원" in note, "없는 금액인데 그냥 넘어갔다"
    assert "믿지 마시" in note


def test_a_number_that_is_in_the_source_is_left_alone() -> None:
    messages = _read('{"text": "로지텍 무선마우스 M170 12,340원 내일 도착"}')

    note = _check("마우스 찾아줘", "가격은 12,340원입니다.", messages)

    assert note == "", "읽은 글에 있는 금액인데 경고했다"


def test_the_users_own_number_counts_as_grounded() -> None:
    """사용자가 말한 값은 지어낸 게 아니다."""
    messages = _read('{"text": "상품 목록"}')

    note = _check("3만원 이하로 찾아줘", "예산 3만원 안에서 골랐습니다.", messages)

    assert note == ""


def test_the_same_amount_written_differently_passes() -> None:
    """원문이 원 단위로 적어도 답이 만원으로 적으면 같은 값이다."""
    messages = _read('{"text": "연봉 58800000원"}')

    note = _check("연봉 알려줘", "연봉은 5,880만원입니다.", messages)

    assert note == "", "표기만 다른 같은 값을 지어낸 것으로 몰았다"


def test_counts_and_small_numbers_are_not_checked() -> None:
    """개수까지 보면 경고가 잦아지고, 잦은 경고는 안 읽힌다."""
    messages = _read('{"text": "공고 목록"}')

    note = _check("찾아줘", "공고 4개를 확인했고 그중 2개가 맞습니다. 10원도 안 듭니다.", messages)

    assert note == ""


def test_only_tool_results_count_as_having_been_read() -> None:
    """모델이 스스로 한 말은 근거가 아니다 — 그게 바로 지어낸 자리다."""
    messages = [
        {"role": "assistant", "content": "제가 알기로 평균 연봉은 5,880만원입니다."},
        {"role": "tool", "tool_name": "browser_extract", "content": '{"text": "급여 정보 없음"}'},
    ]

    note = _check("공고 찾아줘", "평균 연봉 5,880만원", messages)

    assert "5,880만원" in note
