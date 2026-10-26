"""사업계획서 · IR 틀 (2026-10-25 대표: 선정 · 투자받은 문서 셋의 짜임을 증류).

쓰는 판에 이 틀이 맨 앞에 붙는지, 공고를 찾는 판 · 엉뚱한 판에는 앞서지 않는지, 틀에 핵심 규칙이 있고 남의 이름이 없는지 본다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.skill_domains import BY_ID
from alture_jarvis.skills import match_skills

SKILL = Path(__file__).resolve().parents[1] / "skills" / "vendor" / "alture" / "business-plan" / "SKILL.md"


def _names(prompt: str) -> list[str]:
    return [name for name, _ in match_skills(prompt)]


def test_writing_a_business_plan_puts_the_frame_first() -> None:
    assert _names("예비창업패키지 사업계획서 써줘")[0] == "business-plan"
    assert "writing-plans" not in _names("예비창업패키지 사업계획서 써줘")
    assert _names("투자 유치용 IR 장표 만들어줘")[0] == "business-plan"
    assert _names("피치덱 10장 만들어줘") == ["business-plan"]
    assert _names("write a business plan for a bakery") == ["business-plan"]
    assert _names("Make a pitch deck for my startup") == ["business-plan"]


def test_searching_for_programs_still_brings_the_search_skill() -> None:
    names = _names("예창패 공고 찾아서 사업계획서 초안까지 만들어줘")
    assert "startup-support-search" in names and "business-plan" in names
    assert _names("예창패랑 초창패 공고 찾아서 정리해줘")[0] == "startup-support-search"


def test_unrelated_asks_do_not_get_it() -> None:
    for prompt in ("회사 소개 PPT 만들어줘", "사람인에서 여수 회계 공고 3개 찾아 엑셀로 정리해줘", "구현 계획 세워줘",
                   "아이리스 꽃 사진 정리해서 문서로"):
        assert "business-plan" not in _names(prompt), prompt


def test_the_frame_carries_the_rules_and_no_source_names() -> None:
    body = SKILL.read_text(encoding="utf-8")
    for rule in ("산출식", "[증빙 필요", "사람 장면", "왜 지금", "숫자 대조", "원가 대비", "요약 셋", "개조식"):
        assert rule in body, rule
    # 증류한 원본 문서의 회사 · 사람 이름은 싣지 않는다(공개 저장소 · 비밀 표시 문서).
    for name in ("BC모빌리티", "애쓰지마", "SGMA", "어신", "김성우", "임동현", "브리찌", "박가람"):
        assert name not in body, name
    assert "business-plan" in BY_ID["startup"].skills
