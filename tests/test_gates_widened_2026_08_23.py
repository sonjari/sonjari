"""갈래 셋을 넓힌 것 — 각각 **양방향**으로 지킨다 (2026-08-23).

오늘 세 종목을 재 봤더니 갈래가 있는 만큼 정확하고 없는 만큼 지어냈다:

    웹 조사 (16판)    창작 0건 · 도구 100%    ← 갈래가 촘촘함
    내부 작업 (10판)  창작 7건 · 도구 30%     ← 갈래가 얇음
    순수 추론 (8판)   정답 1/8 · 도구 0%      ← 갈래가 없음

두 모델(젬마4-26B 지수 31, 퀀3.8-27B 지수 52)이 **똑같이** 무너졌다. 모델 등급이
아니라 배선의 문제였다. 여기서 지키는 것은 그 배선 셋이다.

★ 넓히기는 언제나 **양방향**으로 잰다. 새로 걸리는 것만 보면 오탐이 조용히 는다
  (2026-07-28 에 한 방향만 보고 넓혔다가 적재율이 96%→19% 로 떨어진 적이 있다).
"""

from __future__ import annotations

from alture_jarvis.plan import extract
from alture_jarvis.runtime import (
    LOCAL_INSPECTION_VERBS,
    LOCAL_PATH_PATTERN,
    LOCAL_SOURCE_PHRASES,
)
from alture_jarvis.skills import match_skill

_KNOWN = {
    "무신사": ("musinsa.com",),
    "크몽": ("kmong.com",),
    "YES24": ("yes24.com",),
    "잡코리아": ("jobkorea.co.kr",),
    "위시켓": ("wishket.com",),
}


# ═══════════════════════════════════════════════════════════════════════════
# ② 로컬 검사 — "알려줘"도 읽으라는 말이다
# ═══════════════════════════════════════════════════════════════════════════
def _local_fires(prompt: str) -> bool:
    compact = " ".join(prompt.split())
    named = bool(LOCAL_PATH_PATTERN.search(compact)) or any(
        phrase in compact for phrase in LOCAL_SOURCE_PHRASES
    )
    return named and any(verb in compact for verb in LOCAL_INSPECTION_VERBS)


def test_asking_about_a_path_opens_the_local_route() -> None:
    """경로를 또박또박 적고 물으면 읽으러 가야 한다.

    실측(2026-08-23): 아래 문장들에 두 모델 모두 **도구 0걸음**으로 답했다.
    젬마는 파일 목록을 우연히 맞혔고(안 읽고), 코드 상수는 둘 다 틀렸다 —
    우리 저장소에만 있는 값이라 읽지 않고는 알 수 없는데 지어냈다.
    """
    for prompt in (
        r"C:\work\monorepo\tools\alture-jarvis\recipes 폴더 안에 파일이 몇 개 있고 이름이 뭔지 알려줘",
        r"C:\work\monorepo\tools\alture-jarvis\src\alture_jarvis\agent.py 에서 "
        r"_TRANSCRIPT_BUDGET_CHARS 값이 얼마이고 왜 그 값인지 알려줘",
        r"C:\work\monorepo\tools\alture-jarvis\docs\인수인계_2026-08-22.ko.md 를 읽고 "
        r"「다음 사람이 할 것」에 적힌 항목을 목록으로 뽑아줘",
        "이 저장소에 테스트가 몇 개 있는지 알려줘",
        "우리 코드에서 그 함수 어디 있는지 찾아줘",
    ):
        assert _local_fires(prompt), f"경로를 대고 물었는데 안 읽으러 간다: {prompt[:48]}"


def test_the_local_route_needs_a_path_not_just_a_verb() -> None:
    """경로/출처 어구와 **짝**으로만 걸린다 — 안 그러면 온 세상이 로컬 검사가 된다."""
    for prompt in (
        "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘",   # 웹
        "중앙대 소프트웨어학부 최근 경쟁률이 어떻게 되나요?",       # 자사 DB
        "내일 일정 알려줘",
        "나래이한테 메일 보내줘",
        "오늘 기분이 어때",
        "1부터 1000까지 소수가 몇 개인지 계산해서 숫자만 알려줘",  # ★ 셈은 상자로
        "학원 상담 전화 첫 질문으로 뭐가 좋을까",
    ):
        assert not _local_fires(prompt), f"오탐: {prompt[:48]}"


