"""검색 결과 화면을 결과 목록으로 바꾸는 규칙.

픽스처는 지어낸 것이 아니라 2026-08-06 에 실제로 잰 것이다 — 질의는
"크몽 AI 챗봇 개발 견적 사례 블로그", `scripts/measure_serp.py` 로 재현할 수 있다.
그때 나온 수치가 이 모듈이 존재하는 이유다:

    네이버  요소 114개 · 첫 외부 결과 j21 · 나무위키 하나가 ref 15개
    빙      요소 40개 · 첫 외부 결과 없음 · http 링크 26개 전부 ck/a 래퍼
"""

from __future__ import annotations

from alture_jarvis.serp import (
    canonical_url,
    collect_results,
    is_navigation,
    naver_blog_ref,
    unwrap_redirect,
)


# ---- 실측 그대로. 이름·href 를 손대지 않았다 ----------------------------------

NAVER_ROWS = [
    {"ref": "j1", "name": "메뉴 영역으로 바로가기", "href": "#lnb"},
    {"ref": "j2", "name": "본문 영역으로 바로가기", "href": "#content"},
    {"ref": "j3", "name": "NAVER", "href": "https://www.naver.com"},
    {"ref": "j5", "name": "한글 입력기", "href": "#"},
    {"ref": "j7", "name": "로그인", "href": "https://nid.naver.com/nidlogin.login?url=https%3A%2F"},
    {"ref": "j8", "name": "서비스 더보기", "href": "javascript:;"},
    {"ref": "j10", "name": "블로그", "href": "?ssc=tab.blog.all&sm=tab_jum&query=%ED%81%AC"},
    {"ref": "j11", "name": "카페", "href": "?ssc=tab.cafe.all&sm=tab_jum&query=%ED%81%AC"},
    {"ref": "j16", "name": "쇼핑", "href": "https://search.shopping.naver.com/search/all?where=a"},
    {"ref": "j18", "name": "어학사전", "href": "https://dict.naver.com/dict.search?query=%ED%81%AC"},
    {"ref": "j19", "name": "더보기", "href": "#"},
    # --- 여기부터 진짜 결과. 나무위키 하나가 ref 15개로 흩어져 있다 ---
    {"ref": "j21", "name": "나무위키 namu.wiki›크몽 새 창 열림", "href": "https://namu.wiki/w/%ED%81%AC%EB%AA%BD"},
    {"ref": "j23", "name": "크몽 - 나무위키 새 창 열림", "href": "https://namu.wiki/w/%ED%81%AC%EB%AA%BD"},
    {"ref": "j24", "name": "본인이나 회사에서 해결하기 어려운 비즈니스 프로젝트가 있는 경우 크몽 전", "href": "https://namu.wiki/w/%ED%81%AC%EB%AA%BD"},
    {"ref": "j26", "name": "개요 새 창 열림", "href": "https://namu.wiki/w/%ED%81%AC%EB%AA%BD#s-1"},
    {"ref": "j27", "name": "상세 새 창 열림", "href": "https://namu.wiki/w/%ED%81%AC%EB%AA%BD#s-2"},
    {"ref": "j28", "name": "역사 새 창 열림", "href": "https://namu.wiki/w/%ED%81%AC%EB%AA%BD#s-3"},
    {"ref": "j36", "name": "크몽 kmong.com›gig 새 창 열림", "href": "https://kmong.com/gig/785601"},
    {"ref": "j38", "name": "쓰던 웹 앱 서비스에 GPT AI 기능 연동 개발 새 창 열림", "href": "https://kmong.com/gig/785601"},
    {"ref": "j39", "name": "두번째 요청이었는데, 이번에도 요청사항에 딱 맞게 꼭 필요한 프로그램을", "href": "https://kmong.com/gig/785601"},
]

# 빙: 목적지가 base64 로 감싸여 있다. `u=a1` 접두가 붙는다.
_KMONG = "a1aHR0cHM6Ly93d3cua21vbmcuY29tLw"           # https://www.kmong.com/
_TISTORY = "a1aHR0cHM6Ly9leGFtcGxlLnRpc3RvcnkuY29tL zE"  # (자리표시)

