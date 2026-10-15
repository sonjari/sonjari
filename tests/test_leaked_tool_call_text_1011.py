"""답 글에 **도구를 부르는 글**이 그대로 새어 나오면 걷어 낸다 (2026-10-11).

16GB 조건(작은 27B 판)으로 가격 조사를 돌린 판(46f45f17)의 답 가운데에 이런 덩어리가 있었다:

    엑셀 파일로 만들었습니다.

    <tool_call>
    <function=local_write_document>
    <parameter=path>
    ...
    </function>
    </tool_call>

모델이 도구를 부르는 대신 그 글을 답에 적은 것이다(파일은 앞 걸음에서 이미 만들어져 있었다). 사람에게는 내부 글이 샌 것으로
보인다. 지난 판 3,464개 가운데 2개(10-08 한 번 · 이 판)였다.

양방향이다: 걷어야 하는 것과 **걷으면 안 되는 것**(그 형식을 설명해 달라고 해서 코드 칸에 적은 것 · 낱말로만 말한 것)을 같이 본다.
걷어 낸 호출은 **실행하지 않는다** — 답에 적힌 글을 명령으로 삼지 않는다.
"""
from __future__ import annotations

from alture_jarvis.runtime import UNEXECUTED_TOOL_CALL_NOTE, strip_leaked_thinking

_BLOCK = (
    "<tool_call>\n<function=local_write_document>\n<parameter=path>\n가격조사.xlsx\n</parameter>\n"
    "<parameter=format>\nxlsx\n</parameter>\n</function>\n</tool_call>"
)


def test_a_leaked_call_in_the_middle_is_removed_and_the_rest_stays() -> None:
    answer = f"가장 싼 곳은 다나와입니다.\n\n| 가게 | 값 |\n|---|---|\n| 다나와 | 1,000원 |\n\n엑셀 파일로 만들었습니다.\n\n{_BLOCK}\n\n⚠ **확인할 것이 있습니다.**\n\n만든 파일:\n- `가격조사.xlsx`"

    cleaned = strip_leaked_thinking(answer)

    assert "<tool_call>" not in cleaned and "<function=" not in cleaned and "<parameter=" not in cleaned
    assert cleaned.startswith("가장 싼 곳은 다나와입니다.") and "| 다나와 | 1,000원 |" in cleaned
    assert "엑셀 파일로 만들었습니다." in cleaned and "⚠ **확인할 것이 있습니다.**" in cleaned and "- `가격조사.xlsx`" in cleaned
    assert "\n\n\n" not in cleaned, "걷어 낸 자리에 빈 줄이 쌓이지 않는다"


def test_a_call_cut_off_at_the_end_is_removed_too() -> None:
    """길이에 끊겨 닫는 표식이 없는 덩어리 — 끝까지가 다 그 호출의 글이다."""
    answer = "세 가게를 정리했습니다.\n\n<tool_call>\n<function=local_write_document>\n<parameter=path>\n가격조사.xl"

    assert strip_leaked_thinking(answer) == "세 가게를 정리했습니다."


def test_a_cut_off_call_does_not_swallow_the_notes_we_appended() -> None:
    """닫는 표식이 없어도, 우리가 답 끝에 붙인 안내는 그 호출의 글이 아니다."""
    answer = (
        "세 가게를 정리했습니다.\n\n<tool_call>\n<function=local_write_document>\n<parameter=path>\n가격조사.xl"
        "\n\n⚠ **읽은 자료에 없는 금액이 있습니다.**\n\n만든 파일:\n- `가격조사.xlsx`"
    )

    cleaned = strip_leaked_thinking(answer)

    assert cleaned == "세 가게를 정리했습니다.\n\n⚠ **읽은 자료에 없는 금액이 있습니다.**\n\n만든 파일:\n- `가격조사.xlsx`"


def test_two_leaked_calls_are_both_removed() -> None:
    answer = f"첫째.\n\n{_BLOCK}\n\n둘째.\n\n{_BLOCK}"

    assert strip_leaked_thinking(answer) == "첫째.\n\n둘째."


def test_an_answer_that_is_only_a_call_says_so_instead_of_going_blank() -> None:
    cleaned = strip_leaked_thinking(_BLOCK)

    assert cleaned == UNEXECUTED_TOOL_CALL_NOTE
    assert "실행되지 않았습니다" in cleaned


# --- 걷으면 안 되는 것 -----------------------------------------------------------

def test_a_format_shown_in_a_code_block_is_left_alone() -> None:
    """그 형식이 무엇인지 물어서 코드 칸에 보여 준 것은 답의 내용이다."""
    answer = f"Qwen 계열은 도구를 이렇게 부릅니다.\n\n```xml\n{_BLOCK}\n```\n\n위에서 function 줄이 도구 이름입니다."

    assert strip_leaked_thinking(answer) == answer


def test_the_words_alone_are_left_alone() -> None:
    for answer in (
        "모델이 `<tool_call>` 표식을 답에 적으면 그 호출은 실행되지 않습니다.",
        "<tool_call> 은 여는 표식이고 </tool_call> 은 닫는 표식입니다.",
        "함수 이름은 <function=이름> 꼴로 적습니다.",
    ):
        assert strip_leaked_thinking(answer) == answer, answer


def test_an_ordinary_answer_comes_back_untouched() -> None:
    answer = "가장 싼 곳은 다나와 128,990원입니다.\n\n| 가게 | 값 |\n|---|---|\n| 다나와 | 128,990원 |"

    assert strip_leaked_thinking(answer) == answer
