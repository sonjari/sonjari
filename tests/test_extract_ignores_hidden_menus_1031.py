"""본문 고르기는 **화면에 보이는 글**로 잰다 (2026-10-31 알라딘 검색 결과 · 판 d5564aae 373초).

알라딘 머리 칸은 보이는 글 198자인데 숨긴 카테고리 메뉴가 18,302자 — 복제본은 숨긴 글까지 세어 머리 칸이 책 목록을 이겼다.
"""
from __future__ import annotations

from test_extract_keeps_cell_boundaries import _extract

MENU = " ".join(f"카테고리{i}" for i in range(1500))   # 숨긴 메뉴 약 1.4만 자
BOOKS = "".join(f"<li>파이썬 책 {i} · 지은이 저자{i} · 판매가 {i},900원 · 정가 {i+1},000원</li>" for i in range(1, 31))
PAGE = f"""<html><head><meta charset="utf-8"></head><body>
<div id="headerTop"><span>로그인 · 장바구니 · 검색</span><div style="display:none"><p>{MENU}</p></div></div>
<div id="leftMenu"><a href="#">국내도서</a> <a href="#">외국도서</a></div>
<div id="Search3_Result"><ul>{BOOKS}</ul></div>
</body></html>"""


def test_a_hidden_menu_does_not_win_over_the_visible_results() -> None:
    text = _extract(PAGE)
    assert "판매가 1,900원" in text and "카테고리100" not in text, text[:300]


def test_a_plain_article_page_still_reads_its_body() -> None:
    """역방향 — 숨긴 것이 없는 평범한 글은 예전처럼 본문을 읽는다."""
    body = "<p>" + "본문 문장입니다. " * 80 + "</p>"
    text = _extract(f"<html><body><div id='nav'><a href='#'>홈</a></div><article>{body}</article></body></html>")
    assert "본문 문장입니다" in text
