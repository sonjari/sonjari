"""문서 꼴 카드 11개 (2026-10-25 대표 「문서도 표준 꼴을 증류해 손자리에 탑재」) — 실리는지 · 맞는 요청에 붙는지 · 이름 · 메일이 없는지."""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.skill_domains import BY_ID
from alture_jarvis.skills import match_skills

FORMS = Path(__file__).resolve().parents[1] / "skills" / "vendor" / "docforms"
CARDS = sorted(p.parent.name for p in FORMS.glob("doc-*/SKILL.md"))


def test_eleven_cards_ship_with_a_license_and_the_code_check_note() -> None:
    assert len(CARDS) == 11 and (FORMS / "LICENSE").exists()
    for name in CARDS:
        body = (FORMS / name / "SKILL.md").read_text(encoding="utf-8")
        assert f"name: {name}" in body
        assert "손자리가 저장 전에 코드로 대 보는 것" in body, name  # 코드가 실제로 하는 검사만 그렇다고 말한다
        assert "@" not in body and "주식회사" not in body, name


@pytest.mark.parametrize("ask, card", [
    ("이번 주 주간 업무 보고서 한글 파일로 만들어줘", "doc-weekly-report"),
    ("어제 회의 녹음 정리해서 회의록 써줘", "doc-meeting-minutes"),
    ("구청에 보낼 협조 요청 공문 작성해줘", "doc-official-letter"),
    ("신제품 출시 보도자료 써줘", "doc-press-release"),
    ("학원 수강료 견적서 엑셀로 만들어줘", "doc-quotation"),
    ("송년회 행사 계획서 만들어줘", "doc-event-plan"),
    ("중2 수학 강의계획서 만들어줘", "doc-syllabus"),
    ("고객 설문 조사 보고서 문서로 정리해줘", "doc-research-report"),
    ("아르바이트 근로계약서 만들어줘", "doc-standard-contract"),
    ("신사업 기획안 써줘", "doc-proposal"),
    ("write meeting minutes for today", "doc-meeting-minutes"),
])
def test_each_form_comes_first_for_its_request(ask, card) -> None:
    assert [name for name, _ in match_skills(ask)][0] == card


def test_unrelated_and_review_asks_do_not_pull_the_writing_cards() -> None:
    assert match_skills("회의 일정 잡아줘") == []
    assert "doc-resume" not in [n for n, _ in match_skills("이력서 첨삭해줘")]
    assert "doc-resume" in [n for n, _ in match_skills("이력서 작성해줘")]
    assert [n for n, _ in match_skills("예비창업패키지 사업계획서 써줘")][0] == "business-plan"


def test_cards_are_in_their_domains() -> None:
    assert {"doc-official-letter", "doc-quotation", "doc-weekly-report"} <= set(BY_ID["office"].skills)
    assert "doc-syllabus" in BY_ID["education"].skills and "doc-resume" in BY_ID["career"].skills
