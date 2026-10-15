"""원 금액을 만원·억원으로 바꿔 쓴 것은 근거 없는 숫자가 아니다 (2026-10-02 K-Startup 3차 판).

원문 「총 교육비: 12,016,000원 · 자부담: 400,000원」을 답이 「총 교육비 1,201만원·자부담 40만원」으로 적었는데
숫자 검사가 1201·40 을 「도구가 준 적 없는 숫자」로 찍었다. 단위만 바꾼 것이다. 거꾸로 지어낸 금액은 그대로 잡혀야 한다.
"""

from __future__ import annotations

from alture_jarvis.evidence import numbers_claimed_in, numbers_in_body, unsupported_numbers

KSTARTUP_PAGE = "▸ 교육비 - 총 교육비: 12,016,000원 - 국비 지원(97%): 11,616,000원 - 자부담: 400,000원"


def _left(answer: str, page: str) -> set[str]:
    return unsupported_numbers(numbers_claimed_in(answer), numbers_in_body({"text": page}))


def test_won_rewritten_as_man_won_is_grounded() -> None:
    assert _left("지원금 없음 (총 교육비 1,201만원·자부담 40만원)", KSTARTUP_PAGE) == set()


def test_rounding_up_to_man_won_is_also_grounded() -> None:
    assert _left("총 교육비 약 1,202만원", KSTARTUP_PAGE) == set()


def test_man_won_on_the_page_read_back_in_won() -> None:
    assert _left("사업화 자금 50,000,000원", "최대 5,000만원 지원") == set()
    assert _left("총 120,000,000원", "1억 2,000만원 한도") == set()


def test_eok_both_ways() -> None:
    assert _left("최대 1.5억", "지원 한도 150,000,000원") == set()
    assert _left("300,000,000원", "최대 3억원") == set()


def test_an_invented_amount_is_still_caught() -> None:
    assert _left("총 교육비 1,350만원", KSTARTUP_PAGE) == {"1350"}


def test_big_numbers_without_a_won_mark_are_not_shrunk() -> None:
    # 조회수·ISBN 같은 표지 없는 큰 수를 만 단위로 줄여 읽으면 작은 숫자가 근거로 쏟아진다.
    assert "1201" not in numbers_in_body({"text": "조회수 12,016,000회"})
    assert _left("응답자 1,201명", "조회수 12,016,000회") == {"1201"}


def test_man_keum_is_not_a_unit() -> None:
    assert "20000" not in numbers_in_body({"text": "2만큼 늘었다"})
