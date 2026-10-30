"""「목록 × ~씩」은 곱한 만큼이 할 일이다 · 흐린 장소 요구로 셈을 좁히지 않는다 (2026-10-30 · 판 391ca5ca · 6e539bf2).

「제품마다 2개씩 … 제품: (일곱)」이 「2개 이상 읽기」로 서서 예산(24)이 영상 14개 일보다 작았고, 상한 몇 걸음 전 「파일 쓸 차례」로
조사가 끊겼다. 6e539bf2(「각각 … 하나씩 · 대상: (일곱)」)는 개수 요구가 아예 없었다. 덤으로 배운 이름표 「ChatGPT → chatgpt.com」이
흐림 장소 요구가 되어 유튜브 영상 다섯을 「chatgpt.com 밖에서 5개 · 0개 읽음」으로 셌다.
운영 대조: 서로 다른 요청 2,786개 중 개수가 바뀌는 것 둘(그 두 판) · 개수 요구 판 1,142개 중 흐림 장소 고침으로 바뀌는 것 1(채움으로).
"""

from __future__ import annotations

import pytest

from alture_jarvis import plan as P

YOUTUBE = (
    "YouTube에서 아래 제품들의 공식 출시·광고·데모 영상을 제품마다 조회수 높은 순으로 2개씩 찾아, 영상마다 제목·주소·길이를 엑셀 표 하나로 "
    "정리해 줘. 제품: Claude in Chrome, Claude Cowork, ChatGPT agent(OpenAI), ChatGPT Atlas 브라우저, Perplexity Comet 브라우저, "
    "Opera Neon, Dia 브라우저(The Browser Company). 공식 채널 영상만(Anthropic · OpenAI · Perplexity · Opera · The Browser Company)."
)
EACH_ONE = (
    "AI 에이전트 제품들의 짧은 홍보 영상을 조사해 엑셀 표로 정리해 줘. 대상: Jev(jev-ultrafast 또는 Jev 에이전트), Hermes Agent(Nous Research), "
    "Manus, Genspark, ChatGPT agent(OpenAI), Perplexity Comet. 각각 공식 유튜브 · X(트위터) · 공식 사이트에서 대표 영상 하나씩 찾아서 칸: 제품, 주소."
)


def test_an_inline_list_keeps_brackets_together() -> None:
    items = P.inline_list_items(" ".join(YOUTUBE.split()))
    assert len(items) == 7 and items[2] == "ChatGPT agent(OpenAI)" and items[-1] == "Dia 브라우저(The Browser Company)"


@pytest.mark.parametrize("ask, want", [(YOUTUBE, 14), (EACH_ONE, 6)])
def test_per_item_times_the_list(ask: str, want: int) -> None:
    reqs = P.extract(" ".join(ask.split()), has_named_source=True, must_observe=True, observe_from=frozenset({"web"}), own_from=ask)
    assert [r.target for r in reqs if r.kind == "count"] == [want]


@pytest.mark.parametrize("ask, want", [
    ("사람인에서 연구비 관리 공고 3개를 열어 읽고 회사명을 알려줘", 3),                       # 목록 없음 — 그대로
    ("쿠팡에서 마우스 상위 5개를 비교해 줘. 기준: 가격, 무게, 배터리", 5),                     # 「~마다 ~씩」 없음 — 이름표 목록이 있어도 그대로
    ("각 사이트에서 2개씩 찾아 줘", 2),                                                        # 「씩」은 있지만 목록 없음
])
def test_other_counts_stay(ask: str, want: int) -> None:
    assert P._count_target(" ".join(ask.split())) == want


def test_the_product_is_capped_at_the_count_range() -> None:
    ask = "제품마다 5개씩 찾아 줘. 제품: A1, B2, C3, D4, E5, F6, G7, H8."
    assert P._count_target(ask) == 30


def test_a_soft_site_does_not_narrow_what_counts() -> None:
    """배운 이름 「ChatGPT」(흐림)가 있어도 유튜브에서 읽은 것을 센다. 확실한 장소 요구는 예전처럼 좁힌다."""
    count = P.Requirement("count", "5개 이상 직접 열어 읽기", 5, grounding_required=True)
    soft = P.Requirement("site", "ChatGPT에서 하기", ("chatgpt.com",), grade=P.GRADE_SOFT, origin="learned")
    firm = P.Requirement("site", "ChatGPT에서 하기", ("chatgpt.com",))
    sources = [f"https://www.youtube.com/watch?v={n}" for n in range(5)]
    steps = [{"tool": "browser_open", "ok": True, "evidence": {"url": url}} for url in sources]
    assert P.check([count, soft], sources=sources, steps=steps)[0][1] is True
    assert P.check([count, firm], sources=sources, steps=steps)[0][1] is False
