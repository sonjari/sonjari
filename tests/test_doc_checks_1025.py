"""문서의 숫자 검사 (2026-10-25 대표 「문서도 똑같이」) — 틀린 것이 확실할 때만, 저장 전에 한 번.

지난 실제 문서 쓰기 1,116번에 대 보니 걸린 3번이 모두 진짜(2026. 10. 5.은 월요일인데 「(일)」)였다 — 헛걸림 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis import doc_checks
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

QUOTE = [["품명", "규격", "수량", "단가", "공급가액", "세액"],
         ["알림 구독", "월", "12", "99,000", "1,188,000", "118,800"],
         ["설정 대행", "1회", "1", "300,000", "300,000", "30,000"],
         ["합계", "", "", "", "1,488,000", "148,800"]]


def _blocks(rows, extra=""):
    return {"path": "견적서.docx", "format": "docx",
            "blocks": [{"type": "heading", "level": 1, "text": "견 적 서"},
                       {"type": "paragraph", "text": "발행일 2026. 10. 26.(월) · 합계 금1,636,800원(금일백육십삼만육천팔백원)" + extra},
                       {"type": "table", "rows": rows}]}


def test_a_correct_quotation_passes() -> None:
    assert doc_checks.problems(_blocks(QUOTE)) == []


@pytest.mark.parametrize("change, expect", [
    (lambda rows: rows[1].__setitem__(4, "1,288,000"), "12 × 99,000"),
    (lambda rows: rows[3].__setitem__(4, "1,500,000"), "더하면 1,488,000"),
    (lambda rows: rows[2].__setitem__(5, "33,000"), "10%"),
])
def test_table_math_is_checked(change, expect) -> None:
    rows = [list(row) for row in QUOTE]
    change(rows)
    found = doc_checks.problems(_blocks(rows))
    assert any(expect in item for item in found), found


def test_korean_amount_and_weekday_are_checked() -> None:
    assert doc_checks.korean_number("일십일만삼천오백육십") == 113560
    assert doc_checks.korean_number("일백일십만") == 1_100_000
    bad = _blocks(QUOTE)
    bad["blocks"][1]["text"] = "발행일 2026. 10. 25.(월) · 합계 금1,636,800원(금일백육십삼만육천원)"
    found = doc_checks.problems(bad)
    assert any("일요일" in item for item in found) and any("1,636,000" in item for item in found)


def test_dates_and_slashes_in_brackets_are_not_arithmetic() -> None:
    texts = {"path": "x.md", "blocks": [{"type": "paragraph", "text": t} for t in (
        "24 검색 결과 (2026-09-11 확인)", "139,300원 · 무료 (제주 20,000원 / 도서산간 40,000원)", "4.5 (전공 평점: 4.32 / 4.5)",
        "5 (4×24)", "11번가 (2026-10-13)")]}
    assert doc_checks.problems(texts) == []


def test_the_document_is_not_saved_and_sent_back_once(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=str(tmp_path / "docs"))
    tools = LocalComputerTools(config)
    rows = [list(row) for row in QUOTE]
    rows[1][4] = "1,288,000"
    args = {**_blocks(rows), "__job_id": "j", "open": False}
    with pytest.raises(ValueError, match="doc_check"):
        tools.write_document_file(args)
    assert not (tmp_path / "docs" / "견적서.docx").exists()
    out = tools.write_document_file(args)  # 두 번째는 받는다 — 검사가 틀릴 수도 있다
    assert Path(out["path"]).exists()


def test_a_whole_sheet_quotation_from_the_real_run_is_checked() -> None:
    """실제 견적서 판 ba286682: 시트 통째(맨 위 제목 줄) · 「12개월」 수량 · 한글 금액이 다른 칸 —
    합계 1,669,800 옆에 「일금 육백육십육만구천팔백원정」(= 6,669,800)을 써도 못 잡았다."""
    sheet = [["견 적 서", "", "", "", "", "", ""],
             ["품명", "규격", "수량", "단가(원)", "공급가액(원)", "세액(원)", "비고"],
             ["학부모 알림 구독", "월", "12개월", "99,000", "1,188,000", "118,800", ""],
             ["초기 설정 대행", "1회", "1회", "300,000", "300,000", "30,000", ""],
             ["학부모 안내문 인쇄", "A4", "200장", "150", "30,000", "3,000", ""],
             ["공급가액 합계", "", "", "", "1,518,000", "151,800", ""],
             ["총 합계", "", "", "", "", "", "1,669,800"],
             ["한글 금액", "", "", "", "", "", "일금 육백육십육만구천팔백원정"]]
    args = {"path": "q.xlsx", "format": "xlsx", "sheets": {"견적서": sheet}}
    found = doc_checks.problems(args)
    assert any("6,669,800" in item and "1,669,800" in item for item in found), found
    sheet[7][6] = "일금 일백육십육만구천팔백원정"
    assert doc_checks.problems(args) == []
    sheet[2][4] = "1,288,000"
    assert any("12개월 × 99,000" in item for item in doc_checks.problems(args))
