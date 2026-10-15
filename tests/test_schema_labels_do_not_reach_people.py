"""사람이 볼 답·문서 칸에 도구 속 이름이 새지 않는다 (2026-09-29, MS 스토어 M3).

엑셀 칸마다 「무료 (offers.price=0)」가 붙었다. 과거 브라우저 답 1,212판을 훑어 바뀌는 것이 그 13판뿐임을 확인하고 넣었다.
"""

from __future__ import annotations

from alture_jarvis.agent import _strip_schema_labels, _strip_schema_labels_in


def test_field_path_in_parentheses_is_removed_value_stays() -> None:
    assert _strip_schema_labels("무료 (offers.price=0)")[0] == "무료"


def test_list_of_fields_in_parentheses_is_removed() -> None:
    text = "상세 페이지의 `structured_data` 및 본문 정보 (`author: OpenAI`, `aggregateRating.ratingValue: 3.5`)"
    cleaned, removed = _strip_schema_labels(text)
    assert cleaned == "상세 페이지의 사이트 제공 정보 및 본문 정보"
    assert len(removed) == 2


def test_structured_data_word_keeps_the_meaning() -> None:
    assert _strip_schema_labels("(structured_data 기준)")[0] == "(사이트 제공 정보 기준)"
    assert _strip_schema_labels("structured_data(book)에서 확인")[0] == "사이트 제공 정보에서 확인"


def test_human_parentheses_and_code_refs_are_left_alone() -> None:
    for text in ("저자 (저자: 홍길동)", "(author: 홍길동)", "함수 (voice.py:104)", "가격 (정가: 18,000원)"):
        assert _strip_schema_labels(text) == (text, [])


def test_code_blocks_are_left_alone() -> None:
    text = "예시:\n```\nstructured_data = {'offers.price': 0}\n```"
    assert _strip_schema_labels(text) == (text, [])


def test_document_cells_are_cleaned() -> None:
    removed: list[str] = []
    args = {"path": "메모 앱.xlsx", "sheets": {"메모 앱": [["이름", "가격"], ["Notion", "무료 (offers.price=0)"]]}}
    cleaned = _strip_schema_labels_in(args, removed)
    assert cleaned["sheets"]["메모 앱"][1] == ["Notion", "무료"]
    assert cleaned["path"] == "메모 앱.xlsx"
    assert removed == ["(offers.price=0)"]
