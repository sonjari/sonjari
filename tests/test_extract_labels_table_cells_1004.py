"""머리줄이 있는 표는 줄마다 한 줄로, 칸마다 머리말을 붙여 읽는다 (2026-10-04 허깅페이스 판 5749ff16).

모델 카드의 벤치마크 표가 「Type / Model / Size / WikiText-2 / C4 / IQ2_XXS / … / 6.68 / 11.03」 — 칸마다 한 줄로 풀려 왔다.
모델은 다섯 줄씩 세어 열을 맞춰야 했고, 엑셀 다섯 줄 중 셋에서 C4 값을 WikiText-2 라고 적거나 옆 줄 값을 섞었다.
숫자는 전부 「읽은 적 있는」 숫자라 근거 검사로는 못 잡는다 — 읽을 때 칸과 머리말을 묶어 주는 수밖에 없다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.browser import _EXTRACT_MAIN_JS, _clean_lines

# 허깅페이스 카드처럼: 칸 사이에 줄바꿈이 있고, 칸을 블록으로 그리는 스타일이 걸려 있다.
CARD_LIKE = """
<html><head><style>td, th { display: block; }</style></head><body><main>
<h2>Perplexity (lower is better)</h2>
<table>
<thead><tr>
<th>Type</th>
<th>Model</th>
<th>Size</th>
<th>WikiText-2</th>
<th>C4</th>
</tr></thead>
<tbody>
<tr>
<td>IQ2_XXS</td>
<td><strong>DASH-Q IQ2_XXS</strong></td>
<td><strong>10.92 GB</strong></td>
<td><strong>6.68</strong></td>
<td><strong>11.03</strong></td>
</tr>
<tr>
<td>IQ2_M</td>
<td>llama.cpp IQ2_M (imatrix)</td>
<td>12.14 GB</td>
<td>7.33</td>
<td>11.13</td>
</tr>
</tbody>
</table>
<p>""" + "llama-perplexity, context 2048; WikiText-2 test, C4 validation. " * 6 + """</p>
</main></body></html>
"""

LAYOUT_TABLE = """
<html><body><main>
<table><tr><td>
<h3>공지</h3>
<p>첫째 문단입니다.</p>
<p>둘째 문단입니다.</p>
</td><td>
<p>오른쪽 칸의 글입니다.</p>
</td></tr></table>
<p>""" + "본문이 이어집니다. " * 20 + """</p>
</main></body></html>
"""

ROW_HEADED = (
    "<html><body><main><h2>모집요강</h2>"
    "<table><tr><th>급여</th><td>회사내규에 따름</td></tr><tr><th>마감일</th><td>2026.10.15</td></tr></table>"
    "<p>" + "회계 담당자를 모집합니다. " * 12 + "</p></main></body></html>"
)

GROUPED_HEADER = """
<html><body><main>
<table>
<tr><th colspan="2">2025</th><th colspan="2">2026</th></tr>
<tr><td>매출</td><td>120</td><td>매출</td><td>150</td></tr>
</table>
<p>""" + "실적 표의 설명이 이어집니다. " * 12 + """</p>
</main></body></html>
"""


def _extract(html: str) -> str:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.set_content(html)
            found = page.evaluate(_EXTRACT_MAIN_JS)
            return _clean_lines(found["text"], 10_000)
        finally:
            browser.close()


def test_a_headed_table_reads_one_row_per_line_with_each_cell_labelled() -> None:
    lines = _extract(CARD_LIKE).splitlines()

    assert "Type | Model | Size | WikiText-2 | C4" in lines
    assert "Type: IQ2_XXS | Model: DASH-Q IQ2_XXS | Size: 10.92 GB | WikiText-2: 6.68 | C4: 11.03" in lines
    assert "Type: IQ2_M | Model: llama.cpp IQ2_M (imatrix) | Size: 12.14 GB | WikiText-2: 7.33 | C4: 11.13" in lines
    assert "11.03" not in lines, "칸 하나가 한 줄로 떨어지면 모델이 열을 세어 맞춰야 한다"


def test_a_layout_table_keeps_its_lines() -> None:
    """th 없는 표는 배치용이다 — 그 안의 문단을 한 줄로 뭉개지 않는다."""
    lines = _extract(LAYOUT_TABLE).splitlines()

    assert "첫째 문단입니다." in lines and "둘째 문단입니다." in lines
    assert not any(" | " in line for line in lines)


def test_a_table_with_row_headers_is_left_as_it_was() -> None:
    """줄 머리(th)와 값(td)이 짝인 표는 이미 「급여 회사내규에 따름」 한 줄이다(10-02) — 건드리지 않는다."""
    lines = _extract(ROW_HEADED).splitlines()

    assert "급여 회사내규에 따름" in lines


def test_a_grouped_header_is_not_guessed() -> None:
    """머리줄이 칸을 묶으면(colspan) 어느 값이 어느 머리말 것인지 모른다 — 모르면 붙이지 않는다."""
    text = _extract(GROUPED_HEADER)

    assert "2025: " not in text and "2026: " not in text
    assert "120" in text and "150" in text


# --- 머리칸 없는 표 · 본문 자리의 큰 그림 (2026-10-04 사람인 공고 21개 실측) -------------------

TH_LESS_GRID = """
<html><head><style>td { display: block; }</style></head><body><main>
<table><tr><td>
  <table>
  <tr><td>분류</td><td>담당업무</td><td>근무지</td></tr>
  <tr><td>경력</td><td>글로벌 영업</td><td>서울</td></tr>
  <tr><td>신입</td><td>재무 회계</td><td>대전</td></tr>
  </table>
