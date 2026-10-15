"""사람 수는 개수 요구가 아니고, 소감 한마디는 앞 요청을 물려받지 않는다 (2026-10-08).

실사용 한 판에서 둘이 겹쳐 났다.

1. 숙소를 알아봐 달라는 요청의 「인원은 2명이고 예약은 하지 말고」가 「2개 실제로 처리하기」가 됐다 — `2명` 이 개수로,
   바로 뒤의 「예약」이 행위로 읽혔다(하지 말라는 말은 안 봤다). 값이 전부 맞는 답 끝에 「2개를 처리하라고 하셨는데
   하나도 안 했습니다」가 붙고 판은 부분 완료로 끝났다.
2. 그 뒤의 감탄 한마디가 「…왜 이렇게 좋아 …」의 `좋아` 때문에 「이어지는 지시」로 판정돼 앞 요청이 통째로 붙었다.
   모델은 「볼 것이 없다」고 판단했는데 하네스가 두 번 되받아 상세 둘을 다시 열었다.

여기 문장은 전부 지어낸 것이다(실제 요청을 옮기지 않는다).
"""

from __future__ import annotations

import pytest

from alture_jarvis import plan
from alture_jarvis.quantities import ROLE_CONSTRAINT, ROLE_UNKNOWN, quantity_role


def kinds(prompt: str, **kwargs: bool) -> list[str]:
    return [requirement.kind for requirement in plan.extract(prompt, **kwargs)]


@pytest.mark.parametrize(
    "prompt",
    [
        "숙소 예약 사이트에서 부산 숙소 알아봐줘 인원은 2명이고 예약은 하지 말고 알아보기만 해줘",
        "이번 주말 1박으로 성인 2명 기준 제주 숙소를 찾아줘",
        "어른 2명 아이 3명이 묵을 방을 알아봐줘",
        "3명이서 갈 만한 식당을 찾아줘",
    ],
)
def test_a_party_size_is_not_a_count(prompt: str) -> None:
    for observe in (False, True):
        found = kinds(prompt, has_named_source=True, must_observe=observe)
        assert "count_action" not in found
        assert "count" not in found


def test_the_role_lives_in_one_place() -> None:
    assert quantity_role("명", "인원", "이고 예약") == ROLE_CONSTRAINT
    assert quantity_role("명", "성인", " 기준") == ROLE_CONSTRAINT
    assert quantity_role("명", "", "이서 갈") == ROLE_CONSTRAINT
    # 찾을 사람을 세는 말은 그대로다.
    assert quantity_role("명", "개발자", "을 찾아") == ROLE_UNKNOWN


def test_people_to_find_are_still_counted() -> None:
    assert plan._count_target("채용 사이트에서 백엔드 개발자 3명을 찾아줘") == 3


def test_a_forbidden_action_does_not_make_the_count_an_action() -> None:
    assert not plan._is_action_count("글 3개만 알려줘 저장은 하지 말고", 3)
    assert not plan._is_action_count("글 3개만 골라줘 등록은 빼고", 3)


@pytest.mark.parametrize(
    "prompt",
    [
        "게시판에서 최근 글 5개마다 제목·올린 날짜·조회수를 읽어서 알려줘",
        "모집 공고 3건의 신청 기간과 지원 자격을 읽어줘",
        "책 4권의 등록일과 작성자를 알려줘",
    ],
)
def test_a_field_name_is_not_an_action(prompt: str) -> None:
    """「올린 날짜」·「신청 기간」·「등록일」은 읽을 칸의 이름이다 — 운영에서 읽기만 하는 요청이 「5개 실제로 처리하기」가 됐다."""
    assert not plan._is_action_count(prompt, plan._count_target(prompt))


def test_an_asked_action_is_still_an_action_count() -> None:
    assert plan._is_action_count("이 순위대로 5개 스크랩해줘", 5)
    assert plan._is_action_count("이 순위대로 4개 저장해줘 발행은 하지 말고", 4)
    # 뒤 문장의 금지가 앞의 시킨 행위까지 죽이지 않는다.
    assert plan._is_action_count("5개 예약해줘 취소는 말고", 5)


@pytest.mark.parametrize(
    "remark",
    [
        "와 너 왜 이렇게 좋아 진짜 놀랍다 제일 어려운 건데",
        "근데 그래 보이긴 하네 신기하다",
        "그 말이 맞아 보이는데 나는 잘 모르겠다",
        "그래 너도 수고했다 오늘 시험하느라 연산을 많이 썼을 텐데 고생했다",
    ],
)
def test_a_remark_is_not_a_continuation(remark: str) -> None:
    assert not plan.is_continuation(remark)


@pytest.mark.parametrize(
    "follow_up",
    ["응", "좋아", "그래 그걸로", "좋아 그렇게 진행해줘", "맞아 그 순서로 정리해서 표로 만들어줘", "제안한 대로 전부 다 진행해줘", "이어서 해"],
)
def test_a_go_ahead_is_still_a_continuation(follow_up: str) -> None:
    assert plan.is_continuation(follow_up)


def test_a_page_read_under_a_longer_address_was_read() -> None:
    """연 주소에 사이트가 매개변수를 덧붙여도 「열어 놓고 안 읽은 곳」이 아니다 — 눈금이 읽은 여섯을 안 읽은 여섯으로 셌다."""
    from alture_jarvis import evidence

    opened = "https://stay.example/room/31?adults=2&checkin=2030-01-02"
    records = [
        {"ok": True, "type": evidence.TYPE_PAGE_OPEN, "candidate": True, "source_id": opened},
        {"ok": True, "type": evidence.TYPE_BODY_READ, "source_id": opened + "&category=STAY"},
        {"ok": True, "type": evidence.TYPE_PAGE_OPEN, "candidate": True, "source_id": "https://stay.example/room/44?adults=2"},
        # 매개변수 값이 다르면 다른 곳이다(질의가 신원인 검색 주소).
        {"ok": True, "type": evidence.TYPE_PAGE_OPEN, "candidate": True, "source_id": "https://stay.example/search?q=busan"},
        {"ok": True, "type": evidence.TYPE_BODY_READ, "source_id": "https://stay.example/search?q=jeju"},
    ]
    summary = evidence.summarize(records, read_only=True)
    assert summary["opened_never_read"] == ["https://stay.example/room/44?adults=2", "https://stay.example/search?q=busan"]


def test_a_remark_does_not_inherit_the_previous_request() -> None:
    history = [{"role": "user", "content": "중고 서점 사이트에서 파이썬 책 3권의 쪽수를 직접 열어 읽고 알려줘"}]
    remark = "와 너 왜 이렇게 좋아 진짜 놀랍다 제일 어려운 건데"
    assert plan.planning_prompt(remark, history) == remark
    # 진짜 이어짓기는 여전히 앞 요청을 물려받는다.
    go_ahead = "좋아 그렇게 진행해줘"
    assert plan.planning_prompt(go_ahead, history).startswith(history[0]["content"])
