"""도구가 모르는 모양의 블록을 조용히 버려 **빈 문서**가 「성공」으로 나가지 않는다 (2026-10-12 밤).

4B(창 32K)에게 조사한 내용을 「한글이나 워드 파일로 전달해 줘」라고 하자 글자가 0자인 한글 파일이 나왔고, 도구는 성공이라고
했고, 답은 「한글 파일로 정리했습니다」였다. 작은 카드로 쓰는 사람이 같은 날 겪은 「흰 화면뿐인 파일」과 같은 모양이다.
모델이 보낸 블록은 `{"heading": …, "paragraphs": […]}` 묶음이었다 — 문서 쓰기는 `type` · `text` · `rows` 만 읽어서 내용을 전부
버렸고, 빈 문서 검사는 「보낸 것」에 글자가 있다는 이유로 통과시켰다.

표본의 글은 지어낸 것이다. 블록의 **모양**만 그날 온 것에서 가져왔다.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import docx
import pytest

from alture_jarvis.documents import _draws_text, _unpack_sections, write_document

SECTIONS = [
    {"heading": "가상 가게 홍보 전략 분석", "paragraphs": ["본 분석은 지어낸 가게의 공개 자료를 바탕으로 한다.", "핵심은 세 가지다."]},
    {"heading": "작은 가게에 적용하기", "paragraphs": ["단골에게 먼저 알린다."], "items": ["전단 대신 문자", "월 1회 행사"]},
]


def _hwpx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        parts = [archive.read(name).decode("utf-8", "replace") for name in archive.namelist() if name.startswith("Contents/section")]
    return " ".join(re.sub(r"<[^>]+>", " ", part) for part in parts)


def _docx_text(path: Path) -> str:
    document = docx.Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def test_a_heading_with_paragraphs_bundle_becomes_a_heading_and_paragraphs() -> None:
    blocks = _unpack_sections(SECTIONS)
    assert blocks[0] == {"type": "heading", "level": 2, "text": "가상 가게 홍보 전략 분석"}
    assert blocks[1] == {"type": "paragraph", "text": "본 분석은 지어낸 가게의 공개 자료를 바탕으로 한다."}
    assert {"type": "bullet", "text": "전단 대신 문자"} in blocks and {"type": "bullet", "text": "월 1회 행사"} in blocks
    assert len(blocks) == 3 + 4, "내용은 하나도 빠지지 않는다"


@pytest.mark.parametrize("fmt, read", [("hwpx", _hwpx_text), ("docx", _docx_text)])
def test_the_file_holds_the_words_the_model_sent(fmt: str, read, tmp_path: Path) -> None:  # noqa: ANN001
    target = tmp_path / f"report.{fmt}"
    write_document(target, fmt, {"blocks": SECTIONS})
    body = read(target)
    for words in ("가상 가게 홍보 전략 분석", "핵심은 세 가지다.", "작은 가게에 적용하기", "월 1회 행사"):
        assert words in body, f"{fmt}: 「{words}」가 파일에 없다"


def test_markdown_and_plain_text_hold_them_too(tmp_path: Path) -> None:
    for fmt in ("md", "txt"):
        target = tmp_path / f"report.{fmt}"
        write_document(target, fmt, {"blocks": SECTIONS})
        body = target.read_text(encoding="utf-8")
        assert "가상 가게 홍보 전략 분석" in body and "단골에게 먼저 알린다." in body and "전단 대신 문자" in body


def test_other_shapes_a_small_model_sends() -> None:
    # 종류를 지어 붙인 묶음 · 제목을 title 칸에 · 글머리표를 items 에 · 묶음 안의 묶음 · 줄의 목록(표)
    blocks = _unpack_sections([
        {"type": "section", "title": "요약", "content": "한 줄 요약이다."},
        {"type": "heading", "title": "제목 칸에 온 제목"},
        {"type": "list", "items": ["하나", "둘"]},
        {"heading": "큰 묶음", "sections": [{"heading": "작은 묶음", "content": "안쪽 글"}]},
        {"heading": "표", "data": [["항목", "값"], ["가", "1"]]},
    ])
    texts = [(block.get("type"), block.get("text")) for block in blocks if isinstance(block, dict) and block.get("text")]
    assert ("heading", "요약") in texts and ("paragraph", "한 줄 요약이다.") in texts
    assert ("heading", "제목 칸에 온 제목") in texts
    assert ("bullet", "하나") in texts and ("bullet", "둘") in texts
    assert ("heading", "큰 묶음") in texts and ("heading", "작은 묶음") in texts and ("paragraph", "안쪽 글") in texts
    nested = next(block for block in blocks if block.get("text") == "작은 묶음")
    outer = next(block for block in blocks if block.get("text") == "큰 묶음")
    assert nested["level"] == outer["level"] + 1, "묶음 안의 묶음은 한 단계 아래 제목이다"
    assert {"type": "table", "rows": [["항목", "값"], ["가", "1"]]} in blocks


def test_blocks_the_writer_already_understands_are_left_alone() -> None:
    known = [
        {"type": "heading", "level": 1, "text": "제목"},
        {"type": "paragraph", "text": "본문", "footnote": "각주 글"},
        {"type": "table", "rows": [["가", "나"], ["1", "2"]]},
        {"rows": [["가", "나"]]},
        {"type": "rule"},
        {"type": "image", "path": "그림.png"},
        {"type": "paragraph", "text": ""},
        "그냥 글 한 줄",
    ]
    assert _unpack_sections(known) == known


def test_nothing_to_draw_is_an_error_not_a_blank_file(tmp_path: Path) -> None:
    """풀어도 글이 없으면 파일을 만들지 않고 돌려보낸다 — 무엇이 필요한지 말한다."""
    for fmt in ("hwpx", "docx", "md", "txt"):
        target = tmp_path / f"empty.{fmt}"
        with pytest.raises(ValueError, match="document_empty"):
            write_document(target, fmt, {"blocks": [{"type": "paragraph", "text": ""}, {"style": "bold"}, {"heading": "   "}]})
        assert not target.exists(), f"{fmt}: 빈 파일이 남았다"
    assert not _draws_text([{"type": "paragraph", "text": " "}], [], "")
    assert _draws_text([{"type": "table", "rows": [["가"]]}], [], "") and _draws_text([], [], "글") and _draws_text([], [["가"]], "")


def test_slides_keep_their_own_shape(tmp_path: Path) -> None:
    """PPT 는 제 칸(title · bullets)이 따로 있다 — 풀지 않는다."""
    target = tmp_path / "deck.pptx"
    shape = write_document(target, "pptx", {"blocks": [{"title": "첫 장", "bullets": ["하나", "둘"]}]})
    assert shape and target.exists()