BING_ROWS = [
    {"ref": "j1", "name": "콘텐츠로 건너뛰기", "href": "#"},
    {"ref": "j9", "name": "전체", "href": "/?scope=web&FORM=HDRSC1"},
    {"ref": "j10", "name": "이미지", "href": "https://www.bing.com/ck/a?!&&p=1b78&u=a1aHR0cHM6Ly93d3cuYmluZy5jb20vaW1hZ2Vz"},
    {"ref": "j15", "name": "kmong.com", "href": f"https://www.bing.com/ck/a?!&&p=2bec&u={_KMONG}&ntb=1"},
    {"ref": "j16", "name": "실력 있는 전문가 찾기, 크몽", "href": f"https://www.bing.com/ck/a?!&&p=2bec&u={_KMONG}&ntb=1"},
    {"ref": "j35", "name": "1페이지", "href": ""},
    {"ref": "j36", "name": "2페이지", "href": "/search?q=%ed%81%ac%eb%aa%bd"},
]


# ---- 껍데기 벗기기 -------------------------------------------------------------


def test_bing_wrapper_is_unwrapped_to_the_real_destination() -> None:
    # 실측: http 링크 26개의 도메인이 전부 www.bing.com 이었다. 모델은 어디로 가는지
    # 모른 채 골라야 했다.
    wrapped = f"https://www.bing.com/ck/a?!&&p=2bec0cff&u={_KMONG}&ntb=1"

    assert unwrap_redirect(wrapped) == "https://www.kmong.com/"


def test_the_a1_prefix_must_be_stripped_or_every_bing_result_is_lost() -> None:
    # 접두를 안 벗기면 base64 정렬이 깨져 전부 실패한다 — 조용히 빙 결과가 0개가 된다.
    import base64

    raw = base64.b64encode(b"https://example.test/page").decode().rstrip("=")

    assert unwrap_redirect(f"https://www.bing.com/ck/a?u=a1{raw}") == "https://example.test/page"


def test_google_style_redirects_are_unwrapped_too() -> None:
    assert (
        unwrap_redirect("https://www.google.com/url?q=https%3A%2F%2Fexample.test%2Fx")
        == "https://example.test/x"
    )


def test_an_unwrappable_url_is_returned_as_is_not_dropped() -> None:
    # 조용히 빈 값을 주면 결과가 통째로 사라진다.
    assert unwrap_redirect("https://example.test/plain") == "https://example.test/plain"


# ---- 묶기 ----------------------------------------------------------------------


def test_fragment_links_collapse_into_one_result() -> None:
    # 나무위키가 ref 15개를 먹은 이유: 목차가 #s-1 … #s-10 으로 전부 다른 주소였다.
    assert canonical_url("https://namu.wiki/w/크몽#s-3") == canonical_url("https://namu.wiki/w/크몽")


def test_naver_scatters_one_result_across_refs_and_we_join_them() -> None:
    results = collect_results(NAVER_ROWS)

    namu = [item for item in results if item.domain == "namu.wiki"]
    assert len(namu) == 1, "목차 링크까지 별개 결과로 세면 순위가 무의미해진다"
    assert len(namu[0].refs) == 6


def test_navigation_is_dropped_so_the_first_result_is_rank_one() -> None:
    results = collect_results(NAVER_ROWS)

    # 실측에서 첫 결과는 j21 이었다. 탭·로그인·사전을 세지 않으면 1위가 된다.
    assert results[0].rank == 1
    assert results[0].domain == "namu.wiki"
    assert not any(item.domain.endswith("naver.com") for item in results)


def test_the_source_line_does_not_become_the_title() -> None:
    results = collect_results(NAVER_ROWS)

    kmong = next(item for item in results if item.domain == "kmong.com")
    assert kmong.title == "쓰던 웹 앱 서비스에 GPT AI 기능 연동 개발"
    assert "요청사항에 딱 맞게" in kmong.snippet


