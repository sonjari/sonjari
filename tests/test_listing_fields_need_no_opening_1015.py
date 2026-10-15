"""달라는 칸이 **전부 목록에 보이는 칸**이면 「직접 열어 읽기」가 아니라 「목록으로 담기」다 (2026-10-15).

10-15 00:24 레딧 판(acba5f24): 「old.reddit.com/r/LLMDevs/top/?t=week 에서 이번 주 인기 글 10개 — 각각 제목 · 점수 · 댓글 수 ·
글 종류 한 단어」가 「웹 자료 10개 이상 직접 열어 읽기」가 됐다. 전부 목록 화면에 보이는 값인데, 모델은 이름표를 듣고 글을 하나씩
여덟 개 열었다(26걸음). 예전에 「표로 정리」만 보고 가르다가 「공고 3개의 자격 요건」처럼 열어야 하는 요청까지 바뀐 적이 있어서
(`says_list_only` 설명), 이번에는 낱말 하나가 아니라 **달라는 칸의 목록 전체**로 가른다:

- 「N개 — 제목 · 점수 · 댓글 수」처럼 개수 뒤에 칸을 늘어놓았고, 그 칸이 **둘 이상이며 전부 목록 칸**(제목 · 점수 · 추천 · 댓글 수 ·
  조회수 · 순위 · 날짜 · 작성자 · 주소 · 종류 · 가격)이면 목록으로 담기.
- 하나라도 목록 밖의 칸(자격 요건 · 쪽수 · ISBN · 본문 요약 · 배송비 …)이 섞이면 지금처럼 직접 열어 읽기.
- 상세를 보라는 말(본문 · 원문 · 상세)이 있으면 지금처럼 직접 열어 읽기.
"""

from __future__ import annotations

from alture_jarvis.plan import says_list_only

REDDIT = ("레딧 두 곳을 읽고 답만 해 줘(파일은 만들지 마). ① old.reddit.com/r/LLMDevs/top/?t=week 에서 이번 주 인기 글 10개 — "
          "각각 제목 · 점수 · 댓글 수 · 글 종류(질문 / 경험담 · 실패담 / 도구 소개 / 뉴스) 한 단어.")


def test_listing_fields_only_mean_no_opening() -> None:
    assert says_list_only(REDDIT)
    assert says_list_only("유튜브 인기 동영상 20개의 제목, 조회수, 올린 날짜를 표로 정리해 줘")
    assert says_list_only("멜론 차트 50위까지 순위와 제목, 가수를 알려줘")


def test_a_field_outside_the_listing_still_means_opening() -> None:
    assert not says_list_only("사람인에서 서울 마케팅 공고 3개의 회사 이름과 자격 요건을 비교표로 정리해 줘")
    assert not says_list_only("YES24에서 파이썬 책 2권의 제목과 쪽수, ISBN을 알려줘")
    assert not says_list_only("레딧 인기 글 5개의 제목과 본문 요약을 알려줘")


def test_one_field_is_not_enough_to_decide() -> None:
    assert not says_list_only("레딧 인기 글 5개를 찾아서 알려줘")
    assert not says_list_only("뉴스 기사 3개의 제목만 알려줘 그리고 각 기사의 내용을 정리해 줘")


def test_asking_for_the_detail_wins() -> None:
    assert not says_list_only("인기 글 10개 — 제목 · 점수 · 댓글 수, 그리고 각 글의 본문을 읽고 요약해 줘")
