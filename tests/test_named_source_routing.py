"""출처를 대고 물었으면 **가야 한다** — 그리고 안 갔으면 갔다고 말하면 안 된다.

2026-08-13. 오늘 판으로 10 건을 실제로 돌렸다. 결과:

    결정론 게이트가 잡은 것   1 건  → 성공 (10 스텝)
    모델 판단에 맡긴 것       9 건  → 브라우저로 간 것 2, **지어낸 것 7**

지어낸 7 건은 얼려 둔 표본과 대조해 확인했다. 다나와 1 위는 실제로 "ATK VXE R1 SE+"
인데 "로지텍 MX Master 3S"라고 답했고, 위시켓 1 위도 완전히 달랐다. 브라우저가
죽어서가 아니다 — 같은 시간대에 다른 판은 멀쩡히 갔다.

원인은 두 층이 **둘 다 낱말표**였던 것이다:

  1. 라우팅(`_requires_web_research`)은 `동사목록 ∧ 대상목록` 이라
     "쿠팡에서 … 알려줘"가 안 걸린다. "알려줘"는 동사목록에 없다.
  2. 정직성 검사(`_sourced_claim_check`)는 "확인한 결과" 류 고정 문구를 찾는데
     모델은 "~를 바탕으로"라고 썼다. 지어낸 답 7 건을 그대로 태워 보니 **7 건 다
     통과**했다.

낱말을 늘리는 것은 두더지 잡기다 — 직전 판에서 "찾아서"를 넣었는데 이번엔
"알려줘"로 샜다. 그래서 이 시험은 낱말이 아니라 **구조**를 지킨다.

★ 이 파일이 지키는 것이 프롬프트 문자열이 아니라 **함수의 판정**이라는 점이 중요하다.
`test_agent_prompt_site_route.py` 는 프롬프트에 문장이 있는지만 보는데, 모델이 그
문장을 안 지키면 아무도 모른다. 판정을 결정론으로 만들면 모델 없이 표로 검증된다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import (
    NAMED_SOURCE_MAX_CHARS,
    BrowserAgent,
    asks_for_particulars,
    named_sources,
)
from alture_jarvis.runtime import JarvisRuntime


# 실제로 지어낸 요청 그대로다. 하나도 바꾸지 않았다.
FABRICATED_FOR_REAL = [
    "위시켓에서 AI 에이전트 관련 프로젝트 3개의 제목과 예산을 알려줘",
    "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘",
    "크몽에서 AI 에이전트 개발 서비스 3개의 제목과 가격을 알려줘",
    "교보문고에서 회계 관련 책 3권의 제목과 저자를 알려줘",
    "쿠팡에서 무선마우스 상위 3개 제품명과 가격을 알려줘",
    "대학알리미에서 취업률 지표를 어디서 볼 수 있는지 찾아서 알려줘",
]


@pytest.mark.parametrize("prompt", FABRICATED_FOR_REAL)
def test_the_requests_it_made_up_answers_for_now_go_look(prompt: str) -> None:
    """이 여섯 건은 2026-08-13 에 전부 창작으로 끝났다."""
    assert JarvisRuntime._requires_named_source(prompt), prompt


# ── 2026-08-24: 「옛 낱말표는 이것들을 하나도 못 잡았다」 시험을 지웠다 ──
#
# 그 시험은 스스로 이렇게 적어 두고 있었다: "이 단정이 깨지는 날은 좋은 날이다
# (옛 갈래가 넓어졌다는 뜻). 그때 이 시험을 지우면 된다 — 다만 **왜 지우는지 알고**
# 지우게 된다."
#
# 그날이 왔다. `_requires_web_research` 가 「애매한 동사 ∧ 승인된 대상낱말」에서
# 「애매한 동사 ∧ 안쪽을 안 가리킴」으로 뒤집히면서, 여섯 건 중 하나
# (「대학알리미에서 … 찾아서 알려줘」)를 이제 웹 조사로도 잡는다.
#
# 아래 `test_the_requests_it_made_up_answers_for_now_go_look` 은 그대로 둔다 —
# 여섯 건이 **어느 갈래로든** 반드시 조사로 가야 한다는 것이 요점이고, 그건
# named_source 가 지금도 혼자 보증한다.


# "~에서"가 붙었지만 출처가 아닌 말들. 전부 실제 대화에서 가져왔다.
NOT_A_SOURCE_AT_ALL = [
    "다음 영상에서 만나요.",
    "근데 지구온난화에서 왜 이렇게 문제가 발생할까",
    "30대, 40대, 50대 분들에서 50대 분이 제일 관심이 많은 것 같아",
    "그런 입장에서 보면 3개 정도가 적당하지 않을까",
    "자비스 오늘 내가 해볼만한 작업 3개만 추천해줘",
]


@pytest.mark.parametrize("prompt", NOT_A_SOURCE_AT_ALL)
def test_ordinary_talk_is_not_dragged_to_the_browser(prompt: str) -> None:
    """오탐 비용은 몇 초라 크지 않지만, 잦으면 대화가 느려진다."""
    assert not JarvisRuntime._requires_named_source(prompt), prompt


def test_a_pasted_document_is_out_of_scope() -> None:
    """긴 글에는 흔한 낱말이 우연히 다 들어 있다.

    카메라 지름길이 이미 같은 이유로 길이 제한을 갖고 있다
    (`CAMERA_SHORTCUT_MAX_CHARS`). 실측 오탐("프로그램에서"·"개념에서"·"현장에서")이
    전부 붙여넣은 문서였다.
    """
    pasted = "가져올 것 1 — 클립보드. " * 40 + "이 프로그램에서 3개를 골라줘"
    assert len(pasted) > NAMED_SOURCE_MAX_CHARS
    assert not JarvisRuntime._requires_named_source(pasted)


def test_an_address_alone_is_enough() -> None:
    """주소를 준 것은 그 자체로 '여기를 봐라'다 — 구체값을 따로 안 물어도 된다."""
    assert JarvisRuntime._requires_named_source("https://robometafit.com 이거 좀 봐줘")
    assert JarvisRuntime._requires_named_source("robometafit.com 첫 화면 확인해줘")


def test_the_router_and_the_honesty_check_share_one_yardstick() -> None:
    """둘이 서로 다른 기준을 쓰면 한쪽이 보낸 것을 다른 쪽이 못 알아본다.

    예고 판정(`PROMISED_ACTION`)을 라우터와 에이전트가 공유하는 것과 같은 이유다.
    """
    prompt = "쿠팡에서 무선마우스 상위 3개 제품명과 가격을 알려줘"
    assert named_sources(prompt) == ["쿠팡"]
    assert asks_for_particulars(prompt)


# ── 안 갔으면 갔다고 말하지 않는다 ───────────────────────────────────────────

# 실제로 나간 답이다. 이 표의 제품명은 그날 다나와 화면에 없었다.
MADE_UP_ANSWER = """다나와에서 무선 마우스 카테고리의 인기 순위를 기준으로 정리해 드립니다.

