"""표의 판매가·적립 칸은 **도구가** 연 페이지 첫머리에서 채운다 — 동결 예외 A(2026-09-28 대표 결정).

★ 헤르메스 대결 T1: 「쓰는 순간 되돌리기」가 울린 3판(O10·O11·O13) 모두 정답 0. 모델은 되돌림을 받으면 「확인 불가」로 쓰거나
가격×5% 로 계산했다. 값은 `recipes/page_values/kyobobook.json` 으로 도구가 읽는다. 고치는 조건은 좁다 — 이름으로 한 페이지에만
묶이고, 레시피가 그 값을 뽑았을 때만. 모르면 안 고친다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

from alture_jarvis import page_values
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.documents import write_document

ML = "https://product.kyobobook.co.kr/detail/S000209068452"
TWO_HUNDRED = "https://product.kyobobook.co.kr/detail/S000000833178"
MAYA = "https://ebook-product.kyobobook.co.kr/dig/epd/ebook/E000006025402"
NO_SALE = "https://product.kyobobook.co.kr/detail/S000202666213"

# 09-28 운영 보관소에서 받은 실제 첫머리(요약). 앞의 「국내도서·외국도서·eBook」 가격 줄이 모델을 헷갈리게 한 자리다.
BODIES = {
    ML: "국내도서컴퓨터/IT파이썬(Python) 3학년 머신러닝의 구조국내도서16,200원외국도서23,410원eBook12,960원성안당"
        "미리보기10%16,200원18,000원통합포인트900P(5% 적립)5만원 이상 구매 시",
    TWO_HUNDRED: "국내도서컴퓨터/IT초보자를 위한 파이썬(Python) 200제국내도서18,000원eBook12,600원장삼용정보문화사"
                 "미리보기10%18,000원20,000원통합포인트1,000P(5% 적립)",
    MAYA: "eBook IT/프로그래밍 마야 파이썬 2024 신동선 e퍼플 종이책 25,000원 소장 10% 17,100 원 통합포인트 5%적립",
    NO_SALE: "국내도서컴퓨터/IT파이썬으로 쉽게 배우는 자료구조개정판최영규 29,000원 통합포인트870P(3% 적립)",
}
TITLES = {
    ML: "파이썬(Python) 3학년 머신러닝의 구조 - 교보문고",
    TWO_HUNDRED: "초보자를 위한 파이썬(Python) 200제 - 교보문고",
    MAYA: "마야 파이썬 2024 | 신동선 | e퍼플 - 교보ebook",
    NO_SALE: "파이썬으로 쉽게 배우는 자료구조 - 교보문고",
}


class _Store:
    def __init__(self) -> None:
        self.by_step: dict[int, str] = {}

    def get(self, job_id: str, step: int) -> dict[str, Any] | None:
        text = self.by_step.get(step)
        return {"payload": {"text": text}} if text else None


def _agent() -> tuple[BrowserAgent, list[dict[str, Any]]]:
    agent = object.__new__(BrowserAgent)
    store = _Store()
    agent.observations = store
    steps: list[dict[str, Any]] = []
    for number, url in enumerate(BODIES, start=1):
        store.by_step[number] = BODIES[url]
        steps.append({
            "step": number, "tool": "browser_extract", "ok": True,
            "evidence": {"url": url, "title": TITLES[url]},
            "evidence_record": {"type": "body_read", "ok": True, "source_id": url, "step": number, "job_id": "j"},
        })
    return agent, steps


def _write(agent: BrowserAgent, steps: list[dict[str, Any]], target: Path, rows: list[list[Any]]) -> str:
    arguments = {"format": "xlsx", "path": target.name, "sheets": {"책": rows}}
    write_document(target, "xlsx", dict(arguments))
    # ★ 실제 모양: 도구 결과(observation)에는 경로가 없고, 걸음 증거에 `output_path` 가 있다(T1 O14 — `path` 만 봐서 라이브에서 0칸).
    steps.append({"step": len(steps) + 1, "tool": "local_write_document", "ok": True, "arguments": arguments,
                  "evidence": {"action": "local_write_document", "format": "xlsx", "output_path": str(target), "verified": True}})
    return agent._fill_values_from_pages("local_write_document", {"ok": True}, steps, "j")


def _cells(target: Path) -> list[list[Any]]:
    return [[cell.value for cell in row] for row in openpyxl.load_workbook(target).active.iter_rows()]


def test_the_recipe_reads_the_main_offer_not_the_other_editions() -> None:
    values = page_values.extract(ML, BODIES[ML])

    assert page_values.describe(values) == "판매가 16,200원 · 정가 18,000원 · 적립 900P"


def test_a_page_without_a_discount_block_leaves_the_price_unknown() -> None:
    """할인 덩어리가 없으면 판매가를 **안 뽑는다** — 모르면 안 고친다."""
    assert "sale_price" not in page_values.extract(NO_SALE, BODIES[NO_SALE])


def test_wrong_and_unknown_cells_are_filled_from_the_page(tmp_path: Path) -> None:
    """O13: 적립 칸이 「확인 불가 (12,960원 표시)」 · 답은 12,960P(eBook 가격). O11: 적립을 가격×5% 로 계산."""
    agent, steps = _agent()
    target = tmp_path / "책.xlsx"

    note = _write(agent, steps, target, [
        ["순위", "제목", "판매가", "적립 포인트"],
        ["1", "파이썬(Python) 3학년 머신러닝의 구조", "16,200원", "확인 불가 (12,960원 표시)"],
        ["2", "초보자를 위한 파이썬(Python) 200제", "12,600원", "630P (5%)"],
        ["3", "마야 파이썬 2024 (eBook)", "17,100원", "확인 불가"],
    ])

    rows = _cells(target)
    assert rows[1][3] == "900P"
    assert rows[2][2] == "18,000원" and rows[2][3] == "1,000P"
    assert rows[3][3] == "확인 불가", "그 페이지는 적립을 %로만 적는다 — 모르는 칸은 그대로"
    assert "3칸" in note and "다시 쓰지 마라" in note
    assert steps[-1]["values_filled"] == 3


def test_right_cells_are_left_alone(tmp_path: Path) -> None:
    agent, steps = _agent()

    note = _write(agent, steps, tmp_path / "책.xlsx", [
        ["제목", "판매가", "적립"],
        ["파이썬(Python) 3학년 머신러닝의 구조", "16,200원", "900P (5%)"],
        ["초보자를 위한 파이썬(Python) 200제", 18000, 1000],
    ])

    assert note == ""


def test_a_row_whose_name_does_not_match_any_page_is_not_touched(tmp_path: Path) -> None:
    """O8: 주소만 옆 줄 것으로 옮긴 줄 · O10: 열지 않은 책. 이름으로 묶이지 않으면 안 고친다(경고는 대조가 따로 낸다)."""
    agent, steps = _agent()
    target = tmp_path / "책.xlsx"

    note = _write(agent, steps, target, [
        ["제목", "판매가", "적립", "URL"],
        ["파이썬 완전 정복", "35,200원", "1,760P", TWO_HUNDRED],
    ])

    assert note == "" and _cells(target)[1][1] == "35,200원"


def test_header_and_rows_sheet_shape_is_filled_too(tmp_path: Path) -> None:
    """O10 이 보낸 모양 `{"header": [...], "rows": [...]}` 도 채운다."""
    agent, steps = _agent()
    target = tmp_path / "책.xlsx"
    arguments = {"format": "xlsx", "sheets": {"책": {"header": ["책 제목", "판매가", "적립 포인트"],
                                                   "rows": [["초보자를 위한 파이썬(Python) 200제", "확인 필요", "확인 필요"]]}}}
    write_document(target, "xlsx", dict(arguments))
    steps.append({"step": 9, "tool": "local_write_document", "ok": True, "arguments": arguments,
                  "evidence": {"output_path": str(target)}})

    note = agent._fill_values_from_pages("local_write_document", {"ok": True}, steps, "j")

    assert "2칸" in note
    assert _cells(target)[1] == ["초보자를 위한 파이썬(Python) 200제", "18,000원", "1,000P"]


def test_a_non_table_document_is_not_touched(tmp_path: Path) -> None:
    agent, steps = _agent()
    steps.append({"step": 9, "tool": "local_write_document", "ok": True, "arguments": {"format": "docx", "blocks": []}})

    assert agent._fill_values_from_pages("local_write_document", {"ok": True, "path": str(tmp_path / "a.docx")}, steps, "j") == ""


DOIT = "https://product.kyobobook.co.kr/detail/S000202532365"


def test_the_exact_o14_write_is_fixed(tmp_path: Path) -> None:
    """★ T1 O14 의 실제 쓰기 인자 그대로(줄이 사전 · 열쇠 순서가 가나다). 라이브에서는 경로를 못 찾아 0칸이었다."""
    agent, steps = _agent()
    agent.observations.by_step[len(steps) + 1] = (
        "국내도서컴퓨터/IT프로그래밍 언어Python(파이썬)Do it! 점프 투 파이썬국내도서19,800원eBook13,500원박응용이지스퍼블리싱"
        "미리보기10%19,800원22,000원통합포인트1,100P(5% 적립)"
    )
    steps.append({"step": len(steps) + 1, "tool": "browser_extract", "ok": True,
                  "evidence": {"url": DOIT, "title": "Do it! 점프 투 파이썬 - 교보문고"},
                  "evidence_record": {"type": "body_read", "ok": True, "source_id": DOIT, "step": len(steps) + 1, "job_id": "j"}})
    target = tmp_path / "파이썬 책 3권 (5).xlsx"
    arguments = {"format": "xlsx", "path": "파이썬 책 3권.xlsx", "sheets": {"파이썬 책": [
        {"ISBN": "9791163034735", "교보문고URL": DOIT, "서열": "1", "저자": "박응용", "적립포인트": "10% (1,980P)",
         "제목": "Do it! 점프 투 파이썬", "출판사": "이지스퍼블리싱", "판매가": "19,800원"},
        {"ISBN": "9791160468711", "교보문고URL": TWO_HUNDRED, "서열": "2", "저자": "장삼용", "적립포인트": "5% (900P)",
         "제목": "초보자를 위한 파이썬(Python) 200제", "출판사": "정보문화사", "판매가": "27,500원"},
    ]}}
    write_document(target, "xlsx", dict(arguments))
    steps.append({"step": len(steps) + 1, "tool": "local_write_document", "ok": True, "arguments": arguments,
                  "evidence": {"action": "local_write_document", "output_path": str(target), "rows": 3, "verified": True}})

    note = agent._fill_values_from_pages("local_write_document", {"ok": True}, steps, "j")

    rows = _cells(target)
    head = rows[0]
    assert rows[1][head.index("적립포인트")] == "1,100P"
    assert rows[2][head.index("판매가")] == "18,000원" and rows[2][head.index("적립포인트")] == "1,000P"
    assert "3칸" in note


def test_a_row_carrying_the_next_rows_address_gets_its_own_address(tmp_path: Path) -> None:
    """★ T1 O18(`8f267e1c`) 실제 인자: 1번 줄(3학년 머신러닝)의 주소가 2번 줄 책(200제) 페이지. 값은 맞았는데 주소만 옆 줄 것 —
    O8·O15 도 같은 모양. 이름으로 한 페이지에만 묶인 줄이니 주소도 그 페이지로 바로잡는다."""
    agent, steps = _agent()
    target = tmp_path / "교보문고 파이썬 책 3권 (6).xlsx"
    arguments = {"format": "xlsx", "sheets": {"파이썬 책": [
        {"URL": TWO_HUNDRED, "저자": "김태우", "적립 포인트": "900P", "제목": "파이썬(Python) 3학년 머신러닝의 구조", "출판사": "한빛미디어", "판매가": "16,200원"},
        {"URL": TWO_HUNDRED, "저자": "이강철 외", "적립 포인트": "1,000P", "제목": "초보자를 위한 파이썬(Python) 200제", "출판사": "위키북스", "판매가": "18,000원"},
    ]}}
    write_document(target, "xlsx", dict(arguments))
    steps.append({"step": 9, "tool": "local_write_document", "ok": True, "arguments": arguments,
                  "evidence": {"output_path": str(target)}})

    note = agent._fill_values_from_pages("local_write_document", {"ok": True}, steps, "j")

    rows = _cells(target)
    head = rows[0]
    assert rows[1][head.index("URL")] == ML, "1번 줄은 그 책(3학년) 주소로"
    assert rows[2][head.index("URL")] == TWO_HUNDRED, "맞는 줄은 그대로"
    assert "주소" in note and "1칸" in note
    assert BrowserAgent._row_page_binding_check("", steps) == "", "고친 뒤에는 줄↔페이지 경고가 없어야"


def test_a_rate_column_is_never_overwritten(tmp_path: Path) -> None:
    """★ T1 O21(`4f556d8f`): 「적립률」 칸의 맞는 값 5% 를 「적립」 글자만 보고 900P 로 덮었다 — 도구가 만든 틀림. 비율 칸은 안 건드린다."""
    agent, steps = _agent()
    target = tmp_path / "책.xlsx"

    note = _write(agent, steps, target, [
        ["제목", "판매가", "적립포인트", "적립률", "할인율(%)"],
        ["파이썬(Python) 3학년 머신러닝의 구조", "16,200원", "810P", "5%", "10%"],
    ])

    rows = _cells(target)
    assert rows[1] == ["파이썬(Python) 3학년 머신러닝의 구조", "16,200원", "900P", "5%", "10%"]
    assert "1칸" in note


def test_a_rate_only_page_turns_a_borrowed_point_amount_into_the_rate(tmp_path: Path) -> None:
    """★ T1 O22(`7d374c2f`): 마야 파이썬 eBook 페이지는 적립을 「5%적립」으로만 적는다. 표에 옆 책(200제)의 1,000P — 경고 0.
    값 채우기는 그 칸을 비율로 고치고, 경고 쪽도 「포인트 금액 없음」으로 짚는다."""
    agent, steps = _agent()
    target = tmp_path / "책.xlsx"
    rows = [["순위", "제목", "판매가", "적립 포인트"], ["3", "마야 파이썬 2024", "17,100원", "1,000P (5% eBook 기준)"]]

    wrong = BrowserAgent._row_value_mismatch(rows[1], "마야 파이썬 2024", BODIES[MAYA])
    assert wrong is not None and "1,000P" in wrong[0] and "포인트 금액 없음" in wrong[1]

    note = _write(agent, steps, target, rows)

    assert _cells(target)[1][3] == "5% 적립"
    assert "비율만" in note


def test_the_recipe_reads_the_rate_on_an_ebook_page() -> None:
    assert page_values.describe(page_values.extract(MAYA, BODIES[MAYA])) == "판매가 17,100원 · 적립률 5%"


def test_a_points_column_marked_with_percent_is_still_a_points_column(tmp_path: Path) -> None:
    """★ T1 O24(`3a6e03a8`): 머리말 「적립 포인트(%)」 — O21 을 막으려던 비율 규칙이 % 만 보고 건너뛰어 혼공 「미확인」을 못 채웠다.
    「적립률」·「할인율(%)」은 여전히 안 건드린다."""
    agent, steps = _agent()
    target = tmp_path / "책.xlsx"

    note = _write(agent, steps, target, [
        ["제목", "판매가", "적립 포인트(%)", "적립률", "할인율(%)"],
        ["초보자를 위한 파이썬(Python) 200제", "18,000원", "미확인", "5%", "10%"],
    ])

    assert _cells(target)[1] == ["초보자를 위한 파이썬(Python) 200제", "18,000원", "1,000P", "5%", "10%"]
    assert "1칸" in note


def test_a_rate_only_page_fixes_a_points_cell_written_in_won(tmp_path: Path) -> None:
    """★ T1 O25(`6a73b55f`): 마야 eBook 적립을 「855원 (5%)」 — 단위가 원이라 P 만 보던 조건이 못 고쳤다."""
    agent, steps = _agent()
    target = tmp_path / "책.xlsx"

    note = _write(agent, steps, target, [["순위", "제목", "판매가", "적립 포인트"], ["3", "마야 파이썬 2024", "17,100원", "855원 (5%)"]])

    assert _cells(target)[1][3] == "5% 적립"
    assert "비율만" in note


def test_a_rate_only_page_leaves_a_plain_rate_cell_alone(tmp_path: Path) -> None:
    """이미 비율로 적은 칸(「5% (통합포인트)」 — O5·O20 모양)은 그대로 둔다."""
    agent, steps = _agent()

    note = _write(agent, steps, tmp_path / "책.xlsx", [["제목", "판매가", "적립 포인트"], ["마야 파이썬 2024", "17,100원", "5% (통합포인트)"]])

    assert note == ""


def test_a_shortened_title_is_still_bound_by_its_words(tmp_path: Path) -> None:
    """★ T1 O27·O28: 「Python 머신러닝의 구조」(실제 「파이썬(Python) 3학년 머신러닝의 구조」) — 두 판 연속. 못 묶어서 O28 의 28,000원을 못 고쳤다."""
    agent, steps = _agent()
    target = tmp_path / "책.xlsx"

    note = _write(agent, steps, target, [["순위", "제목", "판매가", "적립 포인트"], ["1", "Python 머신러닝의 구조", "28,000원", "5%"]])

    assert _cells(target)[1] == [1, "Python 머신러닝의 구조", "16,200원", "900P"]
    assert "2칸" in note


def test_words_are_not_enough_when_they_fit_two_pages() -> None:
    """낱말이 여러 페이지 제목에 다 들어가면 묶지 않는다(한 페이지에만 — 부르는 쪽 조건). 낱말 하나뿐인 이름도 묶지 않는다."""
    assert BrowserAgent._name_words_inside("Python 머신러닝의 구조", "파이썬(Python) 3학년 머신러닝의 구조 - 교보문고")
    assert not BrowserAgent._name_words_inside("파이썬", "파이썬(Python) 3학년 머신러닝의 구조 - 교보문고")
    assert not BrowserAgent._name_words_inside("Python 딥러닝의 구조", "파이썬(Python) 3학년 머신러닝의 구조 - 교보문고")


def test_a_points_column_labelled_with_its_rate_is_a_points_column(tmp_path: Path) -> None:
    """★ T1 O34(`4ea9ffca`): 머리말 「통합 포인트(적립률)」 — 「률」만 보고 비율 칸으로 건너뛰어 마야 eBook 의 855P 를 못 고쳤다."""
    agent, steps = _agent()
    target = tmp_path / "책.xlsx"

    note = _write(agent, steps, target, [
        ["순위", "제목", "판매가(종이책)", "통합 포인트(적립률)", "적립률"],
        ["3", "마야 파이썬 2024", "17,100원", "855P (5%)", "5%"],
    ])

    assert _cells(target)[1] == [3, "마야 파이썬 2024", "17,100원", "5% 적립", "5%"]
    assert "비율만" in note
