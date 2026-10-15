"""복합 작업에는 **스킬도 여럿** 붙는다.

★ 2026-09-02. 사용자님 요청 하나가 이랬다:

    "공고 찾아서 조사하고, 그 다음에 이력서 원문 옮기고 회사별로 각주 달아줘"

조사 + 첨삭 + 맞춤이 한 판에 있는데 스킬은 **하나만** 붙었다. `career-job-search`
만 물고 가고 첨삭은 맨손이었다.

⚠ 그렇다고 다 본문으로 넣으면 플레이북이 도구 규율을 밀어낸다. 그래서:

    첫째   본문(4,000자)
    둘째   본문(2,000자)   ← `skill_read` 를 부르라고 두면 **안 부른다**(장부 10,548중 2건)
    셋째~  이름 + 한 줄
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.skills import SkillLibrary, match_skills

REAL = (
    "자비스 구글 드라이브에서 나래이 이력서를 읽고 오늘자로 지원 가능한 공고를 "
    "조사해줘 그다음에 한글 파일에 이력서 원문 그대로 옮기고 회사별로 각주 달아줘"
)


class _Silent:
    def publish(self, *args, **kwargs) -> None: ...
    def add_audit(self, *args, **kwargs) -> None: ...


@pytest.fixture()
def runtime():
    config = type(
        "_S",
        (),
        {
            "skills_dir": Path("skills"),
            "skills_max_chars": 12_000,
            "skills_body_max_chars": 12_000,
            "skills_fold_sections": False,
            "skills_route_enabled": True,
        },
    )()
    holder = JarvisRuntime.__new__(JarvisRuntime)
    holder.skills = SkillLibrary(config)
    holder.config = config
    holder.events = _Silent()
    holder.store = _Silent()
    return holder


def test_a_compound_request_matches_several(runtime) -> None:
    available = {name for name, doc in runtime.skills.skills.items() if doc.served}
    matches = match_skills(REAL, available=available, limit=3)

    assert [name for name, _ in matches] == [
        "career-job-search",
        "career-resume-review",
        "career-application-tailoring",
    ]


def test_the_second_playbook_is_put_in_by_code_not_hoped_for(runtime) -> None:
    """이름만 주고 `skill_read` 를 부르게 두면 **안 부른다.**"""
    note = JarvisRuntime._skill_instruction(runtime, REAL, job_id="j1", for_agent=True)

    assert "채용 공고 조사" in note, "첫째 플레이북이 없다"
    assert "이력서 첨삭" in note, "둘째 플레이북이 없다 — 첨삭이 맨손으로 간다"
    assert "두 번째 플레이북" in note


def test_the_rest_are_offered_by_name(runtime) -> None:
    note = JarvisRuntime._skill_instruction(runtime, REAL, job_id="j2", for_agent=True)

    assert "career-application-tailoring" in note
    assert "skill_read" in note, "더 있다는 것을 어떻게 꺼내는지 안 알려 준다"


def test_a_second_call_in_the_same_job_gives_the_same_thing(runtime) -> None:
    """★ 판을 두 번 세지 않을 뿐, **주는 것은 같아야 한다.**

    라우터에서 한 번 불린 판이 답변 경로에서 둘째 플레이북을 잃으면, 같은 판인데
    붙는 것이 달라진다.
    """
    first = JarvisRuntime._skill_instruction(runtime, REAL, job_id="same", for_agent=True)
    second = JarvisRuntime._skill_instruction(runtime, REAL, job_id="same", for_agent=True)

    assert first == second


def test_a_single_topic_request_still_gets_one(runtime) -> None:
    """복합이 아니면 늘리지 않는다 — 자리는 도구 규율의 것이다."""
    note = JarvisRuntime._skill_instruction(
        runtime, "학원 수강료 가격 책정 전략을 세워줘", job_id="j3", for_agent=True
    )

    assert note
    assert "두 번째 플레이북" not in note


def test_the_injection_stays_within_a_sane_budget(runtime) -> None:
    """플레이북이 도구 규율을 밀어내면 안 된다."""
    note = JarvisRuntime._skill_instruction(runtime, REAL, job_id="j4", for_agent=True)

    assert len(note) < 8_000, f"{len(note):,}자 — 너무 크다"
