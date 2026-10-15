"""반박 답이 앞 답을 덮으면 앞 답을 되살린다 (2026-10-03 Online-Mind2Web B 판 Rotten Tomatoes).

모델이 목록을 답했는데 대조표가 헛되받자 「목록은 위에 있다」고 반박했고, 하네스는 마지막 말만 가져가 목록이 사라졌다.
"""

from __future__ import annotations

from alture_jarvis.agent import _POINTS_BACK, _restore_pointed_back_answer

# 실제 판(c2bd20c5) 마지막 답 그대로.
REBUTTAL = (
    "The task is complete — no further action needed.\n\n"
    "To confirm I met the requirement: I didn't rely on a search engine. I went straight to Rotten Tomatoes' own browse page "
    "and applied the site's **sort filter** — the \"SORT: MOST POPULAR\" chip is active (visible in the snapshot and confirmed "
    "by the sort menu showing \"Most popular\" selected). The list I gave you comes from that filtered page, not from search results.\n\n"
    "The **Most Popular TV** list is shown above, sourced from:\n"
    "[rottentomatoes.com/browse/tv_series_browse/sort:popular](https://www.rottentomatoes.com/browse/tv_series_browse/sort:popular)"
)
LIST_ANSWER = "Here are the Most Popular TV shows on Rotten Tomatoes right now:\n\n" + "\n".join(
    f"{i}. Show number {i} — Tomatometer {80 + i}% · Popcornmeter {70 + i}%" for i in range(1, 31)
) + "\n\nSource: https://www.rottentomatoes.com/browse/tv_series_browse/sort:popular"


def test_the_rotten_tomatoes_rebuttal_gets_the_list_back() -> None:
    assert _restore_pointed_back_answer(REBUTTAL, [LIST_ANSWER, REBUTTAL]) == LIST_ANSWER


def test_korean_back_references_count() -> None:
    korean = "앞서 정리해 드린 목록이 사이트의 인기순 정렬에서 나온 것입니다. 필터를 썼습니다."
    earlier = "인기 TV 목록입니다:\n" + "\n".join(f"{i}. 작품 {i} — 평점 {80 + i}%" for i in range(1, 30))
    assert _restore_pointed_back_answer(korean, [earlier, korean]) == earlier
    assert _POINTS_BACK.search("기술 분석은 앞서 드린 답변과 동일합니다")


def test_not_caught_user_words_or_self_references() -> None:
    # 운영 답 역검증에서 넓은 그물이 잡았던 것들 — 앞 답을 가리키는 말이 아니다(10-03).
    for text in ("사용자님이 앞서 말씀해주신 핵심 기술들을", "이전에 말씀하신 학원 이름은 로보메타핏입니다",
                 "위 표에 적힌 마감일은 화면에서 읽은 그대로입니다", "the ones in the table above are closest"):
        assert not _POINTS_BACK.search(text), text


def test_an_answer_that_corrects_the_earlier_one_is_never_reverted() -> None:
    # 「이전 답변에서 잘못 말씀드렸다」 — 되살리면 틀린 앞 답으로 돌아간다.
    wrong_before = "블로그 글을 임시저장했습니다. " * 30
    for fix in ("죄송합니다. 앞서 드린 답변과 달리 실제로는 임시저장이 되지 않았습니다.",
                "I apologize — the list is shown above but two entries were wrong; corrected: ..."):
        assert _restore_pointed_back_answer(fix, [wrong_before, fix]) == ""


def test_skips_earlier_answers_that_also_point_back_or_only_promise() -> None:
    second_rebuttal = "As I said, the list above is from the sorted page."
    promise = "Let me open the sorted page and check the list again."
    got = _restore_pointed_back_answer(REBUTTAL, [LIST_ANSWER, second_rebuttal, promise, REBUTTAL])
    assert got == LIST_ANSWER


def test_leaves_a_normal_final_answer_alone() -> None:
    # 앞을 가리키지 않으면 그대로 — 고친 답이 더 짧아도 앞 초안으로 돌아가지 않는다.
    short_fix = "Corrected: the top show is Show 2, not Show 1. Source: https://www.rottentomatoes.com/"
    assert _restore_pointed_back_answer(short_fix, [LIST_ANSWER, short_fix]) == ""
    # 앞을 가리켜도 앞 답이 실속 없으면(짧으면) 그대로.
    assert _restore_pointed_back_answer(REBUTTAL, ["Working on it.", REBUTTAL]) == ""
    # 긴 답이 자기 안의 표를 「위 표처럼」 가리키는 것은 앞 답이 더 길지 않으면 그대로.
    long_self = LIST_ANSWER + "\n\nAs the list above shows, dramas lead."
    assert _restore_pointed_back_answer(long_self, [LIST_ANSWER, long_self]) == ""
    assert _restore_pointed_back_answer("", [LIST_ANSWER]) == ""
