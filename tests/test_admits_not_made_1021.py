"""「파일은 만들지 못했습니다」도 자백이다 (2026-10-21).

접을 때 손자리가 답의 표를 대신 엑셀로 저장하면 산출물 요구가 채워진다. 그런데 그 답이 스스로 「만들지 못했다」 · 「저장하지 못했다」고
말하면 판은 덜 끝난 것이다. 동사 목록에 만들 · 생성 · 저장 · 작성 · 실행 · 내려받 · 다운로드가 없어 HN 세기 판 · 가격 판이 complete 로 나갔다.
운영 complete 2,128판 중 새로 걸리는 판 6 — 모두 실제로 덜 끝난 판.
"""

from __future__ import annotations

import pytest

from alture_jarvis.answer_gate import _ADMITS_NOT_DONE


@pytest.mark.parametrize("text", [
    "| .xlsx 파일 | **만들지 못했다** |",
    "**파일은 만들지 못했습니다.** G마켓과 11번가에서는 정확한 판매 가격이",
    "권한 오류가 발생하여 문서를 저장하지 못했습니다.",
    "입력란을 찾지 못해 작성하지 못했습니다.",
    "파일은 생성하지 못했습니다.",
    "마우스로 타이핑하는 방식은 실행할 수 없었습니다.",
])
def test_saying_the_file_was_not_made_is_an_admission(text: str) -> None:
    assert _ADMITS_NOT_DONE.search(text)


@pytest.mark.parametrize("text", [
    "엑셀 파일을 만들었습니다. 경로는 아래와 같습니다.",
    "저장하지 못할 경우에는 다른 폴더를 골라 주세요.",
    "파일을 만들 수 있으면 바로 만들겠습니다.",
])
def test_done_or_conditional_sentences_are_not_admissions(text: str) -> None:
    assert not _ADMITS_NOT_DONE.search(text)