def test_naver_breadcrumbs_are_source_lines_even_with_a_brand_in_front() -> None:
    # `크몽 kmong.com›gig` — 도메인이 가운데 온다. 앞을 ^ 로 묶으면 이 꼴을 놓쳐
    # 브레드크럼이 제목 자리에 앉는다.
    results = collect_results(NAVER_ROWS)

    namu = next(item for item in results if item.domain == "namu.wiki")
    assert namu.title == "크몽 - 나무위키"
    assert "›" not in namu.title


def test_bing_pairs_collapse_and_keep_the_prose_title() -> None:
    results = collect_results(BING_ROWS)

    assert len(results) == 1, "도메인 줄과 제목 줄은 같은 결과다"
    assert results[0].url == "https://www.kmong.com/"
    assert results[0].domain == "kmong.com"
    assert results[0].title == "실력 있는 전문가 찾기, 크몽"


def test_bing_tab_links_are_dropped_only_after_unwrapping() -> None:
    # 빙은 탭조차 ck/a 로 감싼다. 벗기기 전에는 결과와 구별되지 않는다.
    results = collect_results(BING_ROWS)

    assert not any("bing.com" in item.domain for item in results)


def test_pager_links_are_not_results() -> None:
    assert is_navigation("2페이지", "/search?q=x")
    assert is_navigation("Page 3", "https://www.bing.com/search?q=x")


def test_visited_urls_are_marked_so_the_agent_does_not_loop() -> None:
    results = collect_results(NAVER_ROWS, visited=["https://namu.wiki/w/%ED%81%AC%EB%AA%BD"])

    namu = next(item for item in results if item.domain == "namu.wiki")
    assert namu.visited is True
    assert namu.as_dict()["visited"] is True


def test_limit_caps_the_list() -> None:
    assert len(collect_results(NAVER_ROWS, limit=1)) == 1


# ---- 네이버 블로그 카드: 홈 링크가 글과 별개 순위로 앉던 자리 --------------------
#
# 2026-08-07 실측 그대로다. 질의 "제주도 3박4일 여행 경비 총정리", 네이버 블로그 탭.
# 카드 하나가 홈 링크 2개(빈 이름 + 블로그 이름)와 글 링크 여러 개를 낸다.

BLOG_TAB_ROWS = [
    {"ref": "j20", "name": "블로그", "href": "?ssc=tab.blog.all&query=%EC%A0%9C%EC%A3%BC"},
    {"ref": "j21", "name": "새 창 열림", "href": "https://blog.naver.com/negelowha"},
    {"ref": "j22", "name": "memory and goodtime 새 창 열림", "href": "https://blog.naver.com/negelowha"},
    {"ref": "j23", "name": "제주도 여행 3박 4일 2인용 코스 새 창 열림", "href": "https://blog.naver.com/negelowha/224368785692"},
    {"ref": "j24", "name": "제주도 3박 4일 2인 여행 코스, 진짜 자세하게 다 풀어봅니다", "href": "https://blog.naver.com/negelowha/224368785692"},
    {"ref": "j30", "name": "새 창 열림", "href": "https://blog.naver.com/new_yyoung"},
    {"ref": "j31", "name": "나의하루. 새 창 열림", "href": "https://blog.naver.com/new_yyoung"},
    {"ref": "j32", "name": "제주도 동쪽 3박4일 여름휴가 여행코스 및 2인 경비 총정리! 새 창 열림", "href": "https://blog.naver.com/new_yyoung/224361780207"},
    {"ref": "j33", "name": "렌트카-파도식당-유니클로 제주도남점-세화서핑스쿨-세화해변-돈구어 3일차", "href": "https://blog.naver.com/new_yyoung/224361780207"},
]


