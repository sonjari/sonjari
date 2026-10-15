"""검색 → 결과 → 본문 → 그 안의 링크 → 다음 결과. 파고드는 고리.

이 고리가 완성되기 전에는 `browser_search` 가 결과를 하나도 돌려주지 않았고, 모델은
`browser_snapshot` 으로 200개 덤프를 뒤져야 했다. 그 덤프가 어떤 모양이었는지는
`test_serp_results.py` 에 실측 그대로 들어 있다.

여기서 지키려는 것은 파싱이 아니라 **고리**다:

  · 순위가 뜻을 가질 것          (결과 목록이 세션에 남아 있어야 한다)
  · 같은 글을 두 번 열지 않을 것  (뒤로 오면 화면이 똑같아 기록이 없으면 1번부터 다시 고른다)
  · 목록으로 안 돌아가도 될 것    (뒤로가기는 느리고, 검색 화면은 다시 그려진다)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Locator:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def count(self) -> int:
        return len(self._rows)

    def nth(self, index: int) -> "_Element":
        return _Element(self._rows[index])


class _Element:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def is_visible(self) -> bool:
        return True

    def is_disabled(self) -> bool:
        return False

    def evaluate(self, script: str, *args: Any) -> Any:
        return "a" if "tagName" in script else None

    def get_attribute(self, name: str) -> str | None:
        return self._row.get(name)

    def inner_text(self, timeout: int = 0) -> str:
        del timeout
        return self._row.get("name", "")


class _Frame:
    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        extract: Any = None,
        links: Any = None,
        chrome: list[str] | None = None,
    ) -> None:
        self.rows = rows
        self.url = "https://search.naver.com/search.naver"
        self.name = ""
        self._extract = extract
        self._links = links
        self._chrome = chrome or []

    def locator(self, selector: str) -> _Locator:
        del selector
        return _Locator(self.rows)

    def evaluate(self, script: str) -> Any:
        if "linkChars" in script:
            return self._extract
        # 실제 브라우저에서는 반복 카드 판정기가 목록의 대표 링크를 돌려준다.
        # 이 가짜도 그 계약을 흉내 내야 "화면에 이미 있는 목록" 복구를 시험한다.
        if "const tally = new Map()" in script:
            return [
                {"name": row.get("name", ""), "href": row.get("href", "")}
                for row in self.rows
                if row.get("href")
            ]
        # 화면 장치 수집이 먼저다 — 둘 다 a[href] 를 쓰므로 순서가 중요하다.
        if "role=banner" in script:
            return self._chrome
        if "a[href]" in script:
            return self._links
        return None


class _Page:
    def __init__(self, frame: _Frame) -> None:
        self.frames = [frame]
        self.url = "https://search.naver.com/search.naver"
        self.goto_calls: list[str] = []

    def goto(self, url: str, wait_until: str = "") -> None:
        del wait_until
        self.goto_calls.append(url)
        self.url = url

    def wait_for_timeout(self, ms: int) -> None:
        del ms

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "검색 결과"

    def evaluate(self, script: str, *args: Any) -> Any:
        del script, args
        return None


SERP_ROWS = [
    {"name": "블로그", "href": "?ssc=tab.blog.all&query=x"},
    {"name": "로그인", "href": "https://nid.naver.com/nidlogin.login"},
    {"name": "크몽 kmong.com›gig 새 창 열림", "href": "https://kmong.com/gig/785601"},
    {"name": "쓰던 웹 앱 서비스에 GPT AI 기능 연동 개발 새 창 열림", "href": "https://kmong.com/gig/785601"},
    # 네이버의 출처 줄은 `<블로그명> <도메인>›<경로>` 이지 글 제목이 아니다
    # (실측: `나무위키 namu.wiki›크몽` 다음 줄에 `크몽 - 나무위키` 가 왔다).
    {"name": "개발일지 blog.naver.com›dev 새 창 열림", "href": "https://blog.naver.com/dev/222"},
    {"name": "AI 챗봇 만든 후기 새 창 열림", "href": "https://blog.naver.com/dev/222"},
    {"name": "챗봇 개발 견적을 세 군데서 받아본 이야기입니다 새 창 열림", "href": "https://blog.naver.com/dev/222"},
]


def _worker(tmp_path: Path, **overrides: Any) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            **overrides,
        )
    )


def test_search_hands_back_a_ranked_list_not_just_the_query(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    result = worker._search(page, {"query": "크몽 AI 챗봇 견적"})

    assert result["result_count"] == 2, "예전에는 결과가 0개였다 — 검색어만 돌려줬다"
    assert [item["rank"] for item in result["results"]] == [1, 2]
    assert result["results"][0]["domain"] == "kmong.com"
    assert result["results"][1]["title"] == "AI 챗봇 만든 후기"


def test_it_waits_for_results_not_merely_for_the_page_chrome(tmp_path: Path) -> None:
    """검색창과 탭은 즉시 그려진다. 결과는 그 뒤에 온다.

    실측(2026-08-06 네이버 블로그 탭): 조작 가능한 요소 197개인데 결과는 0건이었다.
    `_wait_until_operable` 은 첫 폴에서 바로 통과한다 — 검색창이 이미 있으니까.
    그리고 0건은 "이 질의에 결과가 없다"와 구별되지 않아서, 모델은 멀쩡한 검색을
    버리고 질의를 바꾸러 간다.
    """
    chrome_only = [
        {"name": "블로그", "href": "?ssc=tab.blog.all&query=x"},
        {"name": "로그인", "href": "https://nid.naver.com/nidlogin.login"},
    ]

    class _LateFrame(_Frame):
        """세 번째로 물어볼 때 결과가 나타나는 화면."""

        def __init__(self) -> None:
            super().__init__(chrome_only)
            self.asked = 0

        def locator(self, selector: str) -> _Locator:
            self.asked += 1
            return _Locator(chrome_only if self.asked <= 2 else SERP_ROWS)

    worker = _worker(tmp_path, browser_ready_timeout_ms=4000)
    page = _Page(_LateFrame())

    result = worker._search(page, {"query": "크몽 견적"})

    assert result["result_count"] == 2, "덜 그려진 화면을 결과 없음으로 읽으면 안 된다"
    assert result["result_polls"] > 1, "몇 번 만에 잡았는지가 '정말 없다'와 가르는 증거다"


def test_a_search_with_genuinely_no_results_still_returns(tmp_path: Path) -> None:
    # 기다리기만 하고 안 끝나면 검색이 통째로 멈춘다.
    worker = _worker(tmp_path, browser_ready_timeout_ms=600)
    page = _Page(_Frame([{"name": "로그인", "href": "https://nid.naver.com/nidlogin.login"}]))

    result = worker._search(page, {"query": "결과없는질의"})

    assert result["result_count"] == 0
    assert "tab" in result["instruction"], "0건일 때는 무엇을 바꿔 볼지 알려 줘야 한다"


# ---- 헛도는 것을 알아본다 --------------------------------------------------------


def test_the_same_search_twice_is_called_out(tmp_path: Path) -> None:
    """검색은 언제나 성공으로 돌아온다 — 그래서 헛도는 것을 스스로 못 안다.

    실측(2026-08-06): 한 질문에 browser_search 8번, browser_extract 1번. 결과가
    마음에 안 들자 파고드는 대신 검색어를 바꿔 가며 목록만 다시 받았다.
    """
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    first = worker._search(page, {"query": "크몽 견적"})
    second = worker._search(page, {"query": "크몽 견적"})

    assert "repeated_search" not in first
    assert second["repeated_search"] is True
    assert "browser_open_result" in second["instruction"]


def test_changing_the_words_does_not_escape_the_guard(tmp_path: Path) -> None:
    """★ 이것이 두 번째 실측의 정체다.

    프롬프트를 고친 뒤에도 검색 7번·본문 1개였다. `repeated_search` 는 **같은 낱말**
    일 때만 걸리는데, 모델은 검색어를 조금씩 바꿔 가며 목록만 다시 받았다.
    낱말이 아니라 **행동**(받아 놓고 안 읽었는가)을 봐야 걸린다.
    """
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    worker._search(page, {"query": "크몽 AI 챗봇 견적"})
    second = worker._search(page, {"query": "크몽 챗봇 개발 비용"})       # 낱말이 다르다
    third = worker._search(page, {"query": "크몽 챗봇 제작 후기 금액"})   # 또 다르다

    assert "repeated_search" not in third, "낱말이 다르므로 질의 일치로는 안 걸린다"
    assert second["searches_without_reading"] == 1
    assert third["searches_without_reading"] == 2
    assert "하나도 안 읽은 채 검색만" in third["instruction"]


def test_reading_one_result_clears_the_guard(tmp_path: Path) -> None:
    # 읽고 나서 다른 각도로 다시 검색하는 것은 정상이다. 거기까지 막으면 안 된다.
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))
    worker._search(page, {"query": "크몽 견적"})
    worker._open_result(page, {"rank": 1})

    again = worker._search(page, {"query": "크몽 기간"})

    assert "searches_without_reading" not in again


def test_opening_a_result_says_how_many_are_left(tmp_path: Path) -> None:
    # 하나 읽고 "이 글엔 없네" 하고 검색으로 돌아가는 것을 막는 자리다.
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))
    worker._search(page, {"query": "크몽 견적"})

    first = worker._open_result(page, {"rank": 1})
    second = worker._open_result(page, {"rank": 2})

    assert first["read_so_far"] == 1
    assert first["remaining"] == [2]
    assert "검색하지 말고" in first["instruction"]
    assert second["read_so_far"] == 2
    assert second["remaining"] == []


def test_extract_points_at_the_next_unread_result(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    body = {"score": 900, "text": "본문 " * 60, "selector": "div.post", "link_ratio": 2}
    page = _Page(_Frame(SERP_ROWS, extract=body))
    worker._search(page, {"query": "크몽 견적"})
    worker._open_result(page, {"rank": 1})

    read = worker._extract(page, {})

    assert read["read_so_far"] == 1
    assert read["remaining"] == [2]
    assert "새로 검색하지 마라" in read["instruction"]


def test_a_different_query_is_not_flagged(tmp_path: Path) -> None:
    # 잘못 붙으면 정상적인 재검색까지 헛도는 것으로 몰린다.
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))
    worker._search(page, {"query": "크몽 견적"})

    other = worker._search(page, {"query": "크몽 기간"})

    assert "repeated_search" not in other


def test_the_same_words_in_a_different_tab_is_a_new_search(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))
    worker._search(page, {"query": "크몽 견적", "engine": "naver", "tab": "all"})

    blog = worker._search(page, {"query": "크몽 견적", "engine": "naver", "tab": "blog"})

    assert "repeated_search" not in blog


# ---- site: 연산자 -----------------------------------------------------------------


def test_the_site_operator_is_stripped_because_naver_ignores_it(tmp_path: Path) -> None:
    """실측에서 모델이 `site:blog.naver.com …` 을 두 번 보냈다.

    구글에서 배운 습관인데 네이버는 이 연산자를 모른다 — 조용히 빈손으로 돌아오고,
    모델은 그것을 "그 사이트에는 자료가 없다"로 읽어 멀쩡한 검색을 포기한다.
    """
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    result = worker._search(page, {"query": "site:blog.naver.com 크몽 AI 챗봇 후기", "engine": "naver"})

    assert result["query"] == "크몽 AI 챗봇 후기"
    assert result["site_operator_removed"] == "blog.naver.com"
    assert "site%3A" not in page.goto_calls[-1] and "site:" not in page.goto_calls[-1]


def test_a_normal_query_is_untouched(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    result = worker._search(page, {"query": "크몽 견적 사례"})

    assert result["query"] == "크몽 견적 사례"
    assert "site_operator_removed" not in result


def test_account_widgets_in_the_header_are_not_results(tmp_path: Path) -> None:
    """★ 로그인한 브라우저에서만 드러난 고장 (2026-08-06, MCP 로 붙이고 나서).

    그때까지 검증은 **로그아웃된 임시 프로필**로만 했다. 사용자님이 실제로 쓰는
    브라우저는 네이버에 로그인돼 있고, 그러면 검색 화면 머리말에 계정 위젯이 붙는다:

        1위 네이버톡 · 2위 알림 58 · 3위 메일 4 · 4위부터 진짜 결과

    결과 8칸 중 3칸을 먹었고, `browser_open_result rank=1` 이 네이버톡을 열었다.
    호스트를 하나씩 늘려 막지 않는다 — **어디에 있는가**로 가른다.
    """
    logged_in_rows = [
        {"name": "네이버톡", "href": "https://talks.naver.com/?frm=pcgnb"},
        {"name": "알림 58", "href": "https://m.notify.naver.com/?from=pcmain"},
        {"name": "메일 4", "href": "https://mail.naver.com"},
        *SERP_ROWS,
    ]
    worker = _worker(tmp_path)
    page = _Page(_Frame(logged_in_rows, chrome=[
        "https://talks.naver.com/?frm=pcgnb",
        "https://m.notify.naver.com/?from=pcmain",
        "https://mail.naver.com",
    ]))

    result = worker._search(page, {"query": "제주도 경비"})

    domains = {item["domain"] for item in result["results"]}
    assert "talks.naver.com" not in domains
    assert "m.notify.naver.com" not in domains
    assert "mail.naver.com" not in domains
    assert result["results"][0]["domain"] == "kmong.com", "1위가 진짜 결과여야 한다"


def test_the_blog_tab_is_a_url_not_an_api(tmp_path: Path) -> None:
    # 검색 API 를 쓰면 제목·요약·URL 한 겹으로 끝이라 그 글 안으로 못 들어간다.
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    worker._search(page, {"query": "크몽 견적", "engine": "naver", "tab": "blog"})

    assert "ssc=tab.blog.all" in page.goto_calls[0]


def test_rank_is_how_you_drill_in_because_refs_die_on_navigation(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))
    worker._search(page, {"query": "크몽 견적"})

    result = worker._open_result(page, {"rank": 2})

    assert page.goto_calls[-1] == "https://blog.naver.com/dev/222"
    assert result["rank"] == 2
    assert result["result_title"] == "AI 챗봇 만든 후기"


def test_you_can_jump_to_the_next_result_without_going_back(tmp_path: Path) -> None:
    # 뒤로가기로 목록에 돌아오면 검색 화면이 다시 그려지고 ref 번호가 전부 달라진다.
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))
    worker._search(page, {"query": "크몽 견적"})

    worker._open_result(page, {"rank": 1})
    worker._open_result(page, {"rank": 2})

    assert page.goto_calls[-2:] == [
        "https://kmong.com/gig/785601",
        "https://blog.naver.com/dev/222",
    ]


def test_a_second_search_marks_what_was_already_read(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))
    worker._search(page, {"query": "크몽 견적"})
    worker._open_result(page, {"rank": 1})

    again = worker._search(page, {"query": "크몽 견적"})

    assert again["results"][0]["visited"] is True
    assert "visited" not in again["results"][1], "안 본 것에 표시가 붙으면 전부 건너뛴다"


def test_an_unknown_rank_says_which_ones_exist(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))
    worker._search(page, {"query": "크몽 견적"})

    try:
        worker._open_result(page, {"rank": 9})
    except ValueError as exc:
        assert "9" in str(exc) and "1, 2" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("없는 순위는 조용히 넘어가면 안 된다")


def test_a_list_on_screen_needs_no_prior_search(tmp_path: Path) -> None:
    """★ 2026-08-13 에 **계약이 바뀐 자리다.**

    예전 이 시험은 "검색을 안 했으면 rank 1 은 열리면 안 된다"였다. 그런데 그 규칙이
    실제로 벌준 것은 **사람처럼 다닌 판**이었다(위시켓 15걸음 실측): 홈 → '프로젝트
    찾기' 클릭 → 검색칸 입력 → Enter 로 목록을 띄웠는데 `no_search_results` 로 세 번
    거절당했고, 그때마다 ref 손클릭 → `browser_back` 30초 타임아웃으로 목록을 잃었다.

    "몇 번째를 열어라"는 **화면의 성질**이지 어떻게 도착했는지가 아니다. 사람은 목록이
    보이면 세 번째를 누른다. 그래서 이제 화면에서 목록을 찾아 순위를 만든다.

    막는 것은 그대로다 — 화면에 목록이 **없으면** 여전히 시끄럽게 실패한다
    (`test_drilling_in_with_no_list_at_all_still_fails`).
    """
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    opened = worker._open_result(page, {"rank": 1})

    assert opened["action"] == "opened_result"
    assert opened["rank"] == 1


def test_drilling_in_with_no_list_at_all_still_fails(tmp_path: Path) -> None:
    """목록이 없으면 없는 것이다. 조용히 아무거나 열면 그게 더 나쁘다."""
    worker = _worker(tmp_path)
    page = _Page(_Frame([]))

    try:
        worker._open_result(page, {"rank": 1})
    except RuntimeError as exc:
        assert "no_result_list" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("목록이 없는데 열리면 안 된다")


# ---- 본문 추리기 ---------------------------------------------------------------


def test_extract_prefers_the_body_over_the_whole_screen(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    body = {"score": 900, "text": "본문입니다. " * 40, "selector": "div.se-main-container", "link_ratio": 3}
    page = _Page(_Frame(SERP_ROWS, extract=body))

    result = worker._extract(page, {})

    assert result["fell_back"] is False
    assert result["selector"] == "div.se-main-container"
    assert "본문입니다" in result["text"]


def test_extract_says_so_when_it_could_not_find_a_body(tmp_path: Path) -> None:
    # 조용히 빈 값을 주면 "글이 없는 페이지"로 읽혀 모델이 엉뚱한 결론을 낸다.
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS, extract=None))

    result = worker._extract(page, {})

    assert result["fell_back"] is True
    assert result["note"]


# ---- 다음 한 걸음 --------------------------------------------------------------


LINKS = [
    {"href": "https://blog.naver.com/dev/223", "text": "다음 편 - 실제 견적서 공개"},
    {"href": "https://kmong.com/gig/785601", "text": "제가 쓴 업체"},
    {"href": "javascript:void(0)", "text": "더보기"},
]


def test_links_split_inside_from_outside(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS, links=LINKS))
    page.url = "https://blog.naver.com/dev/222"

    inside = worker._links(page, {"same_site": "inside"})
    outside = worker._links(page, {"same_site": "outside"})

    assert [item["url"] for item in inside["links"]] == ["https://blog.naver.com/dev/223"]
    assert [item["url"] for item in outside["links"]] == ["https://kmong.com/gig/785601"]


def test_links_mark_what_was_already_visited(tmp_path: Path) -> None:
    # 서로를 가리키는 두 글 사이를 무한히 오가는 것을 막는 유일한 장치다.
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS, links=LINKS))
    page.url = "https://blog.naver.com/dev/222"
    worker._mark_visited("https://kmong.com/gig/785601")

    result = worker._links(page, {})

    kmong = next(item for item in result["links"] if item["domain"] == "kmong.com")
    assert kmong["visited"] is True


def test_links_can_be_filtered_by_word(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS, links=LINKS))
    page.url = "https://blog.naver.com/dev/222"

    result = worker._links(page, {"contains": "다음 편"})

    assert result["link_count"] == 1


# ---- 찾기 ----------------------------------------------------------------------


def test_find_returns_only_the_hits(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    result = worker._find(page, {"query": "로그인"})

    assert result["match_count"] == 1
    assert result["scanned"] == len(SERP_ROWS)
    assert result["matches"][0]["name"] == "로그인"


def test_find_with_nothing_found_does_not_read_as_an_empty_page(tmp_path: Path) -> None:
    # 0건은 "없다"가 아니라 "이 이름으로는 없다"이다. 그 구별을 안 하면 모델이
    # 없는 셀렉터를 지어내기 시작한다.
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    result = worker._find(page, {"query": "결제하기"})

    assert result["match_count"] == 0
    assert str(result["scanned"]) in result["instruction"]
    assert "지어내지" in result["instruction"]


def test_find_accepts_a_regex(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page(_Frame(SERP_ROWS))

    result = worker._find(page, {"query": r"블로그|카페", "regex": True})

    assert result["match_count"] >= 1
