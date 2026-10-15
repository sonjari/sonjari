"""엑셀 한 줄의 이름은 그 줄에 적은 **주소의 페이지**에서 와야 한다 — 추천 띠에서 베낀 줄을 잡는다.

★ 2026-09-28 헤르메스 대결 T1 O1b(`d7196841`). 교보 상세를 일곱 개 읽고 엑셀 세 줄을 썼다. 1번 줄 주소는 「루키를 위한 길잡이
with 파이썬」(18,000원·1,000P)인데 줄에는 그 페이지 추천 띠의 「파이썬 for Beginner 26,000원」, 적립은 가격×5% 로 **계산**한
「1,300P」. 답은 「모든 가격은 상세 페이지에서 직접 확인」 — 경고 0개. 이름도 금액도 **읽은 글 어딘가에** 있었기 때문이다.

헛경고 쪽은 최근 166판 백테스트에서 본 모양 그대로다(「공고 URL | 주소」 항목표 · 한 글에 사례 여럿 · 괄호 설명 · 판매처 칸 ·
사이트 공통 제목).
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent

_check = BrowserAgent._row_page_binding_check
_money = BrowserAgent._money_grounding_check

ROOKIE = "https://product.kyobobook.co.kr/detail/S000218965804"
HONGONG = "https://product.kyobobook.co.kr/detail/S000061352349"
DOIT = "https://product.kyobobook.co.kr/detail/S000202532365"


def _opened(url: str, title: str) -> dict[str, Any]:
    return {"tool": "browser_extract", "ok": True, "error": "", "evidence": {"url": url, "title": title}}


def _wrote(rows: list[list[Any]]) -> dict[str, Any]:
    return {"tool": "local_write_document", "ok": True, "arguments": {"format": "xlsx", "sheets": {"책": rows}}}


READ = [
    _opened(ROOKIE, "루키를 위한 길잡이 with 파이썬 - 교보문고"),
    _opened(HONGONG, "혼자 공부하는 파이썬 - 교보문고"),
    _opened(DOIT, "Do it! 점프 투 파이썬 - 교보문고"),
]
HEADER = ["순위", "제목", "저자", "판매가", "적립 포인트(율)", "교보문고 URL"]


def test_a_row_copied_from_the_recommendation_strip_is_flagged() -> None:
    steps = [*READ, _wrote([
        HEADER,
        [1, "파이썬 for Beginner", "우재남", "26,000원", "1,300P (5%)", ROOKIE],
        [2, "핵심만 쏙쏙! 쉽게 배우는 파이썬", "양숙희·장은실·오경선", "24,000원", "1,200P (5%)", HONGONG],
        [3, "Do it! 점프 투 파이썬", "박응용", "19,800원", "990P (5%)", DOIT],
    ])]

    note = _check("엑셀로 만들었습니다. 모든 가격은 상세 페이지에서 직접 확인했습니다.", steps)

    assert "「파이썬 for Beginner」 줄의 주소는 「루키를 위한 길잡이 with 파이썬」 페이지" in note
    assert "혼자 공부하는 파이썬" in note
    assert "점프 투" not in note, "맞게 적은 줄까지 몰았다"


def test_rows_that_match_their_pages_stay_quiet() -> None:
    steps = [*READ, _wrote([
        HEADER,
        [1, "루키를 위한 길잡이 with 파이썬", "안형근", "18,000원", "1,000P", ROOKIE],
        [2, "혼자 공부하는 파이썬 (개정판)", "윤인성", "19,800원", "1,100P", HONGONG],
        [3, "**Do it! 점프 투 파이썬**", "박응용", "19,800원", "1,100P", DOIT],
    ])]

    assert _check("", steps) == ""


def test_the_answer_table_is_checked_too() -> None:
    answer = f"| 1 | 파이썬 for Beginner | 26,000원 | [바로가기]({ROOKIE}) |"

    assert "파이썬 for Beginner" in _check(answer, READ)


def test_a_field_value_row_is_not_a_named_row() -> None:
    """「| 공고 URL | https://… |」 — 항목 이름 칸이다(위시켓 판 헛경고)."""
    answer = f"| 항목 | 내용 |\n|---|---|\n| 공고 URL | {ROOKIE} |"

    assert _check(answer, READ) == ""


def test_several_rows_citing_one_article_are_not_flagged() -> None:
    """한 글에 사례가 여럿이면 줄마다 제목과 안 맞는 게 정상이다(「기업 AI 활용 사례 정리」 판)."""
    article = "https://blog.example.com/ai-cases"
    steps = [_opened(article, "기업 AI 활용 사례 정리 : 국내 기업의 주요 도입 영역은?"), _wrote([
        ["사례", "회사", "주소"],
        ["LG유플러스 로밍 챗봇", "LG유플러스", article],
        ["포스코DX 웍스 AI", "포스코DX", article],
    ])]

    assert _check("", steps) == ""


