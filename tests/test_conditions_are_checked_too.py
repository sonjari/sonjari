"""개수는 세는데 **무엇인지**는 아무도 안 봤다.

## 2026-08-16 실측 (사용자님이 실제로 쓰다가)

    "사람인에서 '연구비 관리'로 검색해서 **정규직** 공고 3개를 골라줘"

자비스가 가져온 셋 중 **둘이 계약직, 하나가 파견직**이었다. 그런데 계획 대조는
전부 통과했다 — **개수(3개)만 세고 조건은 안 봤기 때문이다.** 그리고 못 지켰다는
말도 안 했다. 조사는 잘하는데 시킨 조건을 지키는 것은 헐거웠다.

## 무엇을 판정하고 무엇을 판정하지 않나

★ "그 공고가 정말 정규직인가"는 **판정하지 않는다.** 그건 본문을 읽어야 알고,
읽었는지는 이미 다른 검사가 본다.

여기서 잡는 것은 더 싸고 더 확실한 것 — **답이 스스로 어긴 경우**다. 정규직을
시켰는데 답에 "계약직"이라고 적혀 있으면, 그건 자비스 자신이 아니라고 적어 놓은
것이다. 이 방향으로만 보면 **없는 위반을 만들어 내지 않는다.**

못 잡는 것(답에 고용형태를 아예 안 적은 경우)은 있다. 그건 이 검사의 한계로
받아들인다 — 오탐을 만드는 것보다 낫다([[gate-must-be-backtested]] 의 교훈).
"""

from __future__ import annotations

from alture_jarvis.plan import broken_condition_note, broken_conditions


def test_the_actual_case_from_that_day() -> None:
    """★ 그날 그 답을 글자 그대로 태운다."""
    prompt = "사람인에서 '연구비 관리'로 검색해서 정규직 공고 3개를 골라줘"
    answer = (
        "1. 코드나루(주) - 연구행정 및 정부과제 관리 담당자 ... 고용 형태: 계약직 (파견직 2년)\n"
        "2. 솔빛대학교 산학협력단 ... 고용 형태: 계약직 (기간제 2년)\n"
        "3. 푸른내일발전경영센터(주) ... 고용 형태: 정규직"
    )
    broken = broken_conditions(prompt, answer)
    assert ("정규직", "계약직") in broken
    assert ("정규직", "파견직") in broken

    note = broken_condition_note(prompt, answer)
    assert "시킨 조건과 다른 것이 섞여" in note
    assert "다시 찾아드릴까요" in note, "짚기만 하고 끝내면 사람이 또 시켜야 한다"


def test_a_clean_answer_says_nothing() -> None:
    """조건을 지킨 답에 경고가 붙으면 그 경고를 아무도 안 읽게 된다."""
    prompt = "정규직 공고 3개 알려줘"
    answer = "1. A사 정규직\n2. B사 정규직\n3. C사 정규직"
    assert broken_conditions(prompt, answer) == []
    assert broken_condition_note(prompt, answer) == ""


def test_a_condition_that_was_not_asked_is_not_judged() -> None:
    """시키지도 않은 조건으로 트집 잡으면 안 된다."""
    prompt = "사람인에서 연구비 관리 공고 3개 알려줘"
    answer = "1. A사 계약직\n2. B사 파견직\n3. C사 정규직"
    assert broken_conditions(prompt, answer) == []


def test_asking_for_contract_work_flags_the_opposite() -> None:
    """방향은 양쪽이다 — 계약직을 시켰는데 정규직을 가져와도 어긴 것이다."""
    assert ("계약직", "정규직") in broken_conditions("계약직으로 찾아줘", "A사 정규직 채용")


def test_each_conflict_is_named_once() -> None:
    """같은 말이 여러 번 나와도 한 번만 짚는다 — 길면 아무도 안 읽는다."""
    answer = "계약직 계약직 계약직 파견직"
    assert broken_conditions("정규직으로", answer) == [("정규직", "계약직"), ("정규직", "파견직")]


def test_an_empty_answer_is_left_alone() -> None:
    assert broken_conditions("정규직 3개", "") == []
    assert broken_conditions("", "계약직") == []
