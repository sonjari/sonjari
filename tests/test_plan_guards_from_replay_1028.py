"""계획 읽기(plan.py)가 **지켜야 하는 요청 읽기** — 재생 261fbfe2(2026-10-28)에서 옮겨 온 사례.

## 왜 저장소 시험으로 두나

2026-10-27 의 증상 둘(#1 읽을 재료의 이름이 만들 형식을 잠금 · #2 사이트 이름이 있는 웹 조사의 「폴더」를 로컬로 읽음)을
같은 문장으로 세 번 다시 고치게 한 재생 측정에서, 세 판 모두 보이는 시험(저장소의 기존 시험 + 증상 시험)은 통과했는데
**지켜야 할 것을 깼다**(판 5b05df02 는 숨은 지킴 46개 중 19개). 저장소의 시험이 이 경우들을 안 지키고 있었다.
아래는 진짜 고침(`aa06dc44`)이 실제로 내는 값을 기대값으로 박은 것이다. 기대값을 시험이 정하지 않는다 — 코드의 출력이다.

- guard: 이름을 직접 댄 요청은 그 형식을 지킨다(「엑셀은 안 쓸게요. plan.py」) · 진짜로 이 PC 의 파일을 읽으라는 요청은 local 을 지킨다
  (「깃허브 사례 3개와 D:\자료 폴더의 문서 5개」) · 이름 없는 요청은 낱말 그대로.
- fix1: 읽을 재료의 이름(README.md · deploy.yaml)이 만들 형식(엑셀)을 잠그지 않는다 — 다른 말꼴로 쓴 같은 요청.

사례 데이터는 이 파일 안에 직접 있다(재생 측정 폴더를 읽지 않는다).
재생 측정은 시작 커밋 4b47d8c3 을 복제하므로 이 시험이 그 측정의 숨은 시험을 새어 나가게 하지 않는다.
"""
from __future__ import annotations

import pytest

from alture_jarvis import plan