def test_a_note_in_parentheses_does_not_break_the_match() -> None:
    url = "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1"
    steps = [_opened(url, "[(주)솔바람뜰여수] [솔바람뜰 여수 호텔] 재무/회계 경력직 채용 - 사람인"), _wrote([
        ["회사", "직무", "주소"],
        ["(주)솔바람뜰여수 (재무/회계 경력직)", "회계", url],
    ])]

    assert _check("", steps) == ""


def test_a_store_column_is_not_the_item_name() -> None:
    """「| YES24 | 29,700원 | 584쪽 | 주소 |」 — 판매처 칸이다. 호스트 이름과 같다."""
    url = "https://www.yes24.com/product/goods/11681152"
    steps = [_opened(url, "클린 코드"), _wrote([["판매처", "판매가", "쪽수", "주소"], ["YES24", "29,700원", "584쪽", url]])]

    assert _check("", steps) == ""


def test_a_generic_site_title_falls_back_to_the_head_of_the_body() -> None:
    """제목이 사이트 공통 문구면 본문 맨 앞의 주 항목으로 본다 — 추천 띠(뒤쪽)는 여전히 못 빠져나간다."""
    url = "https://job.gwangyang.go.kr/view.do?no=235&pstSn=1820"
    steps = [_opened(url, "스마트 구인구직 플랫폼 굿잡광양 | 일자리정보 | 일자리뉴스"), _wrote([
        ["회사", "직무", "주소"], ["[한길남해항만공사]", "신입 사무", url],
    ])]
    key = BrowserAgent._url_key(url)

    assert _check("", steps, {key: "일자리뉴스 한길남해항만공사 2025년 신입 사무직 채용 공고 …"}) == ""
    assert _check("", steps) != "", "본문이 없으면 제목만으로 판정한다"

    rookie_body = "국내도서 루키를 위한 길잡이 with 파이썬 18,000원 20,000원 통합포인트 1,000 P " + "…" * 2000 + " 파이썬 for Beginner 26,000원"
    copied = [*READ, _wrote([HEADER, [1, "파이썬 for Beginner", "우재남", "26,000원", "1,300P", ROOKIE]])]
    assert "파이썬 for Beginner" in _check("", copied, {BrowserAgent._url_key(ROOKIE): rookie_body}), "추천 띠는 본문 뒤쪽이다"


def test_a_listing_page_row_is_not_checked() -> None:
    search = "https://search.kyobobook.co.kr/search?keyword=파이썬"
    steps = [
        {"tool": "browser_site_search", "ok": True, "evidence": {"url": search, "title": "파이썬 - 통합검색 - 교보문고"}},
        _wrote([["제목", "가격", "주소"], ["파이썬 for Beginner", "26,000원", search]]),
    ]

    assert _check("", steps) == ""


def _read(text: str) -> list[dict[str, Any]]:
    return [{"role": "tool", "tool_name": "browser_extract", "content": text}]


def test_points_are_checked_like_money() -> None:
    """적립을 가격×5% 로 계산해 적었다 — 원문의 적립은 1,000P 다."""
    messages = _read('{"text": "루키를 위한 길잡이 with 파이썬 18,000원 20,000원 통합포인트 1,000 P (5% 적립)"}')

    assert "1,300P" in _money("책 찾아줘", "적립 1,300P (5%)", messages)
    assert _money("책 찾아줘", "적립 1,000P", messages) == ""


def test_a_number_hidden_inside_a_longer_number_is_not_grounded() -> None:
    """990 은 19,900 안에 있다 — 예전엔 그걸로 통과했다."""
    messages = _read('{"text": "정가 19,900원 · 판매가 17,910원"}')

    assert "990" in _money("책 찾아줘", "적립 990P · 가격 17,910원", messages)


def test_a_wrong_row_hiding_behind_a_right_row_on_the_same_address_is_flagged() -> None:
    """★ 2026-09-28 T1 O8(`e8b8e1d9`): 1·2번 줄이 같은 주소를 댔다. 그 페이지는 2번 줄 책(「200제」) 상세였고, 1번 줄(「3학년 머신러닝」)은
    주소만 잘못 옮겼다. 「여러 줄 = 여러 항목 글」 규칙이 둘 다 건너뛰어 경고 0 · verified. 한 줄이 제목과 사실상 같으면 한 상품 페이지다."""
    ml = "https://product.kyobobook.co.kr/detail/S000209068452"
    two_hundred = "https://product.kyobobook.co.kr/detail/S000000833178"
    steps = [
        _opened(ml, "파이썬(Python) 3학년 머신러닝의 구조 - 교보문고"),
        _opened(two_hundred, "초보자를 위한 파이썬(Python) 200제 - 교보문고"),
        _wrote([
            ["제목", "저자", "출판사", "판매가 (원)", "적립 포인트 (P)", "타입", "URL"],
            ["파이썬 3학년 머신러닝의 구조", "김성환 외 지음", "위키북스", "16,200", "900", "국내도서(종이책)", two_hundred],
            ["초보자를 위한 파이썬(Python) 200제", "김민준 외 지음", "에이콘출판", "18,000", "1,000", "국내도서(종이책)", two_hundred],
        ]),
    ]

    note = _check("", steps)

    assert "파이썬 3학년 머신러닝의 구조" in note and "200제" in note
    assert "「초보자를 위한 파이썬(Python) 200제」 줄" not in note


