"""「세는 일」이 딴 데로 새지 않는가.

## 2026-08-22 실측

    시킨 것: 검색어 5개로 크몽을 검색하고 **건수를 표로** 적어라. 상세는 필요 없다.
    한 것  : 검색 5번 정확히 수행 ✓  →  상세 3건을 열어 읽고 그 요약을 답으로 냄

답 끝에 흔적이 그대로 남았다:

    "이제 목표한 3개 읽기를 완료했습니다. 남은 자료는 더 이상 읽지 않고…"

자비스가 사용자 지시가 아니라 **`_forced_read_call` 의 목표**를 따랐다. 그 장치는
「목록만 보고 답」을 막으려고 만든 것인데, **목록 자체가 답인 요청**에서는 반대로
일을 가로챈다.

## 그리고 더 나쁜 것

`browser_site_search` 의 `result_count` 가 15·15·11·2·15 로 **도구 결과에 멀쩡히
있었는데** 답에는 한 줄도 안 들어갔다. 사람이 DB 를 열어야 알 수 있었다.
**자료가 왔는데 답이 못 담으면 그건 답이 아니다.**
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.plan import wants_a_count


@pytest.mark.parametrize(
    "prompt",
    [
        "검색어별로 건수를 표로 적어줘",
        "크몽에 학원 관련 서비스 몇 개나 있는지 세줘",
        "경쟁사 목록으로 정리해줘",
        "가격 분포 알려줘",
        "관련 서비스 몇 건이나 나오는지 나열해줘",
    ],
)
def test_counting_requests_are_recognised(prompt: str) -> None:
    assert wants_a_count(prompt) is True, prompt


@pytest.mark.parametrize(
    "prompt",
    [
        # 본문을 보라고 했다 — 이때는 강제 읽기가 맞다.
        "공고 3개 열어서 본문 읽어줘",
        "상위 5개 상세 내용 확인해줘",
        "15건 중 3개는 자세히 읽어줘",
        # 세는 일이 아니다.
        "크몽에서 가격 전략 짜줘",
        "지금 몇 시야",
    ],
)
def test_reading_requests_are_not_counting(prompt: str) -> None:
    """★ 「본문을 읽어라」가 있으면 세는 일이 아니다.

    "15건 중 3개는 내용도 봐줘" 는 세고 **읽는** 일이고, 그때는 강제 읽기가 맞다.
    """
    assert wants_a_count(prompt) is False, prompt


def _step(query: str, count: int) -> dict:
    return {
        "tool": "browser_site_search",
        "evidence": {"action": "site_searched", "query": query, "result_count": count},
    }


def test_counts_are_appended_when_the_answer_forgot_them() -> None:
    """★ 이 파일에서 가장 중요한 검사.

    도구가 이미 돌려준 값을 **옮겨 적는 것**이라 지어낼 자리가 없다.
    """
    steps = [_step("학원 자동화", 15), _step("원생 관리", 11)]

    note = BrowserAgent._search_counts_note("건수를 표로 적어줘", steps, "이것저것 알아봤습니다.")

    assert "학원 자동화" in note and "15" in note
    assert "원생 관리" in note and "11" in note


def test_nothing_is_appended_when_the_answer_already_said_it() -> None:
    """같은 말을 두 번 하면 읽는 사람이 어느 쪽이 진짜인지 헷갈린다."""
    steps = [_step("학원 자동화", 15)]
    answer = "학원 자동화 검색 결과는 15건이었습니다."

    assert BrowserAgent._search_counts_note("건수를 세줘", steps, answer) == ""


def test_nothing_is_appended_for_non_counting_requests() -> None:
    steps = [_step("학원 자동화", 15)]

    assert BrowserAgent._search_counts_note("가격 전략 짜줘", steps, "전략입니다") == ""


def test_nothing_is_appended_when_no_search_happened() -> None:
    assert BrowserAgent._search_counts_note("건수를 세줘", [], "답") == ""


@pytest.mark.parametrize(
    "prompt",
    [
        # ★ 2026-08-22 2차. "제목만 적어줘"가 안 걸려서 또 상세 5개를 읽었다.
        "상위 5개 제목만 적어줘",
        "가격만 알려줘",
        "링크만 뽑아줘",
        # "몇 번"도 세는 말이다.
        "로보메타핏이 몇 번 나왔는지 알려줘",
    ],
)
def test_only_this_much_is_also_counting(prompt: str) -> None:
    """「무엇**만**」은 그것 말고는 보지 말라는 뜻이다 — 세는 일과 같은 성질이다."""
    assert wants_a_count(prompt) is True, prompt
