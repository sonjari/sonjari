"""검색 결과가 대부분 **남이 쓴 글**이면 원문 서비스로 들어가라고 말한다.

2026-08-12 실측(여수·순천·광양 채용 공고). 네이버 웹·블로그만 뒤져서 연 것이
티스토리 글 하나·네이버 블로그 하나였고, 유일하게 찾은 진짜 공고는 **2025년 9월에
마감된 것**이었다. 답 자체는 정직했지만("현재 지원 가능한 공고 없음") 쓸 결과가 0건.

블로그 글은 그때의 이야기다. 지금 열려 있는 것을 알려면 그 서비스 안으로 들어가
그 사이트의 검색을 써야 한다 — "네이버에서 → 잡코리아" 로 가는 길.

여기서 지키는 것 넷:

  1. 블로그·카페가 결과의 절반 이상이면 알린다
  2. 원문 서비스가 섞여 있으면(정상적인 결과) 잔소리하지 않는다
  3. **주소를 지어내라고는 절대 말하지 않는다** — 결과를 눌러 들어가라고 한다
  4. 사이트 목록을 늘리는 방식이 아니다. 늘려야 하는 쪽(채용 사이트)은 끝이 없고,
     안 늘어나는 쪽(블로그·카페)만 적는다
"""

from __future__ import annotations

from alture_jarvis.browser import BrowserWorker

_note = BrowserWorker._secondhand_note


def _result(rank: int, domain: str) -> dict[str, object]:
    return {"rank": rank, "title": f"결과 {rank}", "url": f"https://{domain}/x", "domain": domain}


def test_mostly_blogs_gets_told_to_go_to_the_real_service() -> None:
    results = [
        _result(1, "beawesome0321.tistory.com"),
        _result(2, "blog.naver.com"),
        _result(3, "cafe.naver.com"),
        _result(4, "jasoseol.com"),
    ]

    note = _note(results)

    assert note, "블로그 잔치인데 아무 말도 안 했다"
    assert "browser_site_search" in note, "그 사이트 안에서 찾으라고 말하지 않는다"
    assert "시점이 지난" in note
    assert "사이트 이름을 끼워 넣어" in note, (
        "검색어에 '잡코리아'를 끼워 넣고 또 검색하는 것이 정확히 실측된 실패다"
    )


def test_it_never_tells_the_model_to_make_up_an_address() -> None:
    """크몽을 kmon.co.kr 로 만들어 갔던 사고를 다시 열지 않는다."""
    note = _note([_result(1, "blog.naver.com"), _result(2, "tistory.com")])

    assert "결과를 눌러라" in note
    assert "지어내지" in note


def test_a_healthy_result_list_says_nothing() -> None:
    """잔소리가 잦아지면 안 읽힌다."""
    results = [
        _result(1, "jobkorea.co.kr"),
        _result(2, "saramin.co.kr"),
        _result(3, "work.go.kr"),
        _result(4, "blog.naver.com"),
    ]

    assert _note(results) == ""


def test_empty_results_say_nothing() -> None:
    assert _note([]) == ""


def test_subdomains_of_blog_hosts_count() -> None:
    """티스토리는 사람마다 서브도메인이라 정확히 일치하지 않는다."""
    results = [_result(1, "beawesome0321.tistory.com"), _result(2, "abc.tistory.com")]

    assert _note(results) != ""