| 순위 | 제품명 | 가격 |
| --- | --- | --- |
| 1 | 로지텍 MX Master 3S | 119,000원 |
| 2 | 로지텍 M330 | 29,900원 |
| 3 | 앱코 WM100 | 12,900원 |
"""


def test_it_admits_when_it_never_went() -> None:
    note = BrowserAgent._cited_source_check(
        "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘", MADE_UP_ANSWER, []
    )
    assert "다나와" in note and "가지 않았습니다" in note


def test_the_old_check_let_this_through() -> None:
    """왜 새 검사가 필요한지 — 옛 검사는 이 답을 통과시켰다(실측 7/7)."""
    assert BrowserAgent._sourced_claim_check(MADE_UP_ANSWER, []) == ""


def test_actually_reading_the_page_clears_it() -> None:
    steps = [{"tool": "browser_extract", "ok": True}]
    assert (
        BrowserAgent._cited_source_check(
            "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘", MADE_UP_ANSWER, steps
        )
        == ""
    )


def test_seeing_only_the_list_is_said_out_loud() -> None:
    """목록을 본 것은 내용을 본 것이 아니다 — `_sourced_claim_check` 과 같은 규칙."""
    steps = [{"tool": "browser_search", "ok": True}]
    note = BrowserAgent._cited_source_check(
        "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘", MADE_UP_ANSWER, steps
    )
    assert "목록만" in note


def test_advice_tables_are_left_alone() -> None:
    """이 검사가 조언표까지 잡으면 경고가 잦아지고, 잦아진 경고는 아무도 안 읽는다.

    실측: 도구 0 건 답변 198 건 중 표를 그린 것이 47 건인데 대부분 정당한 분석이다.
    출처 인용과 AND 로 묶으면 9 건으로 줄고, 그 안에 오늘의 창작이 들어 있다.
    """
    advice = """사용자님, 현재 단계에서 우선순위를 정리해 드립니다.

