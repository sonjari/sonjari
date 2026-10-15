"""한국어 쪽에서 고친 병이 영어 쪽에 그대로 남아 있던 셋 (2026-10-08 전수조사 3-6).

① 「○○ 밖의 파일은 건드리지 마라」(한국어 · 같은 날 실제 사고)의 영어 짝 — "any files other than these three" 가 판 전체 읽기 전용.
② `just read …` 에는 있던 예외가 `only read …` 에는 없었다 — "Only read the top 3 results and make an Excel file" 이 읽기 전용.
③ 맞장구(yes · ok · sure)가 글 어디에 있든 이어짓기였다 — 소감 한마디에 앞 요청이 통째로 붙는다(한국어는 글 머리에서만 본다).
"""
from __future__ import annotations

import pytest

from alture_jarvis import english
from alture_jarvis.plan import forbids_writes, is_continuation, write_prohibition_scope


@pytest.mark.parametrize("prompt", [
    "Add two entries to settings.py and fix the tests. Do not modify any files other than these three.",
    "Do not create any files except report.md.",
    "Fix the parser. Don't edit anything besides parser.py and its test.",
])
def test_a_prohibition_that_leaves_something_to_edit_is_not_job_wide(prompt: str) -> None:
    assert english.write_prohibition_scope(prompt) == "clause"
    assert write_prohibition_scope(prompt) == "clause"
    assert not forbids_writes(prompt)


@pytest.mark.parametrize("prompt", [
    "Explain how this folder is organized. Do not modify any files.",
    "This is research only. Do not create any files.",
    "Just review and tell me what you think. Read-only.",
])
def test_a_job_wide_prohibition_is_still_job_wide(prompt: str) -> None:
    assert english.write_prohibition_scope(prompt) == "job"


def test_only_read_these_and_make_a_file_is_not_read_only() -> None:
    assert english.write_prohibition_scope("Only read the top 3 results and make an Excel file.") == ""
    assert english.write_prohibition_scope("Only review. Change nothing.") == "job"


@pytest.mark.parametrize("prompt", ["Yes, do that", "Sure", "Okay, find three more", "go ahead", "Sounds good, continue"])
def test_an_assent_at_the_head_or_a_carry_on_phrase_leans_on_the_last_request(prompt: str) -> None:
    assert is_continuation(prompt)


@pytest.mark.parametrize("prompt", [
    "That looks okay to me, thanks",
    "Wow this is so good, sure beats the old one",
    "ok so what do you think about the price",
])
def test_an_assent_word_in_the_middle_of_a_remark_is_not_a_continuation(prompt: str) -> None:
    assert not is_continuation(prompt)
