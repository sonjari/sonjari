"""모델이 머리줄을 `text` 에 담아 보내도 **열 이름을 잃지 않는다.**

## 왜 (2026-09-12 n=3 벤치)

yes24 두 판이 채움 0% 로 찍혔다. 파일은 만들어졌고 사슬도 O 였다. 열어 보니:

    | Do it! 점프 투 파이썬 | 432쪽 | 9791163034735 | https://… |
    | --- | --- | --- | --- |

**열 이름이 사라지고 유일한 값이 머리줄로 먹혔다.** 데이터 0줄짜리 표다.

모델이 준 것은 멀쩡했다 — 틀린 모양이 아니라 나눠 담은 모양이었다:

    {"type": "table",
     "text": "| 도서명 | 쪽수 | ISBN | 상세 페이지 URL |",
     "rows": [["Do it! 점프 투 파이썬", "432쪽", "9791163034735", "https://…"]]}

우리가 `rows` 만 읽고 `text` 를 버렸다. 조사는 다 해 놓고 **담는 자리에서 잃었다.**
채점기의 「열 0/4」는 정확한 보고였다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.documents import write_document

HEADER = "| 도서명 | 쪽수 | ISBN | 상세 페이지 URL |"
ROWS = [
    ["Do it! 점프 투 파이썬", "432쪽", "9791163034735", "https://www.yes24.com/a"],
    ["혼자 공부하는 파이썬", "552쪽", "9791162245651", "https://www.yes24.com/b"],
]


def _write(tmp_path: Path, block: dict, name: str = "t.md") -> str:
    write_document(tmp_path / name, "md", {"blocks": [block]})
    return (tmp_path / name).read_text(encoding="utf-8")


def test_the_header_line_comes_back_from_text(tmp_path: Path) -> None:
    out = _write(tmp_path, {"type": "table", "text": HEADER, "rows": ROWS})
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines[0] == HEADER
    # 값 두 줄이 살아 있어야 한다 — 하나도 머리줄로 먹히지 않는다.
    assert "Do it! 점프 투 파이썬" in out and "혼자 공부하는 파이썬" in out
    assert out.count("9791") == 2


def test_a_table_that_already_has_its_header_is_left_alone(tmp_path: Path) -> None:
    """제대로 준 표를 건드리면 머리줄이 두 줄이 된다."""
    grid = [["도서명", "쪽수"], ["A", "1쪽"]]
    out = _write(tmp_path, {"type": "table", "text": "| 도서명 | 쪽수 |", "rows": grid})
    assert out.count("도서명") == 1


def test_a_mismatched_header_is_not_forced_in(tmp_path: Path) -> None:
    """칸 수가 안 맞으면 손대지 않는다 — 데이터를 망가뜨리느니 그대로 둔다."""
    out = _write(
        tmp_path,
        {"type": "table", "text": "| 하나 | 둘 |", "rows": [["a", "b", "c"]]},
    )
    assert "하나" not in out


def test_a_separator_line_is_not_mistaken_for_a_header(tmp_path: Path) -> None:
    out = _write(tmp_path, {"type": "table", "text": "| --- | --- |", "rows": [["a", "b"]]})
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines[0] == "| a | b |"


def test_the_same_rescue_reaches_word_documents(tmp_path: Path) -> None:
    """md 만 고치면 docx 가 갈린다 — 같은 자리가 넷이었다."""
    from docx import Document

    write_document(tmp_path / "t.docx", "docx", {"blocks": [
        {"type": "table", "text": HEADER, "rows": ROWS}
    ]})
    table = Document(str(tmp_path / "t.docx")).tables[0]
    assert [cell.text for cell in table.rows[0].cells][0] == "도서명"
    assert len(table.rows) == 3


def test_a_grid_sent_as_a_string_is_brought_back(tmp_path: Path) -> None:
    """격자를 통째로 `text` 에 문자열로 담아 보내기도 한다 (2026-09-12 실측).

        {"type": "table", "rows": [],
         "text": "[['도서명', '쪽수', …], ['모두의 파이썬', '200쪽', …]]"}

    행이 0개라 표를 아예 안 썼고, 파일에는 제목과 한 줄 설명만 남았다.
    조사한 세 권이 통째로 사라졌다 — 채움 0%.
    """
    grid_text = (
        "[['도서명', '쪽수', 'ISBN'], "
        "['모두의 파이썬', '200쪽', '9791162241974'], "
        "['점프 투 파이썬', '432쪽', '9791163034735']]"
    )
    out = _write(tmp_path, {"type": "table", "rows": [], "text": grid_text}, "g.md")
    assert "| 도서명 | 쪽수 | ISBN |" in out
    assert "모두의 파이썬" in out and "점프 투 파이썬" in out


def test_json_shaped_grids_come_back_too(tmp_path: Path) -> None:
    out = _write(
        tmp_path,
        {"type": "table", "rows": [], "text": '[["회사명","고용형태"],["비케이","정규직"]]'},
        "j.md",
    )
    assert "비케이" in out and "회사명" in out


def test_ordinary_text_is_never_turned_into_a_table(tmp_path: Path) -> None:
    """아무 문자열이나 격자로 읽으면 본문이 표로 둔갑한다."""
    out = _write(tmp_path, {"type": "table", "rows": [], "text": "[참고] 표는 아래에"}, "n.md")
    assert "참고" not in out