# ═══════════════════════════════════════════════════════════════════════════
# ③ 스킬 — "가격 전략"도 pricing 이다
# ═══════════════════════════════════════════════════════════════════════════
def test_pricing_skill_attaches_to_the_way_people_actually_ask() -> None:
    """트리거가 "가격 책정"(붙여 쓴 두 낱말)뿐이라 "가격 전략"이 안 걸렸다."""
    for prompt in (
        "학원 수강료 가격 책정 전략을 세워줘",
        "크몽에서 가격 전략 짜줘",
    ):
        matched = match_skill(prompt)
        assert matched and matched[0] == "pricing", f"{prompt} → {matched}"


def test_skills_do_not_attach_to_unrelated_asks() -> None:
    for prompt in ("다나와에서 무선마우스 가격 알려줘", "오늘 기분이 어때", "내일 일정 알려줘"):
        assert match_skill(prompt) is None, prompt


# ═══════════════════════════════════════════════════════════════════════════
# ④ 개수 요구 — **고치려다 되돌린 자리다.** 여기 적어 두는 이유가 있다
# ═══════════════════════════════════════════════════════════════════════════
#
# 오늘(2026-08-23) 무신사 판에서 이런 걸 봤다. "상위 3개의 제품명과 가격"은
# 목록에 이미 있는데 계획 층이 "상세를 3개 열어 읽어라"로 읽는다:
#
#     퀀3.8   30걸음 · 401초 · 충족 0/1   ← 시킨 대로 상세를 열다 시간을 다 씀
#     젬마4    9걸음 · 124초 · 충족 2/2   ← 그 지시를 무시하고 목록에서 뽑음
#
# **시킨 대로 한 쪽이 지는 구조**다. 그래서 "목록에 보이는 칸만 물었으면 요구를
# 안 만든다"로 고쳤더니 **기존 검사 9개가 걸렸다.** `has_named_source` 는
# 2026-08-13 에 일부러 넣은 것이었다 — 없으면 크몽 2걸음·쿠팡 3걸음·교보문고
# 4걸음으로 일찍 멈춰 "3개 시키고 1개 받는" 판이 된다.
#
#     요구 없음 → 너무 일찍 멈춘다        (2026-08-13 에 겪음)
#     요구 있음 → 목록에 있는 걸 열어본다  (2026-08-23 에 겪음)
#
# 둘 다 진짜 병이라 한쪽을 지우는 것은 답이 아니다. 진짜 고칠 자리는
# `plan.check` 의 충족 판정 — **「연 페이지 수」가 아니라 「답에 담긴 항목 수」**
# 로 세야 한다. 그건 별도 작업으로 남긴다. 아래 검사는 **지금 동작을 못 박아**
# 다음 사람이 같은 곳을 뭉툭하게 건드리지 않게 한다.
def _labels(prompt: str) -> list[str]:
    return [r.label for r in extract(prompt, has_named_source=True, known_sites=_KNOWN)]


def test_naming_a_source_with_a_count_still_asks_for_reading() -> None:
    """2026-08-13 의 결정이 그대로 살아 있는지. 지우면 일찍 멈추는 병이 돌아온다."""
    for prompt in (
        "크몽에서 AI 에이전트 개발 서비스 3개의 제목과 가격을 알려줘",
        "무신사에서 남성 반팔티 상위 3개의 제품명과 가격을 알려줘",
    ):
        assert any("열어 읽기" in label for label in _labels(prompt)), _labels(prompt)


def test_real_reading_tasks_keep_the_count_requirement() -> None:
    for prompt in (
        "잡코리아에서 여수 회계 채용 공고 3개의 제목과 회사명을 알려줘",
        "위시켓에서 AI 챗봇 외주 공고를 찾아서 최소 4개는 직접 열어 읽고 표로 정리해줘",
        "사람인에서 정규직 공고 3개를 골라서 본문을 읽고 요약해줘",
    ):
        assert any("열어 읽기" in label for label in _labels(prompt)), _labels(prompt)
