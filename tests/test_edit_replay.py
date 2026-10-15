"""바뀐 자리를 되짚어 보여 줄 재료 — **되짚기지 생중계가 아니다.**

사용자님 제안(2026-08-28): "쓰는 건 토큰이 있으니 커서처럼 보여줄 수 있지 않나."
확인해 보니 아니었다 — Ollama 는 tool_calls 를 통째로 한 번에 준다. 파일 내용은
도구 **인자** 안에 있어서 토큰으로 흘러오지 않는다. 그러니 커서를 붙이면 실제로
안 일어나는 일을 일어나는 척하는 연출이 된다.

그래서 흘러오는 척하지 않고 **끝난 뒤 무엇이 바뀌었는지** 되짚는다. 그러려면 화면이
바뀐 자리를 알아야 하는데, 지금까지 결과에는 바이트 수와 해시뿐이었다 — 사람이
볼 것이 하나도 없는 증거였다.
"""

from __future__ import annotations

from alture_jarvis.local_computer import EDIT_PREVIEW_LINES, _edit_preview

_BEFORE = "def a():\n    return 1\n\ndef b():\n    return 2\n"


def test_it_says_where_in_the_file_the_change_landed() -> None:
    """줄 번호가 없으면 되짚기는 그냥 코드 조각 두 개다."""
    preview = _edit_preview(_BEFORE, "    return 1", "    value = 1\n    return value")
    assert preview["start_line"] == 2


def test_it_carries_both_sides_of_the_change() -> None:
    preview = _edit_preview(_BEFORE, "    return 1", "    value = 1\n    return value")
    assert preview["removed"] == ["    return 1"]
    assert preview["added"] == ["    value = 1", "    return value"]
    assert preview["truncated"] is False


def test_a_big_edit_is_clipped_and_says_so() -> None:
    """되짚기가 전부를 보여 준 척하면 안 된다 — 잘렸으면 잘렸다고 한다."""
    big = "\n".join(f"line {n}" for n in range(EDIT_PREVIEW_LINES + 25))
    preview = _edit_preview("x", "x", big)
    assert len(preview["added"]) == EDIT_PREVIEW_LINES
    assert preview["truncated"] is True
    assert preview["added_count"] == EDIT_PREVIEW_LINES + 25


def test_a_change_at_the_top_is_line_one() -> None:
    preview = _edit_preview(_BEFORE, "def a():", "def a(x):")
    assert preview["start_line"] == 1


def test_text_that_is_not_there_does_not_crash_the_preview() -> None:
    """실제로는 apply_edit 이 먼저 막지만, 되짚기가 예외로 잡을 자리는 아니다."""
    preview = _edit_preview(_BEFORE, "없는 글", "새 글")
    assert preview["start_line"] == 1
