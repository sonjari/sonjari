"""「…해줘」로 끝난다 해도 **자기 완결된 요청은 앞 말을 붙이지 않는다.**

★ 2026-10-09. `_CONTINUATION` 에 `해\s*줘\s*$` 가 있어서 「…해줘」로 끝나는
  **어떤** 짧은 문장도 이어짓기로 잡혔다. 그 자체로 할 일이 다 들어 있는

      「파이썬 책 2권 추천해줘」

  같은 요청까지도, 바로 앞 사람 말(「사람인에서 공고 3개 열어 읽어줘」)이
  통째로 앞에 붙어서 계획을 뽑았다 — 3개·사람인이라는 **모르는 것**이 새 판의
  요구로 다시 살아난 것이다.

  「해줘」 꼬리만 보고 앞 말에 기대하는 것은 「진행해」·「이어서」·「그대로」
  등 진짜 지시 낱말로 충분하므로, 그 꼬리 자체를 이어짓기 신호로 쓰지 않는다.

  지켜야 할 것은 그대로다 — 「응 그렇게 해」·「이어서 해줘」·「나머지도 해줘」·
  「좋아 그걸로 진행해」처럼 **진짜로** 앞 말에 기대는 지시는 앞 요청을 물려받는다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import extract, is_continuation, planning_prompt

#: 앞 판 — 「3개」와 「사람인」이 새 요청에 다시 살아나면 안 되는 것.
PRIOR = "사람인에서 공고 3개 열어 읽어줘"
HISTORY = [
    {"role": "user", "content": PRIOR},
    {"role": "assistant", "content": "사람인 공고 3개를 열어서 읽었습니다."},
]


def _kinds(prompt: str, history: list[dict[str, str]] | None = None) -> dict[str, object]:
    text = planning_prompt(prompt, history)
    return {req.kind: req.target for req in extract(text, has_named_source=True)}


@pytest.mark.parametrize(
    "prompt",
    [
        "파이썬 책 2권 추천해줘",
        "이 함수가 왜 느린지 설명해줘",
        "이 글을 5문장으로 요약해줘",
        "10만원 이하 키보드 2개 추천해줘",
    ],
)
def test_a_self_contained_ask_is_not_a_continuation(prompt: str) -> None:
    """할 일이 자기 안에 다 있으면 「…해줘」로 끝나도 이어짓기가 아니다."""
    assert is_continuation(prompt) is False


@pytest.mark.parametrize(
    "prompt",
    [
        "파이썬 책 2권 추천해줘",
        "이 함수가 왜 느린지 설명해줘",
        "이 글을 5문장으로 요약해줘",
        "10만원 이하 키보드 2개 추천해줘",
    ],
)
def test_a_self_contained_ask_does_not_get_the_prior_glued_on(prompt: str) -> None:
    """앞 판의 말(사람인·3개)이 새 요청에 붙지 않는다."""
    assert planning_prompt(prompt, HISTORY) == prompt
    text = planning_prompt(prompt, HISTORY)
    assert PRIOR not in text
    # 붙었다면 앞 판의 요구(사람인·3개)가 다시 살아난다.
    assert "saramin.co.kr" not in str({req.kind: req.target for req in extract(text, has_named_source=True)})
    assert "3" not in str({req.kind: req.target for req in extract(text, has_named_source=True)})


@pytest.mark.parametrize(
    "prompt",
    ["응 그렇게 해", "이어서 해줘", "나머지도 해줘", "좋아 그걸로 진행해", "제안한대로 전부 진행해줘"],
)
def test_a_real_go_ahead_still_inherits_the_prior_request(prompt: str) -> None:
    """진짜로 앞 말에 기대는 지시는 그대로 앞 요청을 물려받는다."""
    assert is_continuation(prompt) is True
    joined = planning_prompt(prompt, HISTORY)
    assert joined.startswith(PRIOR)
    got = _kinds(prompt, HISTORY)
    assert got.get("count") == 3, "앞 판의 개수를 잃었다"
    assert "saramin.co.kr" in str(got.get("site")), "앞 판의 사이트를 잃었다"


def test_a_short_self_contained_ask_stays_short_even_with_history() -> None:
    """짧고 완결된 「X해줘」는 이력이 있어도 그대로 돌아간다."""
    prompt = "요청사항 정리해줘"
    assert planning_prompt(prompt, HISTORY) == prompt


# ── 덧붙임(검토하며) — **따로 선** 「해줘」는 여전히 앞 말에 기댄다 ─────────────────────────────
#
# 위까지는 손자리가 우리 숙제로 쓴 시험이다(2026-10-09 — 원인을 스스로 찾았고, 꼬리 규칙을 빼는 고침과 이 파일을 냈다).
# 그 고침은 「그렇게 해줘」·「그걸로 해줘」·「해줘」·「바로 해줘」까지 독립 요청으로 만들었다 — 기존 시험에 이 문장들이 없어
# 시험으로는 안 보이는 회귀였다. 「추천해줘」의 「해줘」는 낱말에 붙어 있고(할 일이 그 낱말이다), 「그렇게 해줘」의 「해줘」는
# 따로 서 있다(할 일이 앞 말에 있다). 따로 선 것만 이어짓기로 남긴다(`plan._BARE_DO_IT`).


@pytest.mark.parametrize(
    "prompt",
    ["그렇게 해줘", "그걸로 해줘", "해줘", "그럼 해줘", "바로 해줘", "그 방법으로 해줘", "그렇게 해 줘요", "그럼 해줘 ㅎㅎ"],
)
def test_a_bare_do_it_still_leans_on_the_prior_request(prompt: str) -> None:
    assert is_continuation(prompt) is True
    assert planning_prompt(prompt, HISTORY).startswith(PRIOR)


@pytest.mark.parametrize("prompt", ["표로 정리해줘", "한 줄로 요약해줘", "다시 설명해줘", "이 표를 엑셀로 저장해줘"])
def test_a_do_it_glued_to_its_own_verb_is_its_own_request(prompt: str) -> None:
    assert is_continuation(prompt) is False
