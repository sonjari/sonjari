"""생각 채널 표식이 답 앞머리로 새면 걷는다 — 새 프로필 E2E 에서 인계 대화 첫 줄이 「thought」였다."""
from __future__ import annotations

from alture_jarvis.runtime import UNEXECUTED_PLAN_NOTE, strip_leaked_thinking


def test_leaked_gemma_thinking_prefix_is_removed() -> None:
    assert strip_leaked_thinking("thought\n<channel|>작업 현황을 정리했습니다.") == "작업 현황을 정리했습니다."
    assert strip_leaked_thinking("<|channel|>thought\n계획을 세운다\n<channel|>답입니다") == "답입니다"


def test_ordinary_answers_are_untouched() -> None:
    for text in (
        "thought experiment는 실제로 해 볼 수 없는 것을 가정해 보는 방법입니다.",
        "토큰 이름 <channel|> 은 Gemma 4 생각 채널을 닫는 표식입니다.",
        "평범한 답",
    ):
        assert strip_leaked_thinking(text) == text


def test_answer_wrapped_whole_in_thought_tags_is_labelled_as_an_unexecuted_plan() -> None:
    """W0 라이브: 답 전체가 `<thought>…</thought>` — 안은 「엑셀 파일을 만들겠습니다」 계획뿐이었다."""
    leaked = "<thought\n>\nsandbox_run 이 꺼져 있습니다. 엑셀 파일을 만들겠습니다.\n</thought>"
    cleaned = strip_leaked_thinking(leaked)
    assert cleaned.startswith(UNEXECUTED_PLAN_NOTE)
    assert "<thought" not in cleaned and "</thought>" not in cleaned
    assert "엑셀 파일을 만들겠습니다" in cleaned


def test_thought_block_followed_by_a_real_answer_keeps_only_the_answer() -> None:
    assert strip_leaked_thinking("<thought>\n계획\n</thought>\n정리했습니다.") == "정리했습니다."


def test_thought_tags_inside_an_answer_are_not_touched() -> None:
    text = "Gemma 는 <thought> 태그로 생각을 감쌀 때가 있습니다."
    assert strip_leaked_thinking(text) == text
