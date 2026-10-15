"""「주제 다섯 · **주제마다** 글 2개」는 2개가 아니라 10개다 (2026-10-15).

10-15 13:10 맡긴 레딧 조사(a92acbe8): 「아래 다섯 주제를 각각 검색해 … ① … ⑤ …, 주제마다 댓글이 가장 많은 글 2개를 골라 열고」가
「웹 자료 2개 이상 직접 열어 읽기」가 됐다. 첫 주제의 글 두 개를 읽자 「시킨 것 2/2」가 되어 손자리는 정리로 넘어갔고,
②~⑤는 「검색도 시작하지 못했다」고 스스로 밝혔다.

지키는 약속(`plan._count_target`):
- 고른 개수 바로 앞에 「○○마다」가 있고, 요청에 묶음의 수가 드러나 있으면(①②③… 의 개수 · 「다섯 주제」 · 「세 사이트」) 개수 × 묶음 수.
- 묶음의 수를 모르면 지금처럼 그 개수 그대로.
- 「마다」가 없으면 지금 그대로(「인기 글 10개 — 각각 제목 · 점수」는 10).
"""

from __future__ import annotations

from alture_jarvis.plan import _count_target

TOPICS = ("레딧 r/ollama 에서 아래 다섯 주제를 각각 검색해, 주제마다 댓글이 가장 많은 글 2개를 골라 그 글을 열고 댓글을 읽어 줘. "
          "주제와 검색어: ① 컨텍스트 크기 ② 메모리 부족 ③ 모델이 서로 밀어냄 ④ 작은 그래픽카드 ⑤ 모델 설정 기본값.")


def test_a_count_per_topic_is_multiplied_by_the_circled_topics() -> None:
    assert _count_target(TOPICS) == 10


def test_a_count_per_site_with_the_number_of_sites_spelled_out() -> None:
    assert _count_target("세 사이트에서 각각 찾아서, 사이트마다 후기 3개씩 읽고 정리해 줘") == 9


def test_without_the_number_of_groups_the_count_stays() -> None:
    assert _count_target("주제마다 글 2개를 찾아서 알려줘") == 2


def test_without_per_group_the_count_stays() -> None:
    assert _count_target("이번 주 인기 글 10개 — 각각 제목 · 점수 · 댓글 수를 알려줘") == 10


def test_the_plan_with_a_named_site_address_counts_every_group_too() -> None:
    """주소(www.reddit.com/…)를 댄 요청은 범위별 개수(`_scoped_count_targets`) 길로 간다 — 실제 판 b55c8113 이 그 길에서 2개였다."""
    from alture_jarvis.plan import extract

    prompt = ("레딧 r/ollama 에서 아래 다섯 주제를 각각 검색해(www.reddit.com/r/ollama/search/?q=검색어&sort=comments&t=year), "
              "주제마다 댓글이 가장 많은 글 2개를 골라 그 글을 열고 댓글을 읽어 줘. 답만 해 줘(파일은 만들지 마). "
              "주제와 검색어: ① 컨텍스트 크기 — num_ctx ② 메모리 부족 — out of memory RAM ③ 모델이 서로 밀어냄 — unload model "
              "④ 작은 그래픽카드 — 8GB VRAM ⑤ 모델 설정 기본값 — presence_penalty.")
    counts = [req.target for req in extract(prompt) if req.kind == "count"]
    assert counts == [10]