def test_dict_rows_are_checked_too() -> None:
    """★ T1 O16(`f55520bc`): 파일 줄이 사전 모양이라 줄 검사가 그 줄을 못 봤다. 3번 줄은 **열지 않은 책**에 지어낸 주소(Do it! 주소 끝자리만 바꿈).
    답의 3번 줄은 다른 책(맞는 값)이라 답만 보는 검사도 조용했다 — 경고 0 · 거짓 완료."""
    hongong = "https://product.kyobobook.co.kr/detail/S000061352349"
    steps = [
        _opened(DOIT, "Do it! 점프 투 파이썬 - 교보문고"),
        _opened(hongong, "혼자 공부하는 파이썬 - 교보문고"),
        {"tool": "local_write_document", "ok": True, "arguments": {"format": "xlsx", "sheets": {"책": [
            {"ISBN": "9791163842482", "URL": DOIT, "저자": "박응용", "적립포인트": "1,100P (5%)", "제목": "Do it! 점프 투 파이썬", "판매가": "19,800원"},
            {"ISBN": "9791162245651", "URL": hongong, "저자": "윤인성", "적립포인트": "1,100P (5%)", "제목": "혼자 공부하는 파이썬", "판매가": "19,800원"},
            {"ISBN": "9791167530018", "URL": "https://product.kyobobook.co.kr/detail/S000202532366", "저자": "김성현",
             "적립포인트": "1,490P (5%)", "제목": "자동화 프로그래밍 파이어베이스", "판매가": "29,800원"},
        ]}}},
    ]

    note = _check("| 제목 | 판매가 |\n|---|---|\n| Do it! 점프 투 파이썬 | 19,800원 |", steps)

    assert "자동화 프로그래밍 파이어베이스" in note and "S000202532366" in note
    assert "「Do it! 점프 투 파이썬」 줄" not in note


GENSPARK = "https://www.genspark.ai/pricing"
CLAUDE = "https://claude.com/ko/pricing"


def test_plan_rows_of_a_pricing_page_are_not_flagged() -> None:
    """2026-10-02 가격표 판 6cc1590c: 「Genspark | Free | $0 | …/pricing」 세 줄이 첫 칸(사이트 이름)으로는 한 줄로 세어져
    「「Free」 줄의 주소는 「Genspark」 페이지」 헛경고가 났다. 요금제 줄은 그 사이트 가격 페이지의 여러 항목이다."""
    head = ["사이트", "요금제 이름", "월 요금(달러)", "에이전트/브라우저 기능", "확인 주소"]
    steps = [
        _opened(GENSPARK, "Genspark"),
        _opened(CLAUDE, "요금제 | Claude"),
        _wrote([
            head,
            ["Genspark", "Free", "$0", "제한적", GENSPARK],
            ["Genspark", "Plus", "$24.99", "포함", GENSPARK],
            ["Genspark", "Pro", "$249.99", "포함", GENSPARK],
            ["Claude (Anthropic)", "Free", "$0", "아니요", CLAUDE],
            ["Claude (Anthropic)", "Pro", "$20", "Claude Code 포함", CLAUDE],
        ]),
    ]
    assert "줄과 출처 페이지가 안 맞습니다" not in _check("엑셀로 정리했습니다.", steps)


def test_a_wrong_row_among_one_page_rows_is_still_flagged_when_one_row_names_the_page() -> None:
    """반대쪽: 같은 주소 줄 중 하나가 페이지 제목과 같으면 한 상품 페이지다 — 다른 줄이 주소를 잘못 옮긴 것은 그대로 잡는다."""
    steps = [*READ, _wrote([
        HEADER,
        [1, "루키를 위한 길잡이 with 파이썬", "안형근", "18,000원", "1,000P", ROOKIE],
        [2, "파이썬 for Beginner", "우재남", "26,000원", "1,300P", ROOKIE],
    ])]
    assert "「파이썬 for Beginner」 줄의 주소는 「루키를 위한 길잡이 with 파이썬」 페이지" in _check("엑셀로 만들었습니다.", steps)
