"""양식·근거 검사기(`bench/browser_agents/doc_form.py`)가 **양쪽으로** 맞게 재는지.

새 눈금은 붙이기 전에 좋은 표본과 나쁜 표본 둘 다에 대 본다(이 저장소 규칙).
좋은 문서를 걸면 오탐이고, 나쁜 문서를 통과시키면 눈금이 아니다.

첫 실전에서 오탐이 하나 나왔다 — 라운드마다 같은 이름으로 덮어써서 1판 장부와
3판 파일을 대조했다. 그건 벤치가 판 직후에 사본을 떠 두는 것으로 막았다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alture_jarvis.documents import write_document

BENCH = Path(__file__).resolve().parents[1] / "bench" / "browser_agents"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

import doc_form  # noqa: E402

GOOD_MD = """# YES24 파이썬 도서 3권

YES24에서 파이썬 책 3권의 상세 페이지를 직접 열어 확인했다. 2026-09-13 기준.

| 도서명 | 쪽수 | ISBN | URL |
| --- | --- | --- | --- |
| 점프 투 파이썬 | 432쪽 | 9791163034735 | https://www.yes24.com/product/goods/1 |
| 혼자 공부하는 파이썬 | 552쪽 | 9791162245651 | https://www.yes24.com/product/goods/2 |
"""

TRACE = {
    "tool_numbers": [],
    "tool_numbers_body": ["432", "552", "9791163034735", "9791162245651", "2026", "09", "13", "3", "1", "2"],
    "steps": [
        {"tool": "browser_extract", "evidence": {"url": "https://www.yes24.com/product/goods/1"}},
        {"tool": "browser_extract", "evidence": {"url": "https://www.yes24.com/product/goods/2"}},
    ],
    "verification": {"urls": []},
}


def _check(path: Path, trace=TRACE, ext=(".md",), url=True) -> dict:
    return doc_form.check(path, want_ext=ext, table_task=True, url_wanted=url, trace=trace)


def test_a_good_markdown_document_passes_everything(tmp_path: Path) -> None:
    path = tmp_path / "good.md"
    path.write_text(GOOD_MD, encoding="utf-8")
    result = _check(path)
    assert result["form_ok"] is True, result["failed"]


def test_filling_blanks_with_unverified_is_caught(tmp_path: Path) -> None:
    path = tmp_path / "blank.md"
    path.write_text(GOOD_MD.replace("552쪽", "확인 불가"), encoding="utf-8")
    result = _check(path)
    assert any(f.startswith("빈칸 속임") for f in result["failed"])


def test_a_value_that_was_never_read_is_caught(tmp_path: Path) -> None:
    """읽은 원문에 없는 쪽수 — 지어낸 값이다."""
    path = tmp_path / "made_up.md"
    path.write_text(GOOD_MD.replace("552쪽", "618쪽"), encoding="utf-8")
    result = _check(path)
    assert "618" in result["unsupported"]


def test_an_address_that_was_never_opened_is_caught(tmp_path: Path) -> None:
    path = tmp_path / "url.md"
    path.write_text(GOOD_MD.replace("goods/2", "goods/999"), encoding="utf-8")
    result = _check(path)
    assert any("goods/999" in value for value in result["unsupported"])


def test_a_header_that_is_really_a_value_is_caught(tmp_path: Path) -> None:
    path = tmp_path / "head.md"
    lines = GOOD_MD.splitlines()
    body = [l for l in lines if not l.startswith("| 도서명") and not l.startswith("| ---")]
    first_value = next(i for i, l in enumerate(body) if l.startswith("| 점프"))
    body.insert(first_value + 1, "| --- | --- | --- | --- |")
    path.write_text("\n".join(body), encoding="utf-8")
    result = _check(path)
    assert any(f.startswith("머리줄") for f in result["failed"])


def test_bold_markers_left_in_word_are_caught(tmp_path: Path) -> None:
    """검사기가 봐야 하는 것은 **파일**이다 — 쓰기 도구를 거치지 않은 워드를 직접 만든다."""
    from docx import Document

    path = tmp_path / "leak.docx"
    doc = Document()
    doc.add_heading("경쟁 분석", level=1)
    doc.add_paragraph("1. **Python 중심의 에이전트 생태계:** 수요가 많다")
    doc.save(str(path))
    result = doc_form.check(path, want_ext=(".docx",), table_task=False, url_wanted=False, trace=None)
    assert any(f.startswith("기호 누수") for f in result["failed"])


def test_a_word_file_from_our_writer_passes_the_form_checks(tmp_path: Path) -> None:
    """반대쪽 — 우리 쓰기 도구가 만든 멀쩡한 워드를 걸면 오탐이다."""
    path = tmp_path / "ok.docx"
    write_document(path, "docx", {"blocks": [
        {"type": "heading", "level": 1, "text": "여수 회계 채용 공고 2건"},
        {"type": "paragraph", "text": "사람인에서 여수 회계 공고 2건의 상세를 직접 확인했다."},
        {"type": "table", "rows": [
            ["회사명", "고용형태", "공고 URL"],
            ["푸른빛에너지", "정규직", "https://www.saramin.co.kr/zf_user/jobs/1"],
            ["한화 아쿠아플라넷", "계약직", "https://www.saramin.co.kr/zf_user/jobs/2"],
        ]},
    ]})
    result = doc_form.check(path, want_ext=(".docx",), table_task=True, url_wanted=True, trace=None)
    assert result["form_ok"] is True, result["failed"]


def test_the_wrong_file_type_is_caught(tmp_path: Path) -> None:
    path = tmp_path / "good.md"
    path.write_text(GOOD_MD, encoding="utf-8")
    result = _check(path, ext=(".xlsx",))
    assert any(f.startswith("형식") for f in result["failed"])


# ── 새 과제 형식(CSV·한글) — 돌리기 전에 채점기부터 양쪽으로 ────────────────────
import content_grade  # noqa: E402

JOB_ROWS = [
    ["회사명", "고용형태", "마감일", "공고 URL"],
    ["가나상사", "정규직", "2026-09-30", "https://www.jobkorea.co.kr/Recruit/GI_Read/1"],
    ["다라물산", "계약직", "2026-10-05", "https://www.jobkorea.co.kr/Recruit/GI_Read/2"],
    ["마바유통", "정규직", "2026-10-11", "https://www.jobkorea.co.kr/Recruit/GI_Read/3"],
]


def _hwpx(tmp_path: Path, rows: list[list[str]]) -> Path:
    path = tmp_path / "jobs.hwpx"
    write_document(path, "hwpx", {"blocks": [
        {"type": "heading", "level": 1, "text": "순천 사무직 공고 3건"},
        {"type": "paragraph", "text": "잡코리아에서 순천 사무직 공고 3건의 상세를 직접 확인했다."},
        {"type": "table", "rows": rows},
    ]})
    return path


def test_a_good_hangul_table_is_read_with_its_structure(tmp_path: Path) -> None:
    """읽는이는 한글 표를 칸마다 한 줄로 풀어 준다 — 그걸로 채점하면 완벽한 문서가 0% 였다."""
    path = _hwpx(tmp_path, JOB_ROWS)
    card = content_grade.grade("jobkorea_hwpx", path)
    assert card["filled_pct"] == 100, card
    form = doc_form.check(path, want_ext=(".hwpx",), table_task=True, url_wanted=True, trace=None)
    assert form["form_ok"] is True, form["failed"]


def test_an_unverified_cell_in_a_hangul_table_counts_as_unfilled(tmp_path: Path) -> None:
    """★ 2026-09-14 부터 **우리 쓰기 도구가 「확인 불가」 칸을 비운다**(새 과제 검사 ③).

    그래서 이 시험은 「검사기가 확인 불가를 잡는가」가 아니라 「비운 칸이 채운 것으로
    세어지지 않는가」를 본다. 검사기가 확인 불가 글자를 잡는지는 쓰기 도구를 거치지 않은
    마크다운 시험(`test_filling_blanks_with_unverified_is_caught`)이 따로 본다.
    """
    rows = [r[:] for r in JOB_ROWS]
    rows[2][2] = "확인 불가"
    path = _hwpx(tmp_path, rows)
    assert content_grade.grade("jobkorea_hwpx", path)["filled_pct"] < 100
    form = doc_form.check(path, want_ext=(".hwpx",), table_task=True, url_wanted=True, trace=None)
    assert not any(f.startswith("빈칸 속임") for f in form["failed"])


def test_a_comma_csv_is_a_table_even_with_commas_inside_cells(tmp_path: Path) -> None:
    """탭만 표로 보던 채점기는 멀쩡한 CSV 를 「표 0행」으로 찍었을 것이다."""
    path = tmp_path / "mice.csv"
    path.write_text(
        "상품명,가격,제조사,상품 URL\n"
        '"로지텍 G304, 블랙",29900원,로지텍,https://prod.danawa.com/info/?pcode=1\n'
        "레이저 바이퍼,59000원,레이저,https://prod.danawa.com/info/?pcode=2\n"
        "앱코 A660,19800원,앱코,https://prod.danawa.com/info/?pcode=3\n",
        encoding="utf-8-sig",
    )
    card = content_grade.grade("danawa_csv", path)
    assert card["filled_pct"] == 100, card
    form = doc_form.check(path, want_ext=(".csv",), table_task=True, url_wanted=True, trace=None)
    assert form["form_ok"] is True, form["failed"]


def test_a_pipe_table_saved_as_csv_is_caught(tmp_path: Path) -> None:
    path = tmp_path / "fake.csv"
    path.write_text("| 상품명 | 가격 |\n| --- | --- |\n| 로지텍 | 29900원 |\n", encoding="utf-8")
    form = doc_form.check(path, want_ext=(".csv",), table_task=True, url_wanted=False, trace=None)
    assert any(f.startswith("기호 누수") for f in form["failed"])


def test_addresses_are_matched_by_what_they_point_at() -> None:
    """물음표 뒤를 버리면 다나와·사람인은 **어떤 주소를 적어도** 연 주소로 통과했다.

    반대로 파라미터를 통째로 견주면, 자비스가 연 주소에 붙은 곁가지 때문에 멀쩡한
    주소가 걸린다. 양쪽 다 틀리면 안 된다.
    """
    opened = [
        "https://prod.danawa.com/info/?pcode=1&cate=112787&keyword=x",
        "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=search&rec_idx=5123&location=ts",
        "https://www.yes24.com/product/goods/119293186",
    ]
    assert doc_form.url_was_opened("https://prod.danawa.com/info/?pcode=1", opened)
    assert not doc_form.url_was_opened("https://prod.danawa.com/info/?pcode=999", opened)
    assert doc_form.url_was_opened(
        "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=5123", opened)
    assert not doc_form.url_was_opened(
        "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=7777", opened)
    assert doc_form.url_was_opened("https://www.yes24.com/product/goods/119293186/", opened)
    assert not doc_form.url_was_opened("https://www.yes24.com/product/goods/1", opened)
