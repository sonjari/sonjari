"""요청 동사에 바로 붙은 개수가 요구다 (2026-10-04 새벽 레딧 판 df35948f·33cac79a·93f08e95).

    「한 번에 두 개 이상 작업을 걸면 느려지는 문제를 … 실사용 글 5개를 찾아줘」

`이상` 이 붙은 2 가 이겨 계획이 「2개 이상 직접 열어 읽기」가 됐다. 둘을 읽자 「더 진전 없음」으로 산출물 차례가 일찍 와서,
다섯째 글을 읽는 걸음이 거절되고 엑셀 없이 끝났다. 조건절의 개수와 요청의 개수를 가르는 것은 **요청 동사**다.

운영 요청 1,508개에 옛·새 판정을 나란히 돌려 달라지는 것은 위 세 판뿐이었다(다른 판정을 안 건드린다는 근거).
"""
from __future__ import annotations

import pytest

from alture_jarvis import plan


def _target(prompt: str) -> int:
    return plan._count_target(" ".join(prompt.split()))


@pytest.mark.parametrize("prompt, want", [
    # 오늘의 판 — 조건절의 「두 개 이상」이 아니라 「5개를 찾아줘」.
    ("레딧에서, 한 번에 두 개 이상 작업을 걸면 느려지는 문제를 사람들이 어떻게 풀었는지 실사용 글 5개를 찾아줘. 각 글을 직접 열어 읽고 엑셀로 정리해줘.", 5),
    ("후기 10개 이상인 상품 3개를 찾아줘", 3),
    ("댓글이 20개 이상 달린 글 중에서 4개만 골라 정리해줘", 4),
])
def test_the_count_tied_to_the_request_verb_wins_over_a_qualified_condition(prompt: str, want: int) -> None:
    assert _target(prompt) == want


@pytest.mark.parametrize("prompt, want", [
    # 2026-08-18: 「리뷰 0개 … 최소 6개를 뽑아줘」 — 예전 규칙이 지키던 것.
    ("리뷰 0개 신규 판매자가 올린 상품 중 최소 6개를 뽑아줘", 6),
    # 요청 동사가 둘이면 큰 쪽 — 읽어야 하는 개수다.
    ("최소 5개 이상 읽고 그중 3개를 골라줘", 5),
    # 요청 동사에 바로 붙은 것이 없으면 예전 그대로.
    ("YES24에서 파이썬 책 3권의 쪽수와 ISBN 을 조사해서 마크다운 문서로 만들어줘", 3),
    ("여수 쪽 괜찮은 국밥집 조사해서 세 군데만 알려줘", 3),
    ("적어도 4개 이상의 자료를 근거로 써줘", 4),
])
def test_what_the_old_rule_got_right_stays(prompt: str, want: int) -> None:
    assert _target(prompt) == want


def test_the_plan_asks_for_five_reads_not_two() -> None:
    prompt = (
        "레딧 r/LocalLLaMA 에서, 로컬 LLM 에이전트를 쓰면서 한 번에 두 개 이상 작업을 걸면 느려지는 문제를 사람들이 실제로 "
        "어떻게 풀었는지 실사용 글 5개를 찾아줘. 각 글을 직접 열어 읽고 엑셀 파일로 정리해줘."
    )

    labels = [req.label for req in plan.extract(prompt)]

    assert "5개 이상 직접 열어 읽기" in labels
    assert "2개 이상 직접 열어 읽기" not in labels


@pytest.mark.parametrize("prompt, want", [
    ("Find 3 products that have 10 or more reviews", 3),
    ("Find at least 6 products from sellers with 0 reviews", 6),
    ("Read at least 5 sources and pick the best 3", 5),
    ("On r/LocalLLaMA, find 5 real posts about slowdowns when running two or more tasks at once. Read each one.", 5),
])
def test_english_requests_follow_the_same_rule(prompt: str, want: int) -> None:
    """영어판도 같다 — 운영의 영어 요청 66개에 나란히 돌려 달라지는 것은 없었다."""
    assert _target(prompt) == want


# --- 걸러 내는 조건 · 만들 파일 · 「열 필요 없다」 (레딧 기준선 판 8faf3a05) ------------

_BASELINE = (
    "레딧 r/LocalLLM 게시판의 최신 글 목록(new 정렬)을 열어, 올라온 지 6시간~48시간 사이인 글 30개의 제목 · 댓글 수 · 추천 수 · "
    "올라온 뒤 지난 시간을 엑셀 파일 「레딧_LocalLLM_기준선.xlsx」로 정리해줘. 글을 하나하나 열 필요는 없고 목록에 보이는 숫자만 적어. "
    "목록에 안 보이는 숫자는 「목록에 없음」이라고 적고 지어내지 마. 마지막에 댓글 수의 가운데값과, 댓글이 7개 이상인 글이 30개 중 몇 개인지 알려줘."
)


def test_a_count_that_filters_is_not_a_request() -> None:
    """「댓글이 7개 이상**인** 글」의 7 은 대상을 꾸미는 말이다 — 손자리는 「로컬 자료 7개 읽기」를 붙들고 447초를 헤맸다."""
    assert _target("댓글이 7개 이상인 글이 30개 중 몇 개인지 알려줘") == 30
    assert _target("리뷰가 5개 이상 달린 상품을 찾아줘") == 0
    assert _target("회원이 3명 있는 팀과 4명 있는 팀을 비교해줘") == 0


def test_the_baseline_request_asks_for_thirty_rows_not_seven_local_files() -> None:
    reqs = plan.extract(_BASELINE)
    labels = [req.label for req in reqs]

    # 「열 필요 없다」고 직접 말한 과제라 이름표도 「목록으로 담기」다(같은 날 오후 — test_list_only_requests_1004).
    assert "30개 이상 목록으로 담기" in labels
    assert not any("로컬 자료" in label or "7개" in label for label in labels)
    # 사람이 「열 필요 없다」고 했다 — 목록(파일에 쓴 표)이 답이다. 서른 개를 열어 읽어야 채워지는 요구가 아니다.
    count = next(req for req in reqs if req.kind == "count")
    assert count.grounding_required is False


def test_a_file_to_make_is_not_a_local_source_but_a_file_to_read_still_is() -> None:
    made = " ".join("채용 공고 5개를 찾아 엑셀 파일 「공고.xlsx」로 정리해줘. 그중 3개는 조건도 적어줘".split())
    assert ("local", 3) not in plan._scoped_count_targets(made)
    read = " ".join("보고서 폴더의 파일 3개를 읽고 요약해줘".split())
    assert plan._scoped_count_targets(read) == [("local", 3)]


def test_do_not_open_means_the_list_is_the_answer_and_its_opposite_is_untouched() -> None:
    assert plan.wants_a_count("최신 글 25개의 제목과 댓글 수를 정리해줘. 글을 하나하나 열 필요는 없어")
    assert plan.wants_a_count("목록에 보이는 숫자만 적어줘")
    # 반대 뜻 — 읽으라는 말이다. 처음 넣은 낱말이 이걸 뒤집었다(운영 요청에 돌려 보고 뺐다).
    assert not plan.wants_a_count("최근 흐름을 조사해서 실제로 읽은 근거와 함께 분석해줘. 검색 결과 목록만 보고 답하지 마.")