def test_the_blog_home_link_does_not_take_a_rank_of_its_own() -> None:
    # 실측: 결과 10건 중 1·3·5·7·9 위가 글이 아니라 블로그 홈이었다. 열면 그 블로그의
    # 최신 글(질의와 무관한 글)이 떠서 순위의 절반이 통째로 버려졌다.
    results = collect_results(BLOG_TAB_ROWS)

    assert [item.url for item in results] == [
        "https://blog.naver.com/negelowha/224368785692",
        "https://blog.naver.com/new_yyoung/224361780207",
    ]
    assert results[0].rank == 1 and results[1].rank == 2


def test_the_home_link_keeps_the_card_position_it_had() -> None:
    # 홈이 카드의 맨 위에 그려지므로, 홈을 빼면 글이 그 자리를 물려받아야 한다.
    results = collect_results(BLOG_TAB_ROWS)

    assert results[0].title == "제주도 여행 3박 4일 2인용 코스"
    # 대표 ref 는 글 쪽 그대로여야 한다 — 누르면 홈이 아니라 글로 가야 하므로.
    assert results[0].ref == "j23"
    assert "j21" in results[0].refs, "홈 링크의 ref 도 같은 카드의 증거로 남는다"


def test_merging_happens_before_the_limit_so_the_list_is_not_halved() -> None:
    # 자른 뒤에 합치면 2건 달라고 했을 때 1건만 남는다 — 낭비가 사라지는 게 아니라
    # 목록이 짧아진다.
    assert len(collect_results(BLOG_TAB_ROWS, limit=2)) == 2


def test_a_visited_post_absorbs_its_own_blog_home_instead_of_repeating_it() -> None:
    # 실측 7위가 이것이었다 — 이미 읽은 글의 블로그 홈이라 중복이면서 쓸모도 없었다.
    results = collect_results(
        BLOG_TAB_ROWS, visited=["https://blog.naver.com/negelowha/224368785692"]
    )

    assert results[0].visited is True
    assert not any(item.url == "https://blog.naver.com/negelowha" for item in results)


def test_a_blog_home_with_no_post_in_the_list_survives() -> None:
    # 글이 없는 홈까지 지우면 "결과가 없다"는 거짓 결론이 된다.
    results = collect_results(
        [{"ref": "j21", "name": "memory and goodtime", "href": "https://blog.naver.com/negelowha"}]
    )

    assert [item.url for item in results] == ["https://blog.naver.com/negelowha"]


def test_post_and_home_urls_are_told_apart_by_shape() -> None:
    assert naver_blog_ref("https://blog.naver.com/negelowha/224368785692") == ("negelowha", "post")
    assert naver_blog_ref("https://m.blog.naver.com/negelowha/224368785692") == ("negelowha", "post")
    assert naver_blog_ref("https://blog.naver.com/negelowha") == ("negelowha", "home")
    assert naver_blog_ref("https://blog.naver.com/PostList.naver?blogId=negelowha") == (
        "negelowha",
        "home",
    )
    assert naver_blog_ref(
        "https://blog.naver.com/PostView.naver?blogId=negelowha&logNo=224368785692"
    ) == ("negelowha", "post")


def test_shapes_we_do_not_recognise_are_left_alone_not_guessed() -> None:
    # 글을 홈으로 잘못 읽으면 진짜 결과가 병합돼 사라진다. 애매하면 손대지 않는다.
    assert naver_blog_ref("https://blog.naver.com/PostView.naver?blogId=x") == ("", "")
    assert naver_blog_ref("https://cafe.naver.com/somecafe") == ("", "")
    assert naver_blog_ref("https://example.test/negelowha") == ("", "")


def test_a_mobile_post_absorbs_the_desktop_home_of_the_same_blog() -> None:
    # 호스트가 갈려도 같은 블로그다 — blogId 로 맞춘다.
    results = collect_results(
        [
            {"ref": "j1", "name": "memory and goodtime", "href": "https://blog.naver.com/negelowha"},
            {"ref": "j2", "name": "제주도 여행 3박 4일", "href": "https://m.blog.naver.com/negelowha/224368785692"},
        ]
    )

    assert len(results) == 1
    assert results[0].url == "https://m.blog.naver.com/negelowha/224368785692"