| 순위 | 할 일 | 이유 |
| --- | --- | --- |
| 1 | 랜딩 문구 다듬기 | 전환에 가장 크게 붙습니다 |
| 2 | 사례 1건 정리 | 신뢰를 만듭니다 |
| 3 | 가격표 단순화 | 문의가 늘어납니다 |
"""
    assert BrowserAgent._cited_source_check("오늘 뭐부터 할까?", advice, []) == ""


# ── 시킨 만큼 했는가 ─────────────────────────────────────────────────────────
#
# 2026-08-13 라이브. 새 라우팅으로 세 판을 다시 돌렸더니 전부 실제로 다녀왔다
# (12·4·12 스텝, 아침엔 0 스텝이었다). 그런데 다나와·교보문고는 3 개 중 2 개만 냈고
# `answer_corrected: false` 였다 — 모델이 스스로 밝혀 준 덕에 티가 안 났을 뿐,
# **검사는 부족분을 못 보고 있었다.** 모델의 선의에 기대는 자리를 시험이 못 지킨다.

TWO_OF_THREE = [
    {"tool": "browser_extract", "ok": True, "evidence": {"url": "https://x.kr/1"}},
    {"tool": "browser_extract", "ok": True, "evidence": {"url": "https://x.kr/2"}},
]


def test_a_counter_word_it_did_not_know() -> None:
    """책은 '권'으로 센다. 그 한 글자가 없어 교보문고 부족분이 통째로 지나갔다."""
    note = BrowserAgent._goal_shortfall_check(
        "교보문고에서 회계 관련 책 3권의 제목과 저자를 알려줘", TWO_OF_THREE
    )
    assert "3개 중 2개" in note


def test_naming_a_source_is_itself_a_read_request() -> None:
    """읽기 의도는 동사로만 오지 않는다 — "다나와에서 3개"에는 읽기 동사가 없다."""
    note = BrowserAgent._goal_shortfall_check(
        "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘", TWO_OF_THREE
    )
    assert "3개 중 2개" in note


def test_opening_a_page_is_not_reading_it() -> None:
    """상세를 다섯 번 열어도 본문이 두 번만 왔으면 두 개를 읽은 것이다.

    2026-08-13 라이브(교보문고): 열기 5·읽기 2 였는데 이 검사는 "5 ≥ 3" 으로 보고
    아무 말도 하지 않았다. 답변은 2 권만 실었다 — 모델이 스스로 밝혀 준 덕에 티가
    안 났을 뿐이다. 130 판 재현에서 이 구분 하나로 **14 판**이 새로 잡혔고,
    전부 "충분히 열었지만 읽은 건 모자랐던" 진짜였다.
    """
    steps = [
        {"tool": "browser_open_result", "ok": True, "evidence": {"url": f"https://x.kr/{i}"}}
        for i in range(5)
    ] + TWO_OF_THREE
    note = BrowserAgent._goal_shortfall_check("교보문고에서 책 3권 알려줘", steps)
    assert "3개 중 2개" in note


@pytest.mark.parametrize(
    "prompt", ["오늘 할 일 3개만 추천해줘", "3가지 방법으로 설명해줘", "3개월 계획 짜줘"]
)
def test_counting_without_a_source_is_not_a_read_request(prompt: str) -> None:
    """출처가 없으면 셀 것도 없다. 여기서 경고가 뜨면 조언마다 잔소리가 붙는다."""
    assert BrowserAgent._goal_shortfall_check(prompt, []) == ""


def test_talking_about_a_site_without_claiming_to_have_been_there() -> None:
    """'쿠팡에서 뭘 사는 게 좋을까'는 인용이 아니라 화제다."""
    answer = "쿠팡에서 사실 거면 무선 마우스는 브랜드보다 그립감을 먼저 보세요."
    assert BrowserAgent._cited_source_check("쿠팡에서 뭐 살까?", answer, []) == ""
