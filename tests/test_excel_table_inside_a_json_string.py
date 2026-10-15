"""표를 **넣었는데** 「표가 있어야 합니다」라고 하지 않는다 (2026-10-01 AWS, Qwen 3.5 9B).

모델이 blocks 를 JSON 글자열로 보냈고(목록 대신), 그 안의 표 블록이 깨져 못 읽었다. 도구는 「엑셀은 표가 있어야 합니다」라고
답했고, 모델은 표를 넣었으니 **같은 것을 5번** 다시 보냈다(16걸음째에야 다른 모양으로 성공). 틀린 오류 문구는 벽보다 나쁘다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.documents import write_document

GOOD_TABLE = {"type": "table", "rows": [["순위", "제목", "판매가"], ["1", "초보자를 위한 파이썬 200제", "18,000원"]]}


def test_a_readable_json_string_still_makes_the_sheet(tmp_path: Path) -> None:
    blocks = json.dumps([{"type": "heading", "level": 1, "text": "교보문고 파이썬 책"}, GOOD_TABLE], ensure_ascii=False)

    shape = write_document(tmp_path / "a.xlsx", "xlsx", {"blocks": blocks})

    assert shape


def test_a_broken_table_inside_the_string_says_what_to_do(tmp_path: Path) -> None:
    # 표 블록이 닫히지 않은 글자열 — 제목·문단은 건지지만 표는 못 읽는다.
    broken = ('[{"type": "heading", "level": 1, "text": "교보문고 파이썬 책"}, '
              '{"type": "table", "rows": [["순위", "제목"], ["1", "초보자를 위한 "파이썬" 200제"]]}]')

    with pytest.raises(ValueError) as raised:
        write_document(tmp_path / "b.xlsx", "xlsx", {"blocks": broken})

    message = str(raised.value)
    assert message.startswith("blocks_table_unreadable"), message
    assert "rows" in message and "목록" in message
    assert "표가 있어야" not in message, "표를 넣은 모델에게 표가 없다고 하면 같은 것을 또 보낸다"


def test_no_table_at_all_keeps_the_old_message(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as raised:
        write_document(tmp_path / "c.xlsx", "xlsx", {"blocks": json.dumps([{"type": "paragraph", "text": "글만"}])})

    assert str(raised.value).startswith("rows_or_sheets_required")
