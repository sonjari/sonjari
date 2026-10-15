"""「그 ○○」의 ○○ 가 바로 앞 판에 있으면 오랜 기억을 싣지 않는다 (2026-10-13).

네 번 이어 묻기(4B · 창 32K): 「○○의 홍보 전략을 조사해 줘」 다음에 「그 전략이 동네 작은 카페와는 어디가 다른지」라고 묻자, 도구
없이 답하는 길이 이 PC 의 오랜 기억에 있던 **다른 「전략」**으로 답했다(같은 조건 다섯 줄기 중 둘). 찾는 말이 요청 문장 하나뿐이라
낱말만 겹치는 옛 기억이 걸려 왔고, 작은 모델은 「관련된 기억」이라는 이름표가 붙은 쪽을 골랐다.

표본의 가게 · 기억은 지어낸 것이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.memory import ConversationMemory, points_at_previous_turn

PREVIOUS = "가상 카페 체인의 홍보 전략은 세 가지입니다. 첫째 리워드 프로그램, 둘째 시즌 한정 메뉴, 셋째 지역 행사입니다."


@pytest.mark.parametrize("ask, pointed", [
    ("그 전략이 동네 작은 카페의 홍보와는 구체적으로 어디가 다른지 알려줘", ["전략"]),
    ("그 리워드 프로그램을 자세히 알려줘", ["리워드"]),
    ("그래서 그 메뉴는 언제 나와", ["메뉴"]),
    ("그 행사에는 누가 와?", ["행사"]),
])
def test_a_noun_pointed_at_that_is_in_the_previous_turn(ask: str, pointed: list[str]) -> None:
    assert points_at_previous_turn(ask, PREVIOUS) == pointed


@pytest.mark.parametrize("ask", [
    "그 머라고하지 일단 다음으로 가자",          # 머뭇거리는 말
    "그 다음에 뭐 하면 되지",                    # 이음말
    "그 정도면 됐어",
    "그 회사 주가는 어때",                       # 앞 판에 없는 낱말
    "지난번에 말한 그 전략 기억나?",              # 옛일을 찾는 말 — 오랜 기억이 필요하다
    "예전에 정리한 그 전략은 어디까지 했지",
    "가상 카페 체인의 홍보 전략을 조사해 줘",      # 가리키는 말이 없다
    "",
])
def test_what_does_not_point_at_the_previous_turn(ask: str) -> None:
    assert points_at_previous_turn(ask, PREVIOUS) == []


def test_without_a_previous_turn_nothing_is_in_view() -> None:
    assert points_at_previous_turn("그 전략이 뭐였지", "") == []


def _memory(tmp_path: Path) -> ConversationMemory:
    return ConversationMemory(tmp_path / "memory.db")


def _old_memory_lines(messages: list[dict[str, str]]) -> list[str]:
    return [item["content"] for item in messages if item["role"] == "system" and ("과거 기억" in item["content"] or "이전에 배운 사실" in item["content"])]


def test_the_context_leaves_old_memory_out_when_the_thing_is_in_view(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    # 다른 대화에서 쌓인 오랜 기억 — 「전략」이라는 낱말만 겹친다.
    memory.add_message("old-room", "user", "우리 제품 전략 문서 어디까지 썼지")
    memory.add_message("old-room", "assistant", "제품 전략 문서는 3장까지 썼습니다. 가격 전략은 아직입니다.")
    # 지금 대화.
    memory.add_message("now", "user", "가상 카페 체인의 홍보 전략을 조사해 줘")
    memory.add_message("now", "assistant", PREVIOUS)

    pointed = memory.context_messages("now", query="그 전략이 동네 작은 카페의 홍보와는 어디가 다른지 알려줘")
    assert _old_memory_lines(pointed) == [], "가리킨 것이 바로 앞 답에 있다 — 창고를 뒤지지 않는다"
    assert any(PREVIOUS in item["content"] for item in pointed), "이 대화의 앞 답은 그대로 실린다"

    # 가리키는 말이 없는 새 질문에는 예전처럼 오랜 기억을 찾는다.
    fresh = memory.context_messages("now", query="제품 전략 문서 어디까지 썼지")
    assert _old_memory_lines(fresh), "예전 그대로 — 찾은 기억이 실린다"
    # 옛일을 찾는 말도 예전 그대로다.
    asked_old = memory.context_messages("now", query="지난번에 말한 그 전략 문서 기억나?")
    assert _old_memory_lines(asked_old)


def test_the_request_itself_already_in_the_record_is_not_the_previous_turn(tmp_path: Path) -> None:
    """이번 요청이 기록에 먼저 들어와 있어도, 자기 말에서 낱말을 찾아 걸리지 않는다."""
    memory = _memory(tmp_path)
    memory.add_message("old-room", "user", "새 회사 소개 자료 만들자")
    memory.add_message("old-room", "assistant", "회사 소개 자료 초안을 만들었습니다.")
    memory.add_message("now", "user", "가상 카페 체인의 홍보 전략을 조사해 줘")
    memory.add_message("now", "assistant", PREVIOUS)
    ask = "그 회사 소개 자료는 어디 있지"
    memory.add_message("now", "user", ask)        # 이번 요청이 이미 기록에 있다
    assert _old_memory_lines(memory.context_messages("now", query=ask)), "「회사」는 앞 답에 없다 — 오랜 기억을 찾아야 한다"
