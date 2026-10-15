"""개수 요구를 **일한 방식이 아니라 낸 결과**로 채점한다.

## 두 병 사이에 끼어 있던 자리다

    2026-08-13   개수 요구가 없어서 **너무 일찍 멈췄다**
                 크몽 2걸음 · 쿠팡 3걸음 · 교보문고 4걸음 — 3개 시키고 1개 받음
    2026-08-23   개수 요구를 「연 페이지 수」로 재서 **목록에 답이 있는 판이 미달**
                 무신사 "상위 3개의 제품명과 가격"
                     퀀3.8   시킨 대로 상세를 셋 열다 30걸음·401초·충족 0/1
                     젬마4   목록에서 뽑아 9걸음·124초·정답 3개

**시킨 대로 한 쪽이 지는 구조였다.** 시킨 것은 "3개를 알려 달라"였지
"3개를 열어 보라"가 아니었는데, 재는 자가 일한 방식을 채점하고 있었다.

한쪽을 지우면 다른 쪽 병이 돌아온다(오늘 실제로 지웠다가 검사 9개가 걸려 되돌렸다).
그래서 **두 길 중 하나면 충족**으로 바꿨다 — 충분히 읽었거나, 답이 N개를 담았거나.
"""

from __future__ import annotations

from alture_jarvis.plan import Requirement, all_met, check, count_listed_items

_THREE = [Requirement("count", "3개 이상 직접 열어 읽기", 3)]


def test_the_musinsa_case_now_passes() -> None:
    """★ 목록에서 뽑아 정답 셋을 냈으면 충족이다 — 상세를 안 열었어도."""
    answer = (
        "1. **RUNNING TEE (U26BTTS604)**: 9,990원\n"
        "2. **컬러 레이어드 롤업 티셔츠 [차콜]**: 29,900원\n"
        "3. **90s 빈티지핏 워시드 티셔츠 [코발트]**: 25,900원"
    )
    results = check(_THREE, sources=["https://www.musinsa.com/search"], steps=[], answer=answer)

    assert all_met(results), "정답 셋을 냈는데 미달로 찍힌다"
    assert "답에 3개" in results[0][2]


def test_the_2026_08_13_case_still_fails() -> None:
    """★ 3개 시켰는데 1개만 낸 판은 여전히 미달이어야 한다.

    이걸 놓치면 "일찍 멈추는" 옛 병이 돌아온다.
    """
    answer = "1. 첫 번째 공고만 찾았습니다."
    results = check(_THREE, sources=["https://kmong.com/gig/1"], steps=[], answer=answer)

    assert not all_met(results)


def test_reading_enough_still_satisfies_without_a_list() -> None:
    """줄글로 답해도 **충분히 읽었으면** 충족이다 — 예전 길을 안 막는다."""
    results = check(
        _THREE,
        sources=["https://a.com/1", "https://a.com/2", "https://a.com/3"],
        steps=[],
        answer="세 곳을 읽고 정리하면 이렇습니다. 전반적으로 …",
    )

    assert all_met(results)


def test_no_answer_falls_back_to_the_old_rule() -> None:
    """판이 도는 중(답 전)에는 예전처럼 읽은 수로만 본다."""
    assert not all_met(check(_THREE, sources=["https://a.com/1"], steps=[]))
    assert all_met(check(_THREE, sources=["https://a.com/1", "https://a.com/2",
                                          "https://a.com/3"], steps=[]))


def test_the_saw_line_shows_both_numbers() -> None:
    """사람이 읽을 줄에 **둘 다** 적는다 — 왜 통과했는지 보여야 한다."""
    answer = "- 가\n- 나\n- 다"
    saw = check(_THREE, sources=["https://a.com/1"], steps=[], answer=answer)[0][2]

    assert "1개 읽음" in saw and "답에 3개" in saw


class TestCountingItself:
    """세는 자가 틀리면 전부 틀린다."""

    def test_numbered(self) -> None:
        assert count_listed_items("1. 가\n2. 나\n3. 다") == 3

    def test_bullets(self) -> None:
        assert count_listed_items("- 가\n- 나\n* 다\n• 라") == 4

    def test_bold_numbers(self) -> None:
        assert count_listed_items("**1.** 가\n**2.** 나") == 2

    def test_table_excludes_header_and_rule(self) -> None:
        table = "| 이름 | 값 |\n| --- | --- |\n| 가 | 1 |\n| 나 | 2 |"
        assert count_listed_items(table) == 2

    def test_prose_counts_nothing(self) -> None:
        assert count_listed_items("줄글입니다. 항목이 없습니다.") == 0

    def test_empty(self) -> None:
        assert count_listed_items("") == 0

    def test_a_stray_dash_in_prose_is_not_an_item(self) -> None:
        """줄 **머리**의 불릿만 센다 — 문장 속 하이픈은 항목이 아니다."""
        assert count_listed_items("가격은 9,990원 - 29,900원 사이입니다.") == 0
