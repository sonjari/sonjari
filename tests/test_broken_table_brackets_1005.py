"""표 블록의 대괄호 개수가 틀려도 줄은 건진다 (2026-10-05 9B arXiv 판 d3a87ec6).

9B 가 `blocks` 를 JSON 글자열로 보내면서 표를 두 가지로 깨뜨렸다. 두 번 다 `blocks_table_unreadable`(못 읽은 블록 0개)로 돌려보냈고
세 번째에야 됐다. 줄(문자열 배열) 자체는 두 번 다 온전했다 — 틀린 것은 감싸는 괄호의 개수뿐이다.

아래 글자열은 그 판이 실제로 보낸 것을 줄만 줄인 것이다.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.documents import _blocks_from_payload, rows_from_blocks, write_document

HEAD = '["Paper Title", "Authors", "arXiv ID"]'
ROW1 = '["Language Models that Play Chess and Explain Their Moves", "Adithya Bhaskar, Jeffrey Cheng, Danqi Chen", "2610.03695"]'
ROW2 = '["FALCON: A Model and Dataset Agnostic Framework [NL2SQL] {pairs}", "Darian Lee, Shannon Rumsey", "2610.03625"]'
ROW3 = '["Writerslogic at the CLEF 2026 SimpleText Track", "David L. Condrey", "2610.03567"]'
TITLE = '{"type": "heading", "level": 1, "text": "Comparison of 3 Newest arXiv cs.CL Papers"}'
NEXT = '{"type": "heading", "level": 2, "text": "Key Observations"}, {"type": "paragraph", "text": "All three are cs.CL."}'

#: 머리줄 뒤에서 표를 일찍 닫았다.
CLOSED_EARLY = f'[{TITLE}, {{"type": "table", "rows": [{HEAD}], {ROW1}, {ROW2}, {ROW3}]}}, {NEXT}]'
#: 표를 닫는 `}}` 가 빠졌다.
NEVER_CLOSED = f'[{TITLE}, {{"type": "table", "rows": [{HEAD}, {ROW1}, {ROW2}, {ROW3}]], {NEXT}]'


def _kinds(blocks):
    return [block.get("type") for block in blocks]


def test_a_table_closed_too_early_keeps_every_row():
    blocks = _blocks_from_payload(CLOSED_EARLY)
    assert _kinds(blocks) == ["heading", "table", "heading", "paragraph"]
    rows = rows_from_blocks(blocks)
    assert len(rows) == 4 and rows[0][0] == "Paper Title" and rows[3][2] == "2610.03567"


def test_a_table_that_was_never_closed_is_not_silently_dropped():
    blocks = _blocks_from_payload(NEVER_CLOSED)
    assert _kinds(blocks) == ["heading", "table", "heading", "paragraph"], "표가 사라지면 다음 제목이 표 자리에 온다"
    rows = rows_from_blocks(blocks)
    assert len(rows) == 4
    # 줄 안의 괄호·중괄호는 줄의 끝이 아니다.
    assert rows[2][0] == "FALCON: A Model and Dataset Agnostic Framework [NL2SQL] {pairs}"


def test_the_excel_is_made_instead_of_sending_the_model_back(tmp_path: Path):
    for index, broken in enumerate((CLOSED_EARLY, NEVER_CLOSED)):
        target = tmp_path / f"papers_{index}.xlsx"
        write_document(target, "xlsx", {"blocks": broken})
        assert target.exists() and target.stat().st_size > 0


def test_rows_are_not_invented_when_there_are_none():
    """줄을 못 찾으면 표를 지어내지 않는다 — 예전처럼 「표가 깨졌다」고 돌려보낸다."""
    blocks = _blocks_from_payload('[{"type": "table", "rows": [[ "a", "b" , {"type": "heading", "text": "x"}]')
    assert "table" not in _kinds(blocks)


def test_well_formed_blocks_are_untouched():
    good = f'[{TITLE}, {{"type": "table", "rows": [{HEAD}, {ROW1}]}}]'
    blocks = _blocks_from_payload(good)
    assert _kinds(blocks) == ["heading", "table"] and len(blocks[1]["rows"]) == 2


def test_a_row_that_cannot_be_read_is_not_quietly_left_out(tmp_path: Path):
    """괄호가 아니라 **줄 자체**가 깨졌으면(안쪽 따옴표) 복구하지 않는다 — 머리줄뿐인 엑셀을 성공이라 하지 않는다."""
    import pytest

    broken = ('[{"type": "heading", "level": 1, "text": "교보문고 파이썬 책"}, '
              '{"type": "table", "rows": [["순위", "제목"], ["1", "초보자를 위한 "파이썬" 200제"]]}]')
    assert "table" not in _kinds(_blocks_from_payload(broken))
    with pytest.raises(ValueError) as raised:
        write_document(tmp_path / "b.xlsx", "xlsx", {"blocks": broken})
    assert str(raised.value).startswith("blocks_table_unreadable")
