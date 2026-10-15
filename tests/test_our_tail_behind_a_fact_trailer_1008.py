"""우리 꼬리 뒤에 「만든 파일:」이 붙으면 꼬리가 모델에게 그대로 갔다 (2026-10-08 전수조사 3-3).

다음 판의 모델에게 보낼 때는 우리가 덧붙인 경고·대조표를 뗀다(10-05). 그런데 끝에서부터 떼는 그 함수는 맨 끝이
「만든 파일:」이나 「[이 목록의 주소]」면 첫 덩어리에서 멈췄다. 저장된 손자리 답 3,325개: 우리 꼬리가 붙은 622개 중
146개(23%)가 떼고도 남았고, 고친 뒤 6개다.

그 두 덩어리는 모델도 알아야 하는 사실(파일이 있다 · 그 줄의 주소)이라 남기고, 사이의 우리 꼬리만 뗀다.
"""
from __future__ import annotations

from alture_jarvis.memory import without_our_tail

_BODY = "표로 정리해 파일로 저장했습니다."
_WARNING = "⚠ **3개 중 2개만 실제로 열어 읽었습니다.** 나머지는 확인하지 못했으니, 부족하면 더 찾아보라고 말씀해 주세요."
_CHECKLIST = "**시킨 것 대조**\n- ❌ 3개 이상 직접 열어 읽기 — 2개 읽음\n- ✅ 실제 산출물 파일 만들기 — 파일 1개"
_FILES = "만든 파일:\n- `C:\\work\\out\\result.xlsx`"
_ADDRESSES = "[이 목록의 주소]\n다음에 「저거 해줘」라고 하실 때 이 주소로 집습니다.\n1. 첫째 — https://shop.example/1"


def test_the_tail_is_taken_off_even_behind_the_file_list() -> None:
    shown = "\n\n".join([_BODY, _WARNING, _CHECKLIST, _FILES])
    assert without_our_tail(shown) == "\n\n".join([_BODY, _FILES])


def test_the_tail_is_taken_off_behind_the_addresses_too() -> None:
    shown = "\n\n".join([_BODY, _CHECKLIST, _ADDRESSES])
    assert without_our_tail(shown) == "\n\n".join([_BODY, _ADDRESSES])


def test_both_fact_blocks_keep_their_order() -> None:
    shown = "\n\n".join([_BODY, _WARNING, _ADDRESSES, _FILES])
    assert without_our_tail(shown) == "\n\n".join([_BODY, _ADDRESSES, _FILES])


def test_an_answer_with_only_the_file_list_is_unchanged() -> None:
    shown = "\n\n".join([_BODY, _FILES])
    assert without_our_tail(shown) == shown


def test_a_warning_the_model_wrote_in_the_middle_still_stays() -> None:
    shown = "\n\n".join(["먼저 알려 드립니다.", "⚠ **주의**: 이 값은 추정입니다.", "그래서 표는 이렇게 됩니다.", _FILES])
    assert without_our_tail(shown) == shown


def test_an_answer_that_is_only_our_blocks_keeps_its_first_block() -> None:
    assert without_our_tail("\n\n".join([_WARNING, _FILES])) == "\n\n".join([_WARNING, _FILES])
