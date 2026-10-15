"""짧은 답의 **어느 문장이든** 앞으로 할 일이고 결과를 말한 문장이 없으면 예고다 (2026-10-04 실전 판 e055235f).

사람인 공고를 엑셀로 정리한 판이 검토 지적을 받고 낸 최종 답:

    시스템이 지적한 대로, 한빛기술전략연구소 담당업무 표기를 수정하고 최종 답을 다시 작성하겠습니다. 엑셀 파일을 수정합니다.

이 답이 `complete` 로 나갔다. 예고 그물은 **마지막 문장**만 봤고(「수정합니다」는 낱말표에 없다), 예고는 첫 문장에 있었다.
낱말을 더하지 않고 모양으로 본다 — 운영 답 2,023개 역검증: 새로 걸리는 것 1(이 판), 헛걸림 0.
"""
from __future__ import annotations

import pytest

from alture_jarvis.agent import _announces_without_a_result, _only_a_promise, _states_a_fact

THE_ANSWER = "시스템이 지적한 대로, 한빛기술전략연구소 담당업무 표기를 수정하고 최종 답을 다시 작성하겠습니다. 엑셀 파일을 수정합니다."


def test_the_answer_that_went_out_as_complete_is_a_promise() -> None:
    assert _only_a_promise(THE_ANSWER) is True


@pytest.mark.parametrize("answer", [
    "표를 다시 만들겠습니다. 파일을 고칩니다.",
    "먼저 목록을 정리하겠습니다. 그다음 엑셀에 옮깁니다.",
])
def test_a_promise_in_an_earlier_sentence_counts(answer: str) -> None:
    assert _announces_without_a_result(answer) is True


@pytest.mark.parametrize("answer", [
    # 결과를 말한 문장이 있다 — 바로잡는 답이다.
    "정정하겠습니다. 실제로는 2개의 문서를 성공적으로 읽었습니다.",
    # 못 한 것을 말하고 사람에게 묻는다 — 넘기는 답이다.
    "손자리 관련 파일은 찾지 못했습니다. 주소를 알려 주시면 바로 접속해 드릴게요. 이미 로그인되어 있는 상태인가요?",
    "주소를 알려 주시면 접속해 드릴게요. 로그인돼 있나요?",
    # 있는 사실을 말한다.
    "파일은 문서 폴더에 있습니다. 필요하시면 다시 만들어 드리겠습니다.",
    # 앞으로 할 일이 아예 없다.
    "대전의 정규직 공고는 3건입니다.",
])
def test_an_answer_that_reports_or_asks_is_left_alone(answer: str) -> None:
    assert _announces_without_a_result(answer) is False


@pytest.mark.parametrize("sentence, expected", [
    ("실제로는 2개를 읽었습니다.", True),
    ("찾지 못했습니다", True),
    ("파일이 있습니다.", True),
    ("값이 없었어요", True),
    ("다시 작성하겠습니다.", False),
    ("엑셀 파일을 수정합니다.", False),
    ("확인해 보겠어요", False),
    ("공고는 3건입니다.", False),
])
def test_what_counts_as_stating_a_fact(sentence: str, expected: bool) -> None:
    assert _states_a_fact(sentence) is expected


def test_a_long_answer_with_a_table_is_never_a_promise() -> None:
    answer = "오류를 바로잡겠습니다. 확인한 항목만 정리합니다.\n\n| 회사 | 형태 |\n|---|---|\n| 데이터나루터 | 정규직 |"

    assert _only_a_promise(answer) is False
