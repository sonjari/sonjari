"""가게 이름이 첫 칸이 아닌 표도 그 가게의 줄로 센다 (2026-10-15 · 눈금 거짓말).

가격 판 price1015c 2판: 답이 「가게(판매처) | 사이트 | 상품 이름 | 판매 가격 | 배송비 | 주소」 — 첫 칸이 판매처(Y SHOP),
가게 이름(다나와)은 둘째 칸이었다. 세 줄이 다 있는데 채점(`grade_price_rows`)이 첫 칸만 보고 「줄 없음」 0/3 으로 찍었다.

지키는 약속(`measure_kit.row_shop`):
- 가게 이름이 처음 나오는 칸으로 그 줄의 가게를 정한다.
- 주소 칸으로는 정하지 않는다 — 다른 가게 주소를 적은 줄은 여전히 「주소 틀림」이어야 한다.
"""

from __future__ import annotations

from alture_jarvis.measure_kit import grade_price_rows, row_shop

HEAD = ["가게", "사이트", "상품 이름", "판매 가격", "배송비", "읽은 페이지 주소"]
PAGES = [{"url": "https://prod.danawa.com/info?pcode=1", "text": "최저가 219,720원"},
         {"url": "https://www.11st.co.kr/products/9", "text": "232,170원"}]


def test_the_shop_in_the_second_cell_is_found() -> None:
    rows = [HEAD,
            ["Y SHOP", "다나와", "버즈3 프로", "219,720원", "무료", "https://prod.danawa.com/info?pcode=1"],
            ["셀러허브", "11번가", "버즈3 프로", "232,170원", "무료", "https://www.11st.co.kr/products/9"]]
    graded = grade_price_rows(rows, PAGES)
    assert graded["다나와"] == "온전"
    assert graded["11번가"] == "온전"
    assert graded["G마켓"] == "줄 없음"


def test_the_address_cell_does_not_decide_the_shop() -> None:
    assert row_shop(["판매처", "https://prod.danawa.com/info?pcode=1"]) == ""


def test_a_row_naming_one_shop_with_another_shops_address_is_still_a_wrong_address() -> None:
    rows = [["가게", "판매 가격", "주소"], ["G마켓", "174,440원", "https://prod.danawa.com/info?pcode=1"]]
    assert grade_price_rows(rows, PAGES)["G마켓"] == "주소 틀림"


def test_a_price_column_headed_sale_price_is_read() -> None:
    """머리가 「판매가」인 표(price1015c 2판 스위치)도 값 칸을 찾는다 — 「가격」만 찾아 상품명 칸을 읽고 0/3 이었다."""
    rows = [["쇼핑몰", "판매자", "상품명", "판매가", "배송비", "확인한 페이지"],
            ["다나와", "490몰", "스위치2 본체", "219,720원", "무료", "https://prod.danawa.com/info?pcode=1"]]
    assert grade_price_rows(rows, PAGES)["다나와"] == "온전"


def test_a_list_price_column_is_not_the_price() -> None:
    from alture_jarvis.measure_kit import price_column

    assert price_column(["가게", "정가", "판매 가격"]) == 2


def test_an_address_written_without_the_scheme_is_still_an_address() -> None:
    """`prod.danawa.com/info/?pcode=…` 처럼 `https://` 없이 적은 주소도 주소다(price1015c 3판 마우스 · 세 줄 다 맞는데 0/3)."""
    rows = [HEAD, ["Y SHOP", "다나와", "버즈3 프로", "219,720원", "무료", "prod.danawa.com/info?pcode=1"]]
    assert grade_price_rows(rows, PAGES)["다나와"] == "온전"


def test_a_shop_name_or_a_price_is_not_an_address() -> None:
    from alture_jarvis.measure_kit import is_address

    assert not is_address("다나와")
    assert not is_address("219,720원")
    assert not is_address("G마켓 (해외직구)")
    assert is_address("www.11st.co.kr/products/8852665861")


def test_an_address_with_a_note_after_it_is_still_an_address() -> None:
    from alture_jarvis.measure_kit import is_address

    assert is_address("https://item.gmarket.co.kr/Item?goodscode=4861495811 (정가 319,000원 → 할인)")
