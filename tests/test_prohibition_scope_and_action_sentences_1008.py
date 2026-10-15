"""쓰기 금지 범위는 끝 글자가 아니라 요청 자체로 · 행위 규칙은 한 문장 안에서 (2026-10-08 전수조사 3-4).

① 지목 금지(「○○ 파일은 건드리지 마」)가 판 전체 금지로 읽히는지는 금지 앞 낱말의 **끝 글자**로 갈렸다 —
   「설정 파일」은 지목인데 「지도 파일」·「회의 파일」·「원가 파일」은 도·의·가(조사와 같은 글자)로 끝나 판 전체였다.
   「지도 파일은 건드리지 마. 요약 문서를 새로 만들어줘」가 읽기 전용이 되어 만들어 달라는 문서를 못 만든다.
   끝 글자 표를 늘리지 않는다: 금지 구절 밖에서 **새 파일·문서를 만들라고 분명히 시키면** 그 금지는 지목이다.
   운영 요청 1,810개: 달라진 것 하나(새 파일로 저장하라면서 원본은 수정하지 말라는 요청 — 산출물·각주 요구가 이제 선다).
   처음 규칙(「무언가 만들라·쓰라」)은 넷을 바꿨고 셋이 틀린 방향이라 조였다 — 그 셋이 아래 「그대로 판 전체」 표본이다.

② 메일 발송 · 일정 수정 · 일정 삭제 규칙의 `.*` 가 문장 끝을 건너갔다(10-02 에 일정 등록에서 고친 병과 같은 꼴).
"""
from __future__ import annotations

import pytest

from alture_jarvis import plan
from alture_jarvis.plan import forbids_writes, write_prohibition_scope


@pytest.mark.parametrize("prompt", [
    "지도 파일은 건드리지 마. 요약 문서를 새로 만들어줘.",
    "회의 파일은 수정하지 말고 새 문서로 정리해줘",
    "원가 파일은 손대지 마라. 계산은 새 엑셀로 해줘.",
    "설정 파일은 건드리지 마. 요약 문서를 새로 만들어줘.",
    "원본과 외부 사이트는 절대 수정하지 마라. 결과는 출력 폴더에 새 파일로 저장해라.",
])
def test_a_request_that_also_asks_for_something_new_is_not_read_only(prompt: str) -> None:
    assert write_prohibition_scope(prompt) == "clause"
    assert not forbids_writes(prompt)


@pytest.mark.parametrize("prompt", [
    "조사만 해줘. 파일은 만들지 마.",
    "이 폴더를 살펴보고 구조를 설명해줘. 파일은 건드리지 마라.",
    # 「정리해줘」는 파일을 만들라는 말이 아니다 — 채팅으로 답하라는 판이다.
    "설계 문서를 직접 읽고 핵심 3개를 채팅으로 정리해줘. 파일 수정하지 마.",
    # 판 전체를 직접 말한 금지는, 뒤에 무엇이 오든 낮추지 않는다.
    "파일을 수정하거나 외부 서비스에 쓰지 말고 조사·분석만 해라. 결과는 새 문서 형식으로 비교해 말해줘.",
    "조사만 해줘. 읽기 전용이다.",
])
def test_a_job_wide_prohibition_stays_job_wide(prompt: str) -> None:
    assert write_prohibition_scope(prompt) == "job"
    assert forbids_writes(prompt)


def _labels(prompt: str) -> list[str]:
    return [requirement.label for requirement in plan.extract(prompt) if requirement.kind == "action"]


@pytest.mark.parametrize("prompt", [
    "캘린더에서 다음 주 일정을 보여줘. 회의록은 따로 수정할 거야.",
    "이번 주 일정을 알려줘. 그리고 어제 그 파일은 지워도 돼?",
    "메일함에서 견적 메일을 찾아 요약해줘. 자료는 나중에 직접 보낼게.",
])
def test_a_verb_in_the_next_sentence_is_not_an_action_on_this_one(prompt: str) -> None:
    assert _labels(prompt) == []


@pytest.mark.parametrize(("prompt", "label"), [
    ("내일 회의 일정을 오후 3시로 옮겨줘", "일정 수정"),
    ("다음 주 화요일 일정 삭제해줘", "일정 삭제"),
    ("견적서를 정리해서 팀장에게 메일로 보내줘", "메일 발송"),
    # 문장 안의 점(주소·파일 이름)에서는 끊지 않는다.
    ("lead@team.example 로 report.pdf 를 메일 첨부해서 보내줘", "메일 발송"),
])
def test_an_action_asked_in_one_sentence_still_stands(prompt: str, label: str) -> None:
    assert label in _labels(prompt)
