"""다나와 · 11번가 · G마켓 상품 페이지의 값은 **도구가** 읽는다 — 가게별 값 규칙 (2026-10-11).

가격 조사 스킬팩을 하루에 열여덟 판 돌리며 본 것:

  - 11번가 줄에 「줄의 값이 그 페이지와 다릅니다 — 첫머리에는 ○○원」이 다섯 번. 다섯 번 다 적은 값은 할인가, 첫머리는 할인 전 값.
    큰 모델은 답에서 반박하며 지켰고 작은 모델은 정가로 고쳐 썼다.
  - 다나와는 본문 앞 5,700~8,200자가 사이트 메뉴다. 「첫머리」에 값이 없다.
  - G마켓의 큰 값은 쿠폰이 있으면 쿠폰가다. 쿠폰을 뺀 값은 페이지 글에 없다.

표본은 그날 보관소에서 받은 실제 페이지의 **구조**를 본떴다(줄바꿈 · 낱말 · 순서). 상품 이름과 값은 지어낸 것이다.
실제 아홉 페이지(세 상품 × 세 가게)에 대어 아홉 개 모두 기대한 값이 나오는 것을 따로 확인했다.

양방향이다 — 읽어야 하는 값과, **읽으면 안 되는 것**(카드 혜택가 · 다른 가게 줄 · 검색 페이지 · 다른 사이트)을 같이 본다.
"""
from __future__ import annotations

from alture_jarvis import page_values

DANAWA = "https://prod.danawa.com/info?pcode=1000001&keyword=%EB%AC%B4%EC%84%A0&cate=112787"
ELEVEN = "https://www.11st.co.kr/products/1000000001?&trTypeCd=MAS114&trCtgrNo=585021"
GMARKET = "https://item.gmarket.co.kr/Item?goodscode=1000000001&utparam-url=%7B%22x%22%3A%221%22%7D"

# 다나와: 값 앞에 사이트 메뉴가 길게 온다. 메뉴 안에도 「최저가」라는 낱말은 있다(숫자는 없다).
_DANAWA_MENU = "가격비교\n장터\nPC견적\n자동차\nNo.1 가격비교사이트 다나와 앱으로\n간편하게 최저가를 확인하세요.\n전체 카테고리\n" * 90
_DANAWA_OFFER = (
    "등록월: 2026.01.\nㅣ\n제조사:\n가상전자\nㅣ\n이미지출처: 가상몰\n최저가\n128,970\n원\n최저가 구매하기\n"
    "멤버십/카드결제 최대 혜택가\n가상페이\n124,000\n원\n멤버십 최대 4,970원 적립 시\n"
    "쇼핑몰별 최저가\n배송비 포함\n최저가\n128,970\n원\n빠른배송\n구매하기\n139,300원\n(무료배송)\n구매하기\n139,700원\n(무료배송)\n"
)
DANAWA_BODY = _DANAWA_MENU + _DANAWA_OFFER

_ELEVEN_TOP = "가상 무선 마우스 M3 블랙\n상품평\n" + "최근 30일동안 가장 저렴한 가격입니다.\n※각 정보는 업데이트 주기가 있어 정보 반영에 시간 차이가 발생할 수 있습니다.\n" * 11
_ELEVEN_NOTICE = (
    "판매가 안내\n상품의 할인 전 판매가격으로, 이 가게에서 상품을 팔려고 입점한 판매자가 등록한 가격(희망소매가격 · 공식판매처의 판매가격 · "
    "농수산물은 시가 등, 도서정가제 대상 도서는 도서 정가)입니다. 해당 가격은 시장 환경에 따라 변동될 수 있습니다. "
    "실제 결제 금액은 할인 조건에 따라 달라질 수 있으니 주문 화면에서 확인하세요.\n"
)
ELEVEN_DISCOUNT = _ELEVEN_TOP + (
    "판매가\n279,290원\n" + _ELEVEN_NOTICE
    + "가격정보\n할인율\n17%\n229,020\n원\n최대할인 판매가\n할인율\n18%\n226,730\n원\n할인 안내\n최대할인가\n판매가\n279,290원\n-50,270원\n"
    "카드/페이할인 안내\n-2,290원\n최대 3%, 가상페이\n최대할인가\n226,730원\n"
)
ELEVEN_PLAIN = _ELEVEN_TOP + (
    "가격정보\n139,700\n원\n판매가 안내\n상품의 할인 전 판매가격으로, 입점판매자가 등록한 가격입니다.\n"
    "최대할인 판매가\n138,310\n원\n할인 안내\n최대할인가\n판매가\n139,700원\n카드/페이할인 안내\n-1,390원\n최대할인가\n138,310원\n"
)

_GMARKET_TOP = "상품평 삭제와 관련한 문의 및 이의 제기 등은 고객센터를 통해 요청하시면 확인 후 회신해드립니다.\n상품평 문의\n고객센터 바로가기\n" * 4
_GMARKET_NOTE = "판매자 혹은 G마켓의 할인이 적용된 가격입니다. 판매자 혹은 G마켓의 설정에 따라 변동될 수 있습니다.\n"
GMARKET_COUPON = _GMARKET_TOP + (
    "할인률\n18%\n기존가\n270,570원\n가격 안내\n판매가\n판매자가 할인 적용 이전 기준으로 등록한 금액입니다.\n할인가\n" + _GMARKET_NOTE
    + "219,540원\n상세내역\n판매가\n270,570원\n판매자할인\n-21,100원\n[10월] 12% 할인쿠폰\n-29,930원\n쿠폰가\n219,540원\n최대\n24,390원\n적립\n"
)
GMARKET_NO_COUPON = _GMARKET_TOP + (
    "할인률\n6%\n기존가\n815,050원\n가격 안내\n판매가\n판매자가 할인 적용 이전 기준으로 등록한 금액입니다.\n할인가\n" + _GMARKET_NOTE
    + "758,000원\n할인가\n상세내역\n판매가\n815,050원\nG마켓 추가할인\n-57,050원\n할인가\n758,000원\n704,940원결제할인가\n"
)
GMARKET_COUPON_ONLY = _GMARKET_TOP + (
    "할인률\n1%\n기존가\n139,300원\n가격 안내\n판매가\n판매자가 할인 적용 이전 기준으로 등록한 금액입니다. 가격이 달라질 수 있습니다.\n"
    "136,520원\n상세내역\n판매가\n139,300원\n2% 깜짝쿠폰\n-2,780원\n쿠폰가\n136,520원\n최대\n16,382원\n적립\n"
)


