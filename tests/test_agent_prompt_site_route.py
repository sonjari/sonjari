"""작업 순서가 프롬프트에 **박혀 있었다** — 그래서 새 도구가 낄 자리가 없었다.

2026-08-12. `browser_site_search` 를 만들고 그 자리에서 알려 주기까지 했는데도
자비스는 계속 네이버에 "여수 순천 광양 회계 경리 채용 사람인 잡코리아" 를 쳤다.
6차 실측에서 16스텝 중 7번이 네이버 검색이었다.

원인은 모델이 아니라 프롬프트였다:

    - 순서는 이것 하나다:
        browser_search → browser_open_result(rank) → browser_extract → (부족하면 다음 rank)

**"이것 하나다"** 라고 못 박아 놨으니 다른 길이 있어도 안 간다. 도구를 아무리
만들어도 순서에 없으면 안 불린다 — 오늘 세 번째로 확인한 모양이다
(드라이브 읽기 없음 → 사이트 검색 없음 → 있어도 순서에 없음).

여기서 지키는 것 넷:

  1. 그 서비스의 목록이 필요할 때의 순서가 프롬프트에 있다
  2. 검색어에 사이트 이름을 끼워 넣지 말라고 못 박는다
  3. 주소를 조립해 직행하지 말라고 못 박는다
  4. 낡은 지식(쿠팡은 안 된다)이 남아 모델을 잘못 이끌지 않는다
"""

from __future__ import annotations

from alture_jarvis.agent import AGENT_SYSTEM_PROMPT


def test_the_in_site_route_is_in_the_prompt() -> None:
    assert "browser_site_search" in AGENT_SYSTEM_PROMPT, (
        "도구를 만들어도 순서에 없으면 안 불린다"
    )
    assert "browser_load_more" in AGENT_SYSTEM_PROMPT


def test_the_one_and_only_order_no_longer_blocks_other_routes() -> None:
    assert "순서는 이것 하나다" not in AGENT_SYSTEM_PROMPT, (
        "다른 길을 막는 문장이 남아 있다"
    )


def test_it_forbids_stuffing_site_names_into_the_query() -> None:
    """실측된 실패 문장 그대로다: '…채용 사람인 잡코리아'."""
    assert "사이트 이름을 끼워 넣지 마라" in AGENT_SYSTEM_PROMPT


def test_it_forbids_hand_built_search_urls() -> None:
    assert "주소를 조립해서 직행하지 마라" in AGENT_SYSTEM_PROMPT


def test_it_says_to_read_details_not_list_labels() -> None:
    """목록의 직군 이름을 직무로 옮겨 적어 '전산설계사무'가 나갔다."""
    assert "상세 화면의 원문" in AGENT_SYSTEM_PROMPT


def test_going_straight_to_the_site_comes_before_the_search_engine() -> None:
    """2026-08-13 실측. 같은 과제 세 판을 두 경로가 나눠 처리했다:

        사이트 직행   4걸음 · 66초 · 3/3
        검색엔진 경유 12걸음 · 148초 · 2/3  (게다가 딴 사이트에서 읽었다)

    전체 기록으로도 4.8걸음/60초 vs 8.1걸음/144초다. 그런데 프롬프트의 "기본 순서"는
    `browser_search` 로 시작하고 있었고, 그 서비스 목록을 원할 때조차
    "browser_search → 결과에서 그 서비스 도메인을 골라"라고 적혀 있었다 —
    **오늘 샌 경로를 프롬프트가 직접 지시하고 있었던 셈이다.**
    """
    assert "갈 곳을 알면 검색엔진을 거치지 마라" in AGENT_SYSTEM_PROMPT
    assert "검색엔진은 **갈 곳을 모를 때만** 쓴다" in AGENT_SYSTEM_PROMPT
    # 옛 지시가 남아 있으면 모델은 여전히 검색부터 한다.
    assert "browser_search → 결과에서 **그 서비스 도메인**을 골라" not in AGENT_SYSTEM_PROMPT


def test_it_warns_that_a_site_link_can_hand_you_to_another_store() -> None:
    """다나와 링크가 광고 브리지였고 스마트스토어로 넘어갔다. 모델은 그걸 몰랐다."""
    assert "광고가 널 다른 가게로 보낸다" in AGENT_SYSTEM_PROMPT
    assert "본문을 읽기 전에 지금 있는 주소가 그 사이트인지 봐라" in AGENT_SYSTEM_PROMPT


def test_the_stale_coupang_knowledge_is_gone() -> None:
    """진짜 크롬으로 갈아탄 뒤로 쿠팡은 열린다. 옛 지식이 남으면 모델이 포기한다."""
    assert "쿠팡 상품 검색은 안 된다" not in AGENT_SYSTEM_PROMPT
    assert "쿠팡 상품 검색은 이제 된다" in AGENT_SYSTEM_PROMPT