</td></tr></table>
<p>""" + "지원 자격과 전형 절차 안내가 이어집니다. " * 10 + """</p>
</main></body></html>
"""

PICTURE_BODY = (
    "<html><body><main><h2>상세요강</h2>"
    "<img width='860' height='1100' src='data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA='>"
    "<img width='24' height='24' src='data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA='>"
    "<p>" + "아래 그림을 참고해 지원해 주세요. " * 8 + "</p></main></body></html>"
)


def _found(html: str) -> dict:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.set_content(html)
            return page.evaluate(_EXTRACT_MAIN_JS)
        finally:
            browser.close()


def test_a_grid_without_any_header_cell_still_reads_one_row_per_line() -> None:
    """회사가 `<td>` 만으로 짠 공고 표 — 머리말은 못 붙여도(어느 줄이 머리줄인지 모른다) 줄은 지킨다. 안쪽 표만."""
    lines = _clean_lines(_found(TH_LESS_GRID)["text"], 10_000).splitlines()

    assert "분류 | 담당업무 | 근무지" in lines
    assert "경력 | 글로벌 영업 | 서울" in lines and "신입 | 재무 회계 | 대전" in lines
    assert "글로벌 영업" not in lines, "칸 하나가 한 줄로 떨어지지 않는다"


def test_pictures_where_the_body_should_be_are_counted_by_shape() -> None:
    found = _found(PICTURE_BODY)

    assert found["big_images"] == 1 and found["tall_images"] == 1, "아이콘(24×24)은 세지 않는다 · 세로로 긴 그림은 따로"


SUMMARY_THEN_PICTURE = (
    "<html><body><div id='content'>"
    "<div class='summary'><h2>핵심 정보</h2><p>" + "근무형태 정규직 수습기간 3개월 급여 면접 후 결정 근무지역 서울 서초구. " * 8 + "</p></div>"
    "<div class='user_content'><img width='765' height='1800' src='data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA='></div>"
    "</div></body></html>"
)


def test_a_picture_outside_the_chosen_block_is_still_counted() -> None:
    """실전 첫 판(9cbe4dde)의 통이미지 공고 — 고른 덩어리는 위쪽 요약이고 그림(765×8501)은 그 밖의 본문 자리에 있었다."""
    found = _found(SUMMARY_THEN_PICTURE)

    assert "user_content" not in found["selector"]
    assert found["tall_images"] == 1
