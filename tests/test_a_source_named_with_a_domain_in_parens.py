"""출처 이름 뒤 괄호 설명 (2026-10-02 대표 운영 판).

「K-Startup(k-startup.go.kr)에서 … 지원사업 5개를 찾아 … 엑셀로」가 출처 판정에 안 걸렸다. 그래서 「5개」가 읽기 개수 요구로
안 올라갔고 계획은 「산출물 파일」 하나뿐이었다. 22걸음째에 상세 공고를 읽는 중인데 「남은 목표(파일)에 진전 없음」으로 접혀
5개 중 1행만 내고 파일 없이 끝났다(stop_reason wrapped_up:no_progress_for_remaining_goal).
"""

from __future__ import annotations

from alture_jarvis import agent
from alture_jarvis.plan import extract

KSTARTUP = (
    "K-Startup(k-startup.go.kr)에서 지금 모집 중인 창업 지원사업 중 AI나 소프트웨어 분야에 신청할 수 있는 것 5개를 찾아, "
    "사업명·주관기관·지원금 규모·신청 자격(업력 제한)·마감일·공고 주소를 엑셀로 정리해줘."
)


def test_a_name_followed_by_a_parenthesised_domain_is_a_source() -> None:
    assert agent.named_sources(KSTARTUP) == ["K-Startup"]
    assert agent.named_sources("사람인(saramin.co.kr)에서 여수 회계 공고 3개") == ["사람인"]
    assert agent.named_sources("잡코리아 （jobkorea）에 들어가서 공고 봐줘") == ["잡코리아"]


def test_the_count_becomes_a_reading_requirement() -> None:
    reqs = extract(KSTARTUP, has_named_source=bool(agent.named_sources(KSTARTUP)))
    counts = [r for r in reqs if r.kind == "count"]
    assert counts and counts[0].target == 5, reqs
    assert any(r.kind == "artifact" for r in reqs)


def test_parentheses_elsewhere_do_not_invent_a_source() -> None:
    # 괄호가 조사 앞이 아니면 아무것도 걷지 않는다 — 출처 없는 말은 그대로 출처 없음.
    assert agent.named_sources("신청 자격(업력 제한)을 정리해줘") == []
