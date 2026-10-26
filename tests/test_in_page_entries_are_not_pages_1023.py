"""한 페이지 안의 항목(댓글 · 답글)을 센 개수는 **열 페이지 수가 아니다** (2026-10-23).

★ 판 62555a75(MCP · 클로드 코드가 맡김): 「이 레딧 글을 열어서 읽고 정리해 줘: <주소> — 본문을 빠짐없이 요약 …, 그리고
  추천이 많은 댓글 위에서부터 10개를 「누가 · 무슨 말 · 추천 수」로」가 「10개 이상 직접 열어 읽기」가 됐다(saw 「3개 읽음」).
  글 하나면 끝날 일에 다른 페이지를 열며 8분 넘게 헤맸고 사람이 취소했다.

지키는 약속(`plan._counts_entries_inside_a_page` · `quantities.lives_inside_a_page`):
  - 세는 낱말이 페이지 속 항목이면 「N개 이상 목록으로 담기」 — 답에 N개를 담았는지는 계속 센다(요구를 지우지 않는다).
  - 세는 낱말이 글 · 기사 · 후기처럼 한 장씩 여는 것이면 예전처럼 「직접 열어 읽기」.
  - 「댓글」의 역할(작업계약이 쓰는 input)은 그대로다 — 갈린 것은 「몇 번 여는가」뿐이다.

운영 요청 5,111개에 옛 · 새를 나란히 돌린 결과 바뀐 것은 이 판 하나였다(옛 판정 「직접 열어 읽기」 482개 중 내려간 것 0).
"""

from __future__ import annotations

import pytest

from alture_jarvis import plan
from alture_jarvis.quantities import ROLE_INPUT, lives_inside_a_page, quantity_role


_REDDIT_62555A75 = (
    "이 레딧 글을 열어서 읽고 정리해 줘: "
    "https://www.reddit.com/r/LocalLLM/comments/1xclfjf/i_made_my_local_llm_start_thinking_while_im_still/ — "
    "본문을 빠짐없이 요약(무엇을 만들었는지, 어떻게 동작하는지, 적어 둔 한계, 영상이나 링크가 있는지), 올라온 시각, "
    "추천 점수, 댓글 수, 그리고 추천이 많은 댓글 위에서부터 10개를 「누가 · 무슨 말 · 추천 수」로. "
    "파일은 만들지 말고 답으로만 줘.\n\n"
    "(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요: "
    "본문 요약 · 한계 · 영상 · 추천 점수 · 댓글 수 · 댓글)"
)


def _counts(prompt: str):
    return [req for req in plan.extract(prompt) if req.kind == "count"]


def test_the_reddit_run_asks_for_ten_comments_in_the_answer_not_ten_pages() -> None:
    (count,) = _counts(_REDDIT_62555A75)
    assert count.target == 10
    assert count.label == "10개 이상 목록으로 담기"
    assert count.list_only is True
    assert count.grounding_required is False
    assert "직접 열어 읽기" not in count.label


@pytest.mark.parametrize(
    "prompt",
    [
        "이 글의 답글 7개를 작성자와 함께 정리해 줘: https://news.hada.io/topic?id=35636",
        "Open https://www.reddit.com/r/LocalLLM/comments/1xclfjf/x/ and summarize the post "
        "and the top 10 comments with author and score.",
    ],
)
def test_other_in_page_entries_are_listed_too(prompt: str) -> None:
    (count,) = _counts(prompt)
    assert count.list_only is True
    assert "직접 열어 읽기" not in count.label


@pytest.mark.parametrize(
    ("prompt", "target"),
    [
        # 댓글은 **거르는 말**이고 세는 것은 글이다 — 한 장씩 연다.
        ("레딧 r/LocalLLM 에서 댓글 많은 글 5개를 열어 읽고 정리해 줘", 5),
        ("레딧 r/LocalLLM 에서 댓글이 10개 이상인 글 5개를 찾아 읽어 줘", 5),
        # 후기는 글 한 편일 수 있다 — 낱말만으로 못 가르니 예전대로 연다.
        ("네이버 블로그에서 성수동 카페 후기 5개를 찾아 읽어 줘", 5),
        ("Find 5 posts on reddit.com about local LLMs with many comments and read them.", 5),
    ],
)
def test_pages_are_still_opened_one_by_one(prompt: str, target: int) -> None:
    (count,) = _counts(prompt)
    assert count.target == target
    assert count.list_only is False
    assert count.label.endswith("직접 열어 읽기")


def test_what_is_counted_is_decided_in_one_place() -> None:
    assert lives_inside_a_page("댓글") and lives_inside_a_page("답글") and lives_inside_a_page("comments")
    assert not lives_inside_a_page("글")
    assert not lives_inside_a_page("후기")
    assert not lives_inside_a_page("")
    # 작업계약이 쓰는 역할은 그대로 — 댓글은 여전히 「읽을 것」이다.
    assert quantity_role("개", "댓글", "") == ROLE_INPUT
