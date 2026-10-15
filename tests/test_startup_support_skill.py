"""창업 지원사업 스킬 (2026-10-02 대표 운영 판 K-Startup 3차).

「AI」 공고 13건 대부분이 교육·행사였고, 「3년 이상 제외」 문장으로 「1년 미만 불가」를 끌어냈다. 지원사업을 직접 받아 본
대표의 현장 지식(공고 종류·업력 판단·자부담·시기)으로 쓴 스킬이 이 요청에 붙는지, 엉뚱한 요청에는 안 붙는지 본다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.skill_domains import BY_ID
from alture_jarvis.skills import match_skills

KSTARTUP = (
    "K-Startup(k-startup.go.kr)에서 지금 모집 중인 창업 지원사업 중 AI나 소프트웨어 분야에 신청할 수 있는 것 5개를 찾아, "
    "사업명·주관기관·지원금 규모·신청 자격(업력 제한)·마감일·공고 주소를 엑셀로 정리해줘."
)
SKILL = Path(__file__).resolve().parents[1] / "skills" / "vendor" / "alture" / "startup-support-search" / "SKILL.md"


def test_the_skill_comes_first_for_a_support_program_search() -> None:
    assert match_skills(KSTARTUP)[0][0] == "startup-support-search"
    assert match_skills("예창패랑 초창패 공고 찾아서 정리해줘")[0][0] == "startup-support-search"


def test_job_search_and_unrelated_asks_do_not_get_it() -> None:
    assert "startup-support-search" not in [n for n, _ in match_skills("사람인에서 여수 회계 공고 3개 찾아 엑셀로 정리해줘")]
    assert match_skills("청년 육아 지원금 알려줘") == []


def test_the_skill_carries_the_judgement_rules_and_no_personal_names() -> None:
    body = SKILL.read_text(encoding="utf-8")
    assert "기관 모집" in body and "확인 필요" in body and "선 자부담 후 환급" in body
    assert "「N년 이상은 제외」는" in body
    for personal in ("박가람", "전남형", "로보메타핏"):
        assert personal not in body
    assert "startup-support-search" in BY_ID["startup"].skills
