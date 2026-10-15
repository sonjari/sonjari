"""읽은 이름을 「읽지 않고 적은 것」이라고 하지 않는다 — 따옴표 **모양**만 다를 때 (2026-10-11).

실제 판 90c19207: 레딧 프로필의 글 13편을 하나씩 열어 읽고 표로 답했는데, 답 끝에
「⚠ 읽지 않고 적은 것이 있습니다: What's the most annoying part」가 붙었다. 그 글은 실제로 열어 읽었다(걸음 기록에 주소가 있다).
페이지에는 제목이 굽은 따옴표로 적혀 있고(What’s), 모델은 곧은 따옴표로 옮겨 적었다(What's). 이름 대조가 글자 그대로라
같은 제목을 다른 이름으로 봤다. 판 전체가 「일부만 끝냄」으로 떨어졌다.

지키는 것: 따옴표 모양(' ’ ‘ ` · " “ ”)만 다른 이름은 같은 이름이다. 정말 없는 이름은 그대로 잡는다 — 이 검사의 일이다.
"""
from __future__ import annotations

import pytest

from alture_jarvis.agent import BrowserAgent

CURLY_PAGE = (
    "What’s the most annoying part of using an AI agent? : r/AI_Agents 조회 1.5K회 댓글 13 "
    "We started logging failures instead of only successful agent runs : r/AI_Agents 조회 2K회 "
    "The “Popular old GGUF” question : r/LocalLLM 조회 4.4K회"
)
STRAIGHT_PAGE = CURLY_PAGE.replace("’", "'").replace("“", '"').replace("”", '"')


def _check(answer: str, page: str) -> str:
    return BrowserAgent._listed_entity_grounding_check(
        answer, [{"role": "tool", "tool_name": "browser_extract", "content": page}]
    )


def _table(*titles: str) -> str:
    # 줄마다 읽은 글에 없는 칸(「상세 화면에서 확인」)을 하나 둔다 — 실제 판처럼. 이름이 안 맞아도 「그 줄의 칸이 전부 본 글에 있으면
    # 넘어간다」는 둘째 길이 있어서, 그 길이 통하는 표로는 이 잘못이 재현되지 않는다(처음 쓴 시험이 고치기 전에 전부 통과했다).
    rows = "\n".join(f"| {index} | {title} | r/AI_Agents | 상세 화면에서 확인 |" for index, title in enumerate(titles, 1))
    return "글을 모두 열어 확인했습니다.\n\n| # | 제목 | 커뮤니티 | 본 곳 |\n|---|---|---|---|\n" + rows + "\n"


def test_the_harness_names_table_titles_at_all() -> None:
    """이 시험들의 전제 — 표의 제목 칸이 이름으로 뽑히고, 없는 제목은 잡힌다."""
    note = _check(_table("We started logging failures instead", "Totally invented post title here"), CURLY_PAGE)

    assert "읽지 않고 적은 것" in note and "Totally invented post title here" in note
    assert "We started logging failures instead" not in note


def test_a_straight_apostrophe_matches_the_curly_one_on_the_page() -> None:
    note = _check(_table("What's the most annoying part", "We started logging failures instead"), CURLY_PAGE)

    assert note == "", note


def test_a_curly_apostrophe_matches_the_straight_one_on_the_page() -> None:
    note = _check(_table("What’s the most annoying part", "We started logging failures instead"), STRAIGHT_PAGE)

    assert note == "", note


@pytest.mark.parametrize("written", ['The "Popular old GGUF" question', "The “Popular old GGUF” question"])
def test_double_quotes_of_either_shape_match(written: str) -> None:
    for page in (CURLY_PAGE, STRAIGHT_PAGE):
        note = _check(_table(written, "We started logging failures instead"), page)
        assert note == "", (written, page[:40], note)


def test_a_title_that_was_never_read_is_still_caught_next_to_a_quoted_one() -> None:
    note = _check(_table("What's the most annoying part", "Totally invented post title here"), CURLY_PAGE)

    assert "Totally invented post title here" in note
    assert "What's the most annoying part" not in note, "따옴표 모양 때문에 읽은 제목까지 같이 걸면 안 된다"
