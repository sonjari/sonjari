"""스킬은 **있는 것보다 닿는 것**이 중요하다.

★ 2026-09-02 전수 진단. 스킬 라우팅이 도구 실행 11,043회 중 **11건**이었다.
어느 문에서 떨어지는지 프롬프트 382개로 세어 보니:

    ① 제외 낱말에 걸림    40  (10%)
    ② 일 시키는 동사 없음  190 (49%)   ← 대부분 잡담. 맞게 떨어짐
    ③ 대상 낱말 없음      140 (36%)   ← ★ 전부 사용자님의 실제 업무였다
    ④ 스킬 골라짐          12  (3%)

스킬 85개가 marketing·writing·thinking·engineering·devstack 뿐이라
**채용 일에 맞는 것이 아예 없었다.** 낱말은 지어내지 않고 떨어진 프롬프트
169개에서 캤다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.skills import load_skills, match_skill

CAREER = ("career-job-search", "career-resume-review", "career-application-tailoring")


def test_the_career_skills_exist_and_load() -> None:
    docs = load_skills(Path("skills"))
    for name in CAREER:
        assert name in docs, f"{name} 이 로드가 안 된다"
        assert docs[name].collection == "career"


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("나래이 이력서 첨삭해줘", "career-resume-review"),
        ("이력서 좀 봐줘", "career-resume-review"),
        ("자기소개서 다듬어줘", "career-resume-review"),
        ("사람인에서 공고 찾아줘", "career-job-search"),
        ("오늘자로 지원 가능한 채용 공고 알아봐줘", "career-job-search"),
        ("이직할 데 알아봐줘", "career-job-search"),
        ("회사별로 각주 달아줘", "career-application-tailoring"),
        ("서류 통과 가능성 높이게 손봐줘", "career-application-tailoring"),
    ],
)
def test_the_way_a_person_actually_asks(prompt: str, expected: str) -> None:
    got = match_skill(prompt)
    assert got is not None, f"「{prompt}」에 스킬이 안 붙는다"
    assert got[0] == expected, f"「{prompt}」 → {got[0]}"


def test_the_live_request_that_started_this_gets_a_skill() -> None:
    """★ 이 문장이 스킬 없이 돌아서 15걸음을 헛돌았다."""
    real = (
        "자비스 구글 드라이브에서 나래이 이력서를 한번 읽고 오늘자로 지원 가능한 "
        "공고들을 추천해서 조사를 해줘 정규직은 필수고 경력은 3년 이상으로 "
        "알아봐주고 한글 파일에 이력서 원문 그대로 옮기고 각주를 달아줘"
    )
    got = match_skill(real)

    assert got is not None, "실제 요청에 스킬이 안 붙는다"
    assert got[0].startswith("career-")


def test_a_research_request_is_narrowed_not_blocked() -> None:
    """★ 좁힐 때는 **무엇을 막으려 했는지**를 다시 봐야 한다.

    조사 낱말(「알아봐」·「조사해」)이 예전엔 스킬을 통째로 막았다. 사고 틀만
    남기게 고쳤더니 이번엔 **조사 스킬 자체가** 조사 요청에서 막혔다 —
    조사하는 법을 적어 둔 스킬이 조사에서 잘린 것이다. 둘 다 틀렸다.
    """
    from alture_jarvis.skills import _RESEARCH_SAFE_PREFIXES

    assert "career-" in _RESEARCH_SAFE_PREFIXES
    assert "thinking-" in _RESEARCH_SAFE_PREFIXES
    # 카피라이팅은 조사에 안 맞으니 여전히 안 붙는다.
    assert match_skill("경쟁사 카피 조사해줘 상세페이지 카피 써줘") is None or not str(
        match_skill("경쟁사 카피 조사해줘 상세페이지 카피 써줘")[0]
    ).startswith("copywriting")


def test_a_writing_route_is_still_blocked() -> None:
    """「블로그에 써줘」가 스킬로 새면 아무 데도 안 올린다 — 그건 계속 막는다."""
    assert match_skill("네이버 블로그에 글 써줘") is None


def test_a_broad_word_does_not_hijack_the_route() -> None:
    """「맞춤」 하나로 「학원 맞춤 AI」가 걸렸다. 넓은 낱말은 갈래를 오염시킨다."""
    got = match_skill("크몽에서 '학원 맞춤 AI'로 검색해서 상세 페이지 열어 읽고 알려줘")
    assert got is None or got[0] != "career-application-tailoring"


def test_the_skills_say_what_actually_goes_wrong() -> None:
    """플레이북이 일반론이면 안 쓰인 85개가 하나 더 느는 것뿐이다."""
    docs = load_skills(Path("skills"))
    search = docs["career-job-search"].body
    review = docs["career-resume-review"].body

    # 오늘 실제로 겪은 고장이 적혀 있어야 한다.
    assert "마감" in search, "마감 지난 공고를 읽은 사고가 안 적혀 있다"
    assert "상세" in search and "목록" in search
    assert "각주" in review and "원문" in review
