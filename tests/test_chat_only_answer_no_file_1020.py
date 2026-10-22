"""채팅으로 답하라고 한 일에 시키지 않은 파일을 만들지 않는다 (2026-10-20 README 영어 영상 촬영 · 잡 a1d05ead).

클로드 코드가 맡긴 「… Answer in the chat reply — no file needs to be created.」에 「실제 산출물 파일 만들기」가 서서
손자리가 .docx 를 만들었다. 운영 요청 2,430개에 옛 · 새 판정을 대 보니 바뀌는 것은 이 판 하나뿐이었다.
"""

from __future__ import annotations

import pytest

from alture_jarvis import plan

OLLAMA = (
    "Open the Ollama GitHub releases page (https://github.com/ollama/ollama/releases) and read the release notes for the "
    "single latest release. Report the release version/tag, its date, and list exactly three concrete changes from those "
    "notes (quote the wording in the notes), with the source URL for each. Answer in the chat reply — no file needs to be created."
)


def test_the_filmed_request_does_not_ask_for_a_file() -> None:
    assert not plan.wants_an_artifact(OLLAMA)


@pytest.mark.parametrize("text", [
    "Report three changes from the notes. No file needs to be created.",
    "Report three changes from the notes. No document has to be made.",
    "Report three changes from the notes; a file is not needed.",
    "Read the Ollama release notes and answer in the chat reply.",
    "결과는 답으로만 알려 줘. 표로 정리해 줘",
    "채팅으로 알려 줘, 표로 정리해서",
    "결과를 텍스트로 요약만 해 줘",
])
def test_chat_only_or_declined_file_is_not_a_file_request(text: str) -> None:
    assert not plan.wants_an_artifact(text)


@pytest.mark.parametrize("text", [
    "Answer in chat only, and also save the table as an Excel file.",
    "Save it as an Excel file. No separate document needs to be created.",
    "엑셀 파일로 만들어 주고 요약은 채팅으로 알려 줘",
    "워드나 한글로만들어서 보여줘",  # 「한글로 만들어」의 「글로만」은 「글로만 답해」가 아니다
    "사람인 공고 3개를 찾아서 엑셀로 정리해 줘",
    "Create a file named notes.md with the summary",
])
def test_real_file_requests_still_ask_for_a_file(text: str) -> None:
    assert plan.wants_an_artifact(text)


# ── 「직접 계산해 보기」가 읽어 올 값에 서던 것 (운영 41bd1869 · UI-TARS 정리) ──────────────────────────


def test_a_listed_value_to_answer_is_not_a_computation() -> None:
    assert not plan.wants_a_computation("이 저장소의 지원 운영체제, 라이선스, 별 개수와 마지막 커밋 날짜. 확인한 것과 못 한 것을 나눠서 답해 줘.")


@pytest.mark.parametrize("text", [
    "사과가 10개 있고 3개 먹으면 몇 개 남는지 답해 줘",
    "계산기로 1234 × 5678 계산해서 알려 줘.",
    "How many hours are between 9am and 5pm? Answer with the number",
])
def test_real_arithmetic_is_still_a_computation(text: str) -> None:
    assert plan.wants_a_computation(text)
