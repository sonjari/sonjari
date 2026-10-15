"""번호 목록·불릿으로 낸 답도 「화면에서 본 줄」로 센다 (2026-10-08 전수조사 3-2).

화면에서 본 줄을 표로 옮긴 답은 되받지 않게 했는데, 같은 것을 번호 목록으로 옮긴 답은 그대로 되받혔다.
최근 3주 개수 요구가 있던 판에서 번호 목록으로 답한 판은 45판 중 28판이, 표로 답한 판은 117판 중 22판이 되받혔다.
모델이 답을 어떤 모양으로 쓰는지에 판정이 흔들리면 안 된다.

표와 같은 규칙이다 — 값이 전부 도구가 돌려준 글의 **한 자리에 모여** 있어야 본 것이다. 설명 문장은 모델의 말이라 견주지 않는다.
"""
from __future__ import annotations

from typing import Any

from alture_jarvis.agent import (
    _list_items,
    _row_of_name_was_seen,
    _seen_text,
    list_items_seen_by_tools,
    rows_seen_by_tools,
    table_rows_seen_by_tools,
)

_SCREEN = (
    "트렌딩 모델 "
    "alpha-lab/Falcon-9B Text Generation • 9B • Updated 2 days ago • 12.4k • 310 "
    "beta-team/Heron-27B-GGUF Text Generation • 27B • Updated 5 days ago • 8,912 • 205 "
    "gamma/Wren-TTS Text-to-Speech • Updated 1 day ago • 4.1k • 98 "
    "하늘항공 06:00 07:15 할인석 편도 109,900원 "
    "바다항공 07:30 08:40 일반석 편도 121,000원 "
)


def _tool(text: str) -> list[dict[str, Any]]:
    return [{"role": "tool", "content": text}]


def test_names_copied_from_the_screen_as_a_numbered_list_are_seen() -> None:
    answer = "트렌딩 상위 3개입니다.\n\n1. **alpha-lab/Falcon-9B**\n2. **beta-team/Heron-27B-GGUF**\n3. **gamma/Wren-TTS**\n"
    assert table_rows_seen_by_tools(answer, _tool(_SCREEN)) == 0
    assert list_items_seen_by_tools(answer, _tool(_SCREEN)) == 3
    assert rows_seen_by_tools(answer, _tool(_SCREEN)) == 3


def test_a_name_that_was_never_on_the_screen_is_not_seen() -> None:
    answer = "1. **alpha-lab/Falcon-9B**\n2. **omega/Phantom-70B**\n3. **gamma/Wren-TTS**\n"
    assert list_items_seen_by_tools(answer, _tool(_SCREEN)) == 2


def test_a_number_made_up_beside_a_real_name_is_not_seen() -> None:
    """이름은 화면에 있고 숫자는 지어낸 항목 — 값이 하나라도 본 글에 없으면 세지 않는다."""
    answer = "1. **alpha-lab/Falcon-9B** — 좋아요 99.9k\n2. **beta-team/Heron-27B-GGUF** — 좋아요 8,912\n"
    assert list_items_seen_by_tools(answer, _tool(_SCREEN)) == 1


def test_values_on_labelled_lines_under_an_item_must_sit_together() -> None:
    answer = (
        "1. **하늘항공**\n   - 출발: 06:00\n   - 도착: 07:15\n   - 가격: 109,900원\n"
        "2. **바다항공**\n   - 출발: 07:30\n   - 도착: 08:40\n   - 가격: 109,900원\n"  # 가격을 윗줄에서 끌어왔다
    )
    far = _SCREEN + ("가" * 400) + " 109,900원"
    assert list_items_seen_by_tools(answer, _tool(_SCREEN)) == 1
    assert list_items_seen_by_tools(answer, _tool(far)) == 1


def test_the_models_own_description_is_not_held_against_the_item() -> None:
    answer = "- **gamma/Wren-TTS**: 가볍고 빠른 음성 합성 모델로, 한국어 발음이 자연스럽다고 합니다.\n- **alpha-lab/Falcon-9B**: 작은 카드에서 도는 범용 모델\n"
    assert list_items_seen_by_tools(answer, _tool(_SCREEN)) == 2


def test_a_very_short_name_alone_is_not_enough() -> None:
    answer = "1. **9B**\n2. **TTS**\n"
    assert list_items_seen_by_tools(answer, _tool(_SCREEN)) == 1  # 「TTS」는 세 글자라 센다 · 「9B」는 안 센다


def test_nothing_is_seen_when_no_tool_returned_anything() -> None:
    assert list_items_seen_by_tools("1. **alpha-lab/Falcon-9B**\n2. **gamma/Wren-TTS**\n", []) == 0


def test_plain_sentences_and_steps_are_not_items_from_the_screen() -> None:
    answer = "이렇게 하시면 됩니다.\n\n1. 먼저 설정을 엽니다\n2. 그다음 저장을 누릅니다\n"
    assert list_items_seen_by_tools(answer, _tool(_SCREEN)) == 0


def test_the_name_check_also_reads_list_items() -> None:
    answer = "1. **beta-team/Heron-27B-GGUF** — 좋아요 8,912\n2. **omega/Phantom-70B** — 좋아요 1,234\n"
    seen = _seen_text(_SCREEN)
    assert _row_of_name_was_seen(answer, "beta-team/Heron-27B-GGUF", seen)
    assert not _row_of_name_was_seen(answer, "omega/Phantom-70B", seen)


def test_the_name_check_does_not_take_a_bare_name_from_a_listing() -> None:
    """이름 하나뿐인 항목은 이름 경고에서 구제하지 않는다 — 「검색 목록에서 이름만 본 것은 읽은 것이 아니다」를 지킨다."""
    seen = _seen_text(_SCREEN)
    assert not _row_of_name_was_seen("1. **gamma/Wren-TTS**\n2. **alpha-lab/Falcon-9B**\n", "gamma/Wren-TTS", seen)


def test_items_are_split_at_the_next_marker_and_at_unindented_text() -> None:
    answer = "1. **하늘항공** 06:00\n   - 가격: 109,900원\n맺음말입니다 121,000원.\n2. **바다항공** 07:30\n"
    items = _list_items(answer)
    assert len(items) == 2
    assert "109,900원" in items[0] and not any("121,000" in value for value in items[0])