def _digits(url: str, body: str) -> dict[str, str]:
    return {name: value["digits"] for name, value in page_values.extract(url, body).items()}


# --- 다나와 -----------------------------------------------------------------------

def test_danawa_reads_the_lowest_price_past_the_site_menu() -> None:
    assert len(_DANAWA_MENU) > 5_000, "표본의 메뉴가 실제만큼 길어야 한다 — 값은 첫머리 900자 밖이다"
    assert "128,970" not in DANAWA_BODY[:900]

    assert _digits(DANAWA, DANAWA_BODY) == {"sale_price": "128970"}


def test_danawa_does_not_take_the_card_price_or_another_shops_row() -> None:
    values = _digits(DANAWA, DANAWA_BODY)

    assert "124000" not in values.values(), "멤버십·카드 혜택가는 누구나 받는 값이 아니다"
    assert "139300" not in values.values() and "139700" not in values.values(), "쇼핑몰별 목록의 다른 가게 값"


def test_danawa_without_the_buy_button_reads_nothing() -> None:
    """단추가 없으면(목록 · 품절 등 모양이 다르면) 모른다 — 「쇼핑몰별 최저가」 목록의 값을 대신 집지 않는다."""
    body = _DANAWA_MENU + "쇼핑몰별 최저가\n배송비 포함\n최저가\n128,970\n원\n빠른배송\n"

    assert _digits(DANAWA, body) == {}


# --- 11번가 -----------------------------------------------------------------------

def test_eleventh_street_reads_the_discounted_price_not_the_price_before_it() -> None:
    assert ELEVEN_DISCOUNT.index("279,290") < 900 < ELEVEN_DISCOUNT.index("229,020"), (
        "그날의 모양이어야 한다 — 할인 전 값은 첫머리 900자 안에, 할인된 값은 그 밖에 있다"
    )

    assert _digits(ELEVEN, ELEVEN_DISCOUNT) == {"sale_price": "229020", "list_price": "279290"}


def test_eleventh_street_does_not_take_the_card_discount_price() -> None:
    assert "226730" not in _digits(ELEVEN, ELEVEN_DISCOUNT).values(), "「최대할인 판매가」는 카드·페이 할인까지 넣은 값이다"
    assert "138310" not in _digits(ELEVEN, ELEVEN_PLAIN).values()


def test_eleventh_street_without_a_discount_reads_the_one_price() -> None:
    assert _digits(ELEVEN, ELEVEN_PLAIN) == {"sale_price": "139700", "list_price": "139700"}


def test_eleventh_street_search_pages_are_not_product_pages() -> None:
    assert _digits("https://search.11st.co.kr/pc/total-search?kwd=x", ELEVEN_DISCOUNT) == {}


# --- G마켓 ------------------------------------------------------------------------

def test_gmarket_says_when_the_big_price_is_the_coupon_price() -> None:
    values = _digits(GMARKET, GMARKET_COUPON)

    assert values == {"shown_price": "219540", "list_price": "270570", "coupon_price": "219540"}
    assert values["shown_price"] == values["coupon_price"], "둘이 같으면 화면의 값은 쿠폰을 넣은 값이다"


def test_gmarket_without_a_coupon_has_no_coupon_price() -> None:
    assert _digits(GMARKET, GMARKET_NO_COUPON) == {"shown_price": "758000", "list_price": "815050"}


def test_gmarket_with_only_a_coupon_reads_the_same_way() -> None:
    assert _digits(GMARKET, GMARKET_COUPON_ONLY) == {"shown_price": "136520", "list_price": "139300", "coupon_price": "136520"}


def test_gmarket_never_names_a_sale_price() -> None:
    """쿠폰을 뺀 값은 페이지 글에 없다 — 도구가 표의 판매가 칸을 고칠 근거가 없으니 그 이름으로는 아무것도 안 준다."""
    for body in (GMARKET_COUPON, GMARKET_NO_COUPON, GMARKET_COUPON_ONLY):
        assert "sale_price" not in page_values.extract(GMARKET, body)


# --- 가게가 아니면 ----------------------------------------------------------------

def test_the_same_text_on_another_site_reads_nothing() -> None:
    for body in (DANAWA_BODY, ELEVEN_DISCOUNT, GMARKET_COUPON):
        assert page_values.extract("https://shop.example/products/1", body) == {}


def test_the_line_the_model_gets_names_each_value() -> None:
    line = page_values.describe(page_values.extract(GMARKET, GMARKET_COUPON))

    assert line == "화면에 보이는 값 219,540원 · 기존가 270,570원 · 쿠폰가(쿠폰을 넣은 값) 219,540원"
    assert page_values.describe(page_values.extract(DANAWA, DANAWA_BODY)) == "최저가 128,970원"
    assert page_values.describe(page_values.extract(ELEVEN, ELEVEN_DISCOUNT)).startswith("판매가(할인 적용 · 카드·페이 할인 제외) 229,020원")
