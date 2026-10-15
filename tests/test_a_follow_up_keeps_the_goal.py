"""이어지는 지시가 **앞 판의 목표를 물려받는다.**

★ 2026-09-02 라이브. 두 판이 이렇게 났다:

    01:03  "…공고 추천해서 조사해줘…"
           사람인 직행 → 사이트내검색 253건 → 상세 1건      5걸음 107초
    01:05  "어엉 너가 제안한대로 전부다 진행해줘"
           요구 0개 · 네이버 검색 → 네이버 카페(마감 지난 공고) → 구글 검색 → …
                                                          15걸음 186초

앞 판이 사람인에서 253건을 이미 찾아 놨는데 두 번째 판이 그걸 버리고 검색엔진부터
다시 갔다. 「제안한대로」에는 사이트도 개수도 조건도 없으니 계획 층이 눈을 감았다.
사용자님이 본 **삽질**의 정체다.

⚠ 물려주는 것은 **무엇을 시켰는가**뿐이다. 검색 **순위**는 안 물려준다 — 그건
세운 사이트의 것이고, 판을 넘기면 딴 사이트 목록 앞에서 엉뚱한 것을 연다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import extract, is_continuation, planning_prompt

FIRST = (
    "자비스 구글 드라이브에서 나래이 이력서를 읽고 오늘자로 지원 가능한 공고를 "
    "1순위부터 5순위까지 사람인에서 조사해줘"
)
HISTORY = [
    {"role": "user", "content": FIRST},
    {"role": "assistant", "content": "5순위까지 목록을 확보했습니다."},
]


def _kinds(prompt: str, history=None) -> dict[str, object]:
    text = planning_prompt(prompt, history)
    return {req.kind: req.target for req in extract(text, has_named_source=True)}


def test_a_bare_follow_up_inherits_the_site_and_the_count() -> None:
    """이게 라이브에서 통째로 사라졌던 것이다."""
    got = _kinds("어엉 너가 제안한대로 전부다 진행해줘", HISTORY)

    assert got.get("count") == 5, "5순위까지 시킨 것을 잃었다"
    assert "site" in got, "사람인을 잃어 검색엔진부터 다시 간다"
    assert "saramin.co.kr" in got["site"]


@pytest.mark.parametrize(
    "prompt",
    ["ㅇㅇ 진행해줘", "그대로 해줘", "이어서 해줘", "계속해", "너가 말한 대로 해줘", "나머지도 해줘"],
)
def test_the_usual_ways_of_saying_go_on(prompt: str) -> None:
    assert is_continuation(prompt) is True
    assert _kinds(prompt, HISTORY).get("count") == 5


def test_a_new_instruction_does_not_inherit() -> None:
    """새 지시는 앞 말을 끌고 오면 안 된다 — 시키지도 않은 것을 요구로 세운다."""
    got = _kinds("그러면 이번엔 크몽에서 3개 찾아줘", HISTORY)

    assert got.get("count") == 3
    assert "kmong.com" in got["site"]
    assert "saramin.co.kr" not in str(got.get("site"))


def test_a_long_sentence_is_never_a_continuation() -> None:
    """길면 그 안에 할 말이 이미 다 들어 있다."""
    long_ask = (
        "그대로 진행하되 이번에는 잡코리아에서 정규직만 골라서 상위 4개를 "
        "열어 읽고 표로 정리해줘 그리고 마감일도 같이 적어줘"
    )
    assert is_continuation(long_ask) is False


def test_without_history_it_returns_the_prompt_untouched() -> None:
    """없는 맥락을 지어내지 않는다."""
    assert planning_prompt("제안한대로 해줘", []) == "제안한대로 해줘"
    assert planning_prompt("제안한대로 해줘", None) == "제안한대로 해줘"


def test_it_walks_back_past_another_bare_follow_up() -> None:
    """「응」 다음의 「진행해줘」도 목표까지 닿아야 한다."""
    history = [
        {"role": "user", "content": FIRST},
        {"role": "assistant", "content": "목록을 확보했습니다."},
        {"role": "user", "content": "ㅇㅇ"},
        {"role": "assistant", "content": "진행할까요?"},
    ]

    assert _kinds("진행해줘", history).get("count") == 5


def test_the_run_computes_it_before_anything_uses_it() -> None:
    """★ 정의가 쓰는 자리보다 **앞**이어야 한다.

    처음 배선했을 때 `plan_text` 를 쓰는 체크포인트가 정의보다 200줄 앞에 있어
    승인 대기에서 NameError 로 죽을 자리였다. 순서를 검사로 박는다.
    """
    import inspect

    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent.run)
    define = source.index("plan_text = planning_prompt")
    for use in ("plan_prompt=plan_text", "extract_plan(\n            plan_text"):
        if use in source:
            assert source.index(use) > define, f"{use} 가 정의보다 앞에 있다"