# (이름, 요청 문장, 기대하는 만들 파일 확장자, 이 PC 의 파일을 읽는 개수 요구(local count)가 서는가)
GUARD_CASES = [
    ("config_json_excel", "서버 설정(config.json)을 읽고 항목별로 엑셀 한 장으로 정리해 주세요.", [".xlsx"], False),
    ("claude_md_paren_excel", "프로젝트 규칙 파일(CLAUDE.md)을 읽고 핵심만 엑셀 한 장으로 정리해 주세요.", [".xlsx"], False),
    ("toml_excel", "pyproject.toml 을 읽고 의존성 목록을 엑셀로 정리해 줘.", [".xlsx"], False),
    ("named_py_decline_excel", "plan.py 를 고쳐 줘. 엑셀은 안 쓸게요.", [".py"], False),
    ("named_py_decline_excel2", "report.py 를 만들어 줘. 엑셀은 안 쓸게요", [".py"], False),
    ("decline_excel_first", "엑셀은 안 쓸게요. tool.py 를 구현해 줘.", [".py"], False),
    ("decline_word_first", "워드는 안 쓸게요. calc.py 만들어 줘.", [".py"], False),
    ("named_py_hangul_name", "한글 이름 함수를 쓰는 main.py 를 만들어 줘.", [".py"], False),
    ("named_py_wordmark", "워드마크 로고를 그리는 logo.py 를 만들어 줘.", [".py"], False),
    ("named_py_pptx_lib", "python-pptx 로 슬라이드를 만드는 make_deck.py 를 구현해 줘.", [".py"], False),
    ("named_py_quoted_example", "「엑셀로 정리해줘」라고 말하면 동작하는 챗봇 bot.py 를 만들어 줘.", [".py"], False),
    ("named_xlsx", "합계.xlsx 로 저장해 줘", [".xlsx"], False),
    ("named_json_excel_source", "설정을 config.json 으로 저장해 줘. 엑셀 자료를 참고해", [".json"], False),
    ("named_html_excel_source", "엑셀 데이터를 읽어서 index.html 로 만들어 줘.", [".html"], False),
    ("named_md_excel_source", "엑셀 표를 읽고 summary.md 로 정리해 줘", [".md"], False),
    ("named_cpp_excel_word", "엑셀 대신 main.cpp 를 작성해 줘", [".cpp"], False),
    ("named_py_word_source", "워드 파일을 읽고 parse.py 로 구현해 줘", [".py"], False),
    ("named_py_excel_word", "엑셀과 워드 파일을 읽어서 merge.py 로 합치는 코드를 짜 줘.", [".py"], False),
    ("named_docx_excel_source", "보고서.docx 로 만들어 줘. 숫자는 엑셀 표에서 가져와", [".docx"], False),
    ("named_py_hwp_word", "한글 문서에서 표를 뽑는 extract_table.py 를 작성해 줘.", [".py"], False),
    ("named_ts_pdf_word", "PDF 를 읽어 워드로 바꾸는 converter.ts 를 만들어 줘.", [".ts"], False),
    ("named_md_word_output", "CLAUDE.md 를 읽고 워드로 정리해 줘", [".docx"], False),
    ("excel_only_no_name", "분기별 매출을 엑셀 한 장으로 정리해 줘.", [".xlsx"], False),
    ("word_only_no_name", "회의록을 워드 문서 하나로 만들어 줘.", [".docx"], False),
    ("pptx_only_no_name", "신제품 소개 발표자료를 PPT 로 만들어 줘.", [".pptx"], False),
    ("web_folder_structure_10", "유튜브와 레딧에서 프로젝트 폴더 구조 정리 사례 10개 이상을 모아 엑셀로 만들어 줘.", [".xlsx"], False),
    ("local_d_drive_folder", "D:\\자료 폴더의 문서 12개를 읽고 엑셀로 정리해 줘.", [".xlsx"], True),
    ("local_desktop_folder", "바탕화면 폴더에 있는 파일 4개를 읽어 요약해 줘.", [], True),
    ("local_my_docs_folder", "내 문서 폴더의 엑셀 파일 6개 이상을 직접 열어 읽고 정리해 주세요.", [".xlsx"], True),
    ("local_this_folder", "이 폴더의 PDF 8개 이상을 읽고 표로 정리해 줘.", [], True),
    ("local_word_local", "로컬 폴더에 있는 자료 5개를 읽고 비교해 줘.", [], True),
    ("local_downloads_folder", "다운로드 폴더의 파일 7개를 열어 읽고 목록으로 만들어 줘.", [], True),
    ("web_and_drive_mixed", "깃허브 사례 3개와 D:\\자료 폴더의 문서 5개를 비교해 줘.", [], True),
]

# 읽을 재료의 이름이 만들 형식을 잠그지 않는다 — 기대값은 진짜 고침의 출력(엑셀)이다.
FIX1_CASES = [
    ("readme_claude_excel", "README.md 와 CLAUDE.md 를 읽고 차이를 엑셀로 만들어 줘.", [".xlsx"], False),
    ("notes_excel_sheet", "회의 메모(notes.md)와 일정표(plan.md)를 읽고 엑셀 한 장으로 정리해 줘.", [".xlsx"], False),
    ("yaml_excel", "배포 설정 deploy.yaml 과 CLAUDE.md 를 읽고 점검표를 엑셀 파일 하나로 만들어 줘.", [".xlsx"], False),
]


def _read(ask: str) -> tuple[list[str], bool]:
    extensions = list(plan.artifact_extensions(ask))
    requirements = plan.extract(ask, own_from=ask, has_named_source=True)
    return extensions, any(r.kind == "count" and r.source_scope == "local" for r in requirements)


@pytest.mark.parametrize("name,ask,extensions,local_count", GUARD_CASES, ids=[case[0] for case in GUARD_CASES])
def test_guard_request_reading_is_kept(name, ask, extensions, local_count):
    got_extensions, got_local = _read(ask)
    assert got_extensions == extensions, (ask, got_extensions, "기대:", extensions)
    assert got_local == local_count, (ask, "local 개수 요구:", got_local, "기대:", local_count)


@pytest.mark.parametrize("name,ask,extensions,local_count", FIX1_CASES, ids=[case[0] for case in FIX1_CASES])
def test_source_file_names_do_not_lock_the_output_format(name, ask, extensions, local_count):
    got_extensions, got_local = _read(ask)
    assert got_extensions == extensions, (ask, got_extensions, "기대:", extensions)
    assert got_local == local_count, (ask, "local 개수 요구:", got_local, "기대:", local_count)
