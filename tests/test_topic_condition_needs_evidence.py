"""분야 조건에는 근거가 있어야 한다 (2026-10-03 K-Startup 5차 9ac405c8).

「AI나 소프트웨어 분야 5개」에 사업명·본문 어디에도 AI·SW 가 없는 일반 사업 5개를 「AI/SW 창업지원사업」으로 적었다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.plan import mentions_topic, topic_conditions

PROMPT = ("K-Startup(k-startup.go.kr)에서 지금 모집 중인 창업 지원사업 중 AI나 소프트웨어 분야에 신청할 수 있는 것 5개를 찾아, "
          "사업명·주관기관·지원금 규모·신청 자격(업력 제한)·마감일·공고 주소를 엑셀로 정리해줘.")
# 실제 판 답의 표 그대로.
ANSWER = """## K-Startup AI/소프트웨어 창업지원사업 정리 완료

| # | 사업명 | 주관 | 지원금 | 업력 | 마감 | 신청 가능 |
|---|---|---|---|---|---|---|
| 1 | 팁스(TIPS) 창업기업 지원계획 | 창업진흥원 | 최대 8억(딥테크 15억) | 제한 없음* | 12.31 | **가능\\*** |
| 2 | 공공데이터 활용 지원(오픈이노베이션) | 창업진흥원 | 최대 1억 | 7년 이내 | 10.06 | **가능** |
| 3 | 2026 딥테크 스튜디오 | 대전창조경제혁신센터 | 기술이전료 최대 1,500만 | 7년 이내(대전) | 10.31 | **가능** |
| 4 | SVC Seoul 멤버십(확장형) | 창업진흥원 | 공유오피스+자문바우처 | 7년 이내 | 12.11 | **가능** |
| 5 | 실리콘밸리 GTM 프로그램 | 창업진흥원 실리콘밸리사무소 | 전략 컨설팅(금전 아님) | 7년 미만 | 10.09 | **가능** |
"""


def _agent_with_bodies(bodies: dict[str, str]) -> BrowserAgent:
    agent = BrowserAgent.__new__(BrowserAgent)
    agent._page_bodies = lambda steps, job_id: bodies  # type: ignore[method-assign]
    return agent


def test_conditions_are_read_from_the_request() -> None:
    assert [term for term, _ in topic_conditions(PROMPT)] == ["AI", "소프트웨어"]
    assert [term for term, _ in topic_conditions("AI 또는 소프트웨어 관련 창업지원사업 공고 5개")] == ["AI", "소프트웨어"]
    assert [term for term, _ in topic_conditions("Find 3 AI-related startups on Product Hunt")] == ["AI"]
    assert [term for term, _ in topic_conditions("find 5 programs related to AI or data")] == ["AI", "data"]
    # 조건이 없거나 개수가 없으면 잴 것이 없다.
    assert topic_conditions("사람인에서 여수 회계 공고 3개") == []
    assert topic_conditions("창업 관련 지원사업 5개") == []
    assert topic_conditions("AI 분야 소식 알려줘") == []


def test_abbreviations_match_only_as_words() -> None:
    same = dict(topic_conditions(PROMPT))
    assert mentions_topic("AI 바우처 지원사업", same["AI"])
    assert mentions_topic("인공지능 기반 창업", same["AI"])
    assert not mentions_topic("main domain campaign", same["AI"])
    assert mentions_topic("SW 융합 클러스터", same["소프트웨어"])


def test_the_kstartup_answer_says_the_condition_is_unconfirmed() -> None:
    bodies = {"k-startup.go.kr/a": "팁스(TIPS) 창업기업 지원계획 — 기술창업 기업을 지원합니다. 업력 제한 없음.",
              "k-startup.go.kr/b": "SVC Seoul 멤버십(확장형) 공유오피스 입주기업 모집"}
    note = _agent_with_bodies(bodies)._topic_condition_check(PROMPT, ANSWER, [], "job")
    assert "「AI·소프트웨어」 조건의 근거를 못 찾은 항목" in note
    assert "5개 중 5개" in note and "전용 항목은 찾지 못했을 수 있습니다" in note


def test_rows_with_evidence_in_their_name_or_page_pass() -> None:
    answer = ANSWER.replace("2026 딥테크 스튜디오", "AI 바우처 지원사업")
    bodies = {
        # 줄 이름이 든 본문에 조건 말이 있으면 근거다.
        "k-startup.go.kr/a": "팁스(TIPS) 창업기업 지원계획 — 지원 분야: 인공지능, 바이오, 반도체",
        "k-startup.go.kr/c": "공공데이터 활용 지원(오픈이노베이션) — 소프트웨어 개발 스타트업 대상",
        "k-startup.go.kr/d": "SVC Seoul 멤버십(확장형) — SW 기업 우대",
        "k-startup.go.kr/e": "실리콘밸리 GTM 프로그램 — AI·SaaS 기업의 미국 진출",
    }
    assert _agent_with_bodies(bodies)._topic_condition_check(PROMPT, answer, [], "job") == ""


def test_only_unconfirmed_rows_are_named() -> None:
    bodies = {"k-startup.go.kr/a": "팁스(TIPS) 창업기업 지원계획 — 지원 분야: 인공지능"}
    note = _agent_with_bodies(bodies)._topic_condition_check(PROMPT, ANSWER, [], "job")
    assert "5개 중 4개" in note and "팁스" not in note
    assert "전용 항목은" not in note


def test_no_condition_no_note() -> None:
    assert _agent_with_bodies({})._topic_condition_check("사람인에서 회계 공고 3개 찾아줘", ANSWER, [], "job") == ""


def test_operating_prompts_that_misread_before() -> None:
    """운영 요청 2,852개 역검증에서 나온 것(10-03)."""
    assert [term for term, _ in topic_conditions("위시켓에서 AI 에이전트 관련 프로젝트 3개의 제목과 예산을 알려줘")] == ["AI 에이전트"]
    assert topic_conditions("오늘자 뉴스 한 3, 4개 정도 분야별로 조사해서 말해줘") == []
    assert [term for term, _ in topic_conditions("지금 모집 중인 AI 분야 공고 3개")] == ["AI"]
    assert [term for term, _ in topic_conditions("블록체인 관련 프로젝트 2개")] == ["블록체인"]
    # 두 낱말 조건은 어느 낱말이든 있으면 근거다.
    same = dict(topic_conditions("위시켓에서 AI 에이전트 관련 프로젝트 3개"))["AI 에이전트"]
    assert mentions_topic("LLM 기반 상담 챗봇 개발", same) and mentions_topic("에이전트 구축", same)
