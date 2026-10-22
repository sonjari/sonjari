"""「직접 계산해 보기」는 **셈을 시킨 말**에서만 선다 (2026-10-19 긱뉴스 판 1b6df02d).

「…점수가 높은 순으로 10개 골라 … 점수 높은 글들의 공통점 세 가지를 적어 줘. 파일은 안 만들어도 되고 답에 표로 줘」에
「직접 계산해 보기」가 서서 판 내내 「실행 안 됨」으로 남았다. 정렬 말(「높은 순으로 골라」)이 원인이 아니었다 — 셈 대상
「점수」와 **부정된** 만드는 동사 「(안) 만들어」가 40자 안에서 짝지어졌다.

원리: 만드는 · 옮기는 동사(만들어 · 정리해 · 저장해 · 뽑아)는 **셈의 이름**(평균 · 합계 · 비율 · 확률)과 짝지을 때만 셈이다.
**값의 이름**(점수 · 등급 · 총액 · 개수 · 몇 번)은 화면 · 자료에 이미 있는 값을 옮기는 일일 수 있으니 셈 동사(계산해 · 구해 ·
얼마야 · 세어)와 짝지을 때만 셈이다. 하지 말라는 동사(「안 만들어도」)는 시킨 일이 아니다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import extract, wants_a_computation

GEEKNEWS = (
    "긱뉴스 Show GN 에서 반응이 좋았던 글의 짜임을 알고 싶어. https://news.hada.io/show 목록을 1쪽부터 10쪽까지"
    "(https://news.hada.io/show?page=2 처럼 page 를 바꿔) 넘기며 글마다 점수(P)와 댓글 수를 보고, 그중 AI · 개발 도구 · "
    "에이전트 관련 글을 점수가 높은 순으로 10개 골라 하나씩 직접 열어 읽어 줘. 글마다 표 한 줄로: 제목, 점수, 댓글 수, "
    "본문 첫 문장(그대로), 본문 길이(대략 몇 문단), 숫자나 측정 결과가 있는지, 목록(글머리표)을 썼는지, 수익 · 가격 얘기가 "
    "있는지, 댓글에서 칭찬받거나 지적받은 점 한 줄. 마지막에 점수 높은 글들의 공통점 세 가지를 적어 줘. 파일은 안 만들어도 "
    "되고 답에 표로 줘."
)


@pytest.mark.parametrize("prompt", [
    GEEKNEWS,
    # 운영 판에서 같은 꼴로 섰던 것들(값의 이름 + 만드는 동사).
    "학생 5명 점수로 엑셀 성적표 파일 하나 만들어줘. 나래 92, 가람 88, 지훈 75, 서연 95, 민수 61.",
    "거기 3행 가람 점수를 91점으로 고쳐서 roundtrip_updated.xlsx로 저장해줘.",
    "우리 사교육 데이터로 내신 2.4등급 학생이 컴퓨터공학과 갈 수 있는 대학 후보를 뽑아주고, 그 학과 졸업하면 어떤 자격증·직업으로 이어지는지도 같이 알려줘.",
    "제주도 3박4일 여행 경비 후기 블로그를 네이버에서 찾아서, 항목별로 얼마씩 썼는지 정리해줘. 블로그 3개는 직접 들어가서 읽고, 각각 총액이랑 출처 주소를 달아줘.",
    # 「산출물」은 명사다.
    "크몽에서 찾아 알려줘. 어떤 점수 통계인가 - 무엇을 주는가 (작업 기간, 산출물)",
    # 정렬 · 고르기 말은 셈이 아니다.
    "다나와에서 평점이 높은 순으로 무선마우스 5개 골라 줘",
])
def test_no_computation_requirement_without_an_arithmetic_ask(prompt: str) -> None:
    assert not wants_a_computation(prompt), prompt
    assert "sandbox_run" not in [r.target for r in extract(prompt)]


@pytest.mark.parametrize("prompt", [
    # 값의 이름이어도 셈 동사가 있으면 셈이다.
    "학생 다섯 명 점수의 합을 계산해 줘",
    "1부터 1000까지 소수가 몇 개인지 계산해서 숫자만 알려줘",
    "둘이 함께 한 권을 검토하는 데 몇 시간이 걸리는가? 숫자만 답해라.",
    "우리 데이터로 내신 2.4등급 학생이 갈 대학 후보를 뽑아주고, 명지대·성신여대 두 곳은 합격 확률도 계산해줘.",
    # 셈의 이름은 만드는 동사와도 셈이다.
    "세 반의 평균을 엑셀로 만들어줘",
    # 세는 셈.
    "비슷한 페인포인트끼리 묶은 요약 시트를 하나 더 만들어 묶음마다 몇 번 나왔는지 세어 줘.",
    "Calculate the average score of these five students",
])
def test_a_real_arithmetic_ask_keeps_it(prompt: str) -> None:
    assert wants_a_computation(prompt), prompt
    assert "sandbox_run" in [r.target for r in extract(prompt)]


def test_a_negated_make_verb_is_not_an_ask() -> None:
    assert not wants_a_computation("평균은 답에 적어 줘. 파일은 안 만들어도 돼")
    assert wants_a_computation("세 반의 평균을 엑셀로 만들어줘")
    assert not wants_a_computation("No need to make a file with the average, just tell me what the site says")


# ── 셈한 칸을 「넣어줘」 (2026-10-19 판 ac66af89 — 위 고침의 진 결과를 되살린다) ───────────────────────────────
#
# 위 고침으로 「학생 5명 점수로 엑셀 성적표 파일 만들어줘. … 평균이랑 등수도 넣어줘.」의 셈이 사라졌다(운영 5,093판 중 잃은 1).
# 「점수 + 만들어」는 값을 옮기는 짝이라 빠지는 게 맞고, 「평균 + 만들어」는 늘어놓은 칸 이름으로 읽혔다. 진짜 시킨 말은
# 「넣어줘」인데 셈 동사가 아니었다. 평균 · 등수 · 합계 · 비율 · 증감은 **계산하기 전엔 어디에도 없는 칸**이다 — 그 칸을
# 넣으라는 것은 셈이다. 값의 이름(점수 · 사진 · 이름)을 넣으라는 것은 셈이 아니다. 운영 4,898 요청 옛 · 새: 얻음 1(이 판) · 잃음 0.

ROSTER = "학생 5명 점수로 엑셀 성적표 파일 만들어줘. 나래 92, 가람 88, 지훈 75, 서연 95, 민수 61. 평균이랑 등수도 넣어줘."


@pytest.mark.parametrize("prompt", [
    ROSTER,
    "이 시트 맨 아래에 합계 행도 추가해줘",
    "월별 매출 표에 전월 대비 증감 칸을 채워줘",
    "반별 남녀 비율도 넣어 줘",
    "Add the average to the sheet as a new column",
])
def test_adding_a_computed_column_is_an_arithmetic_ask(prompt: str) -> None:
    assert wants_a_computation(prompt), prompt
    assert "sandbox_run" in [r.target for r in extract(prompt)]


@pytest.mark.parametrize("prompt", [
    "점수 칸 넣어줘",
    "시트에 이름이랑 점수 넣어줘",
    "보고서에 사진도 넣어줘",
    # 사이트에 적힌 순위를 옮기는 일 — 「순위」는 셈한 칸 이름에 안 넣었다.
    "다나와 인기 무선마우스 5개를 엑셀로 정리하고 순위도 넣어줘",
    # 하지 말라는 동사.
    "평균은 안 넣어도 돼, 점수만 옮겨 줘",
    # 셈한 칸 이름과 「넣어줘」가 다른 문장이다.
    "평균은 답에 말로만 적어 줘. 표에는 이름을 넣어줘",
    "Include the rank shown on the leaderboard page",
])
def test_adding_a_plain_column_is_not(prompt: str) -> None:
    assert not wants_a_computation(prompt), prompt
