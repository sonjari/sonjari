"""검색은 **주소를 조립하는 일이 아니라 칸에 치는 일**이다.

## 사용자님이 브라우저를 보다가 잡은 것 (2026-08-13)

    "기본 URL에 넣을 결과를 넣네. 이게 아니라 다나와 페이지 검색창 UI에 클릭해서
     커서 뜨면 거기에 넣어야지. 이거는 모든 사이트 공통이다."

측정해 보니 그대로였다(그날 잡 260건):

    browser_open 74 회 중 **검색어가 주소에 박힌 것 12 회**
    browser_site_search(칸에 치는 도구) 40 회

## 안 통해서가 문제가 아니다 — 조용히 틀려서 문제다

같은 날 모델이 만든 주소:

    search.danawa.com/dsearch/main?tab=shopping&query=%EB%AC%B4%EC%84%A7…
                                                      ^^^^ 디코딩하면 "무섧마우스"

**퍼센트 인코딩을 손으로 쓰다 한 글자를 틀렸다.** 사람이 검색칸에 치면 절대 안 나오는
오타다. 그리고 이런 주소는 404 가 아니라 **빈 목록**으로 돌아온다 — "그 사이트엔
없네요"가 되어 버린다. 경로도 같다(`dsearch?q=` 는 진짜 `dsearch.php?query=` 가 아니다).

## 그래서 안내가 아니라 도구가 한다

여기엔 원래 `_handmade_search_note` 라는 **안내문**이 있었다("다음부터는 site_search 를
써라"). 위 12회가 그 안내를 받고도 난 것이다. 이 저장소가 오늘만 세 번 확인한 규칙 —
결정론으로 박을 수 있는 것은 코드로.

막기만 하지 않는 이유: 검색칸을 못 찾는 화면이 있다. 그때는 원래 주소로 가되
**그 사실을 결과에 적는다**(하이브리드).
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.browser import BrowserWorker


_query = BrowserWorker._handmade_search_query


class _Worker:
    """`_search_like_a_person` 만 떼어 본다."""

    def __init__(self, *, box_found: bool = True) -> None:
        self.went: list[str] = []
        self.typed: list[str] = []
        self.box_found = box_found

    # --- 진짜 워커에서 빌려 오는 것들 (판정 로직 그대로) ---
    _handmade_search_query = BrowserWorker._handmade_search_query
    _HANDMADE_SEARCH = BrowserWorker._HANDMADE_SEARCH
    _SEARCH_ENTRY_PATH = BrowserWorker._SEARCH_ENTRY_PATH
    _SEARCH_ENGINE_HOSTS = BrowserWorker._SEARCH_ENGINE_HOSTS
    _QUERY_KEYS = BrowserWorker._QUERY_KEYS

    def _goto_checked(self, page: Any, url: str) -> None:
        self.went.append(url)

    _wait_until_operable = staticmethod(lambda page: {"count": 10, "ms": 1, "polls": 1})
    _mark_visited = staticmethod(lambda url: None)
    _evidence = staticmethod(lambda action, **kw: {"action": action, **kw})

    def _site_search(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.box_found:
            raise RuntimeError("site_search_box_not_found:example.com")
        self.typed.append(str(arguments.get("query") or ""))
        return {"action": "site_searched", "results": [{"rank": 1}]}


def _run(url: str, *, box_found: bool = True):
    worker = _Worker(box_found=box_found)
    return worker, BrowserWorker._search_like_a_person(worker, page=None, url=url)


# ── 무엇이 "손으로 만든 검색 입구"인가 ──────────────────────────────────────


def test_a_built_search_url_is_recognised() -> None:
    assert _query(_Worker(),"https://search.danawa.com/dsearch?q=무선마우스") == "무선마우스"
    assert _query(_Worker(),"https://search.kyobobook.co.kr/search?keyword=회계") == "회계"
    assert _query(_Worker(),"https://www.jobkorea.co.kr/Search/?stext=여수회계") == "여수회계"
    assert _query(_Worker(),"https://www.coupang.com/np/search?q=무선마우스") == "무선마우스"


def test_a_detail_page_is_not_a_search_entry() -> None:
    """★ 이 구분이 없으면 멀쩡한 상세 이동까지 가로챈다.

    잡코리아 공고 상세는 주소에 `stext=` 를 달고 다닌다 — 검색에서 넘어왔다는
    흔적일 뿐 검색 입구가 아니다. 실제로 그날 자비스가 이 주소로 공고를 읽었다.
    """
    assert _query(_Worker(),"https://www.jobkorea.co.kr/Recruit/GI_Read/49567381?Oem_Code=C1&stext=여수") == ""
    assert _query(_Worker(),"https://www.coupang.com/vp/products/1796918840?itemId=3057049578") == ""
    assert _query(_Worker(),"https://prod.danawa.com/info/?pcode=91770953&keyword=무선마우스") == ""


def test_search_engines_are_left_alone() -> None:
    """구글·네이버 주소는 `browser_search` 가 일부러 조립하는 것이다."""
    assert _query(_Worker(),"https://search.naver.com/search.naver?query=크몽") == ""
    assert _query(_Worker(),"https://www.google.com/search?q=wishket") == ""


def test_a_plain_page_is_left_alone() -> None:
    assert _query(_Worker(),"https://www.danawa.com/") == ""
    assert _query(_Worker(),"https://search.danawa.com/") == ""  # 검색어가 없다


# ── 하이브리드: 사람 방식이 먼저, 주소는 폴백 ───────────────────────────────


def test_it_types_into_the_box_instead_of_going_to_the_url() -> None:
    worker, result = _run("https://search.danawa.com/dsearch?q=무선마우스")

    assert result is not None
    assert worker.typed == ["무선마우스"], "칸에 치지 않았다"
    assert worker.went == ["https://search.danawa.com/"], "사이트로 들어가지 않았다"
    assert result["typed_search"] is True


def test_it_falls_back_to_the_url_when_there_is_no_box() -> None:
    """막기만 하면 검색칸 없는 사이트에서 길이 끊긴다."""
    worker, result = _run("https://search.danawa.com/dsearch?q=무선마우스", box_found=False)

    assert result is not None
    assert result["typed_search"] is False
    assert worker.went[-1] == "https://search.danawa.com/dsearch?q=무선마우스"
    assert "빈 목록" in result["instruction"], "왜 위험한지 안 알려 준다"


def test_ordinary_navigation_is_untouched() -> None:
    """None 을 돌려줘야 `_open` 이 원래 하던 대로 연다."""
    worker, result = _run("https://www.wishket.com/project/157430/")
    assert result is None
    assert worker.went == [] and worker.typed == []
