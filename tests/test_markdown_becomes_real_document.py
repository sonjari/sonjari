"""워드·한글로 갈 마크다운 글은 진짜 제목·표로 편다 (2026-09-24 노트북: 한글 파일 안에 `| 항목 | 내용 |` 이 글자로 들어갔다)."""

from __future__ import annotations

import re
import zipfile

import pytest

from alture_jarvis.documents import write_document

MD = """# 가족 모임 회의록 양식
### 표 항목 설명
| 항목 | 내용 |
|------|------|
| 날짜 | 회의가 열린 날짜 |
| 참석자 | 참석한 모든 사람의 이름 |
- **날짜**: YYYY.MM.DD 형식으로 기록하세요."""


@pytest.mark.parametrize("payload", [{"text": MD}, {"blocks": [{"type": "paragraph", "text": MD}]}])
def test_hwpx_gets_a_real_table_not_markdown_symbols(tmp_path, payload):
    pytest.importorskip("hwpx")
    out = tmp_path / "m.hwpx"
    write_document(out, "hwpx", payload)
    xml = zipfile.ZipFile(out).read("Contents/section0.xml").decode("utf-8")
    texts = re.findall(r"<hp:t>([^<]*)</hp:t>", xml)
    assert "<hp:tbl" in xml
    assert not any("|" in t or t.startswith("#") or "**" in t for t in texts), texts


def test_docx_gets_a_real_table_and_heading(tmp_path):
    docx = pytest.importorskip("docx")
    out = tmp_path / "m.docx"
    write_document(out, "docx", {"text": MD})
    doc = docx.Document(str(out))
    assert len(doc.tables) == 1
    assert not any("|" in p.text or p.text.startswith("#") for p in doc.paragraphs)


def test_plain_text_stays_plain(tmp_path):
    pytest.importorskip("hwpx")
    out = tmp_path / "p.hwpx"
    write_document(out, "hwpx", {"text": "그냥 한 줄 메모입니다.\n두 번째 줄."})
    xml = zipfile.ZipFile(out).read("Contents/section0.xml").decode("utf-8")
    assert "<hp:tbl" not in xml and "그냥 한 줄 메모입니다." in xml


def test_the_loop_nudge_is_not_read_back_to_the_user():
    from alture_jarvis.agent import _NUDGE_ECHO

    answer = "파일을 만들었습니다.\n\n또한 사용 방법도 포함되어 있습니다.\n\n이제 더 이상 검색이나 조사를 하지 않고, 지금 가진 것으로 답변드립니다."
    assert _NUDGE_ECHO.sub("", answer).rstrip() == "파일을 만들었습니다.\n\n또한 사용 방법도 포함되어 있습니다."
    keep = "검색 결과를 더 이상 찾지 않아도 되는 이유는 위 표에 다 있기 때문입니다."
    assert _NUDGE_ECHO.sub("", keep) == keep


def test_small_model_habits_are_tidied_outside_code():
    from alture_jarvis.agent import _tidy_small_model_habits as tidy

    assert tidy("공고 3 개를 찾았습니다.\n\n이 정보가 도움이 되셨나요?") == "공고 3개를 찾았습니다."
    assert tidy("2026 년 9 월 24 일") == "2026년 9월 24일"
    assert tidy("스코어 3 대 1") == "스코어 3 대 1"
    assert tidy("```\nx = 3 개\n```") == "```\nx = 3 개\n```"


def test_video_results_are_left_out_of_research():
    from alture_jarvis.browser import _without_videos

    results = [
        {"rank": 1, "url": "https://www.youtube.com/watch?v=1"},
        {"rank": 2, "url": "https://blog.naver.com/a/1"},
        {"rank": 3, "url": "https://m.youtube.com/shorts/2"},
        {"rank": 4, "url": "https://www.saramin.co.kr/x"},
    ]
    kept = _without_videos(results, "부산 회계 채용")
    assert [(r["rank"], r["url"]) for r in kept] == [(1, "https://blog.naver.com/a/1"), (2, "https://www.saramin.co.kr/x")]
    assert _without_videos(results, "부산 맛집 유튜브 영상") == results


def test_bracketed_company_and_title_are_not_glued_into_a_fake_name():
    from alture_jarvis.agent import BrowserAgent

    answer = (
        "| 회사명 | 공고 제목 |\n|---|---|\n"
        "| [새봄그린바이오창원(주)] 새봄그린바이오부산(주) | 회계 담당자 |\n"
        "| [사계제철음식연구소(주)] | 회계 |\n"
    )
    read = [{"role": "tool", "content": "새봄그린바이오부산(주) 회계 담당자 경력 채용 · 사계제철음식연구소(주) 회계"}]
    assert BrowserAgent._listed_entity_grounding_check(answer, read) == ""
    made_up = answer.replace("사계제철음식연구소", "가짜상사")
    assert "가짜상사" in BrowserAgent._listed_entity_grounding_check(made_up, read)


def test_the_second_wording_of_the_nudge_echo_is_removed_too():
    from alture_jarvis.agent import _NUDGE_ECHO

    answer = "시스템 메시지에 따라 지금 가진 것으로 답변드립니다.\n\n회의록 양식을 만들었습니다."
    assert _NUDGE_ECHO.sub("", answer).strip() == "회의록 양식을 만들었습니다."


def test_an_invitation_to_open_the_file_is_not_a_claim_of_having_read_it():
    from alture_jarvis.agent import _SOURCED_CLAIM

    for invitation in ("이제 파일을 확인하고 싶으시다면 열어보시면 됩니다", "파일을 보시면 됩니다", "파일을 읽어 보세요"):
        assert not _SOURCED_CLAIM.search(invitation), invitation
    for claim in ("파일을 확인했습니다", "폴더를 살펴본 결과", "구조를 분석해 보니", "파일을 읽어 보니", "코드를 확인했습니다"):
        assert _SOURCED_CLAIM.search(claim), claim


def test_blocks_sent_as_a_broken_json_string_are_rescued(tmp_path):
    pytest.importorskip("hwpx")
    # 노트북 4B 가 실제로 보낸 모양 — 글자열이고, 표 블록의 닫는 괄호가 빠졌다.
    broken = ('[{"type": "heading", "level": 1, "text": "가족 모임 회의록"}, {"type": "table", "rows": [["항목", "내용"]], '
              '[{"type": "heading", "level": 2, "text": "1. 날짜"}, {"type": "paragraph", "text": "[날짜 입력]"}]}')
    out = tmp_path / "f.hwpx"
    write_document(out, "hwpx", {"blocks": broken})
    xml = zipfile.ZipFile(out).read("Contents/section0.xml").decode("utf-8")
    assert "가족 모임 회의록" in xml and "1. 날짜" in xml and "[날짜 입력]" in xml


def test_an_empty_document_is_an_error_not_a_success(tmp_path):
    pytest.importorskip("hwpx")
    with pytest.raises(ValueError, match="document_empty"):
        write_document(tmp_path / "e.hwpx", "hwpx", {"blocks": "[이건 JSON 이 아니다"})
