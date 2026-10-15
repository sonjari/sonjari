"""웹에서 찾으라는 요청 속의 「문서」·「파일」은 읽을 로컬 자료가 아니다 (2026-10-06 국내 조사 두 판).

「구글과 네이버에서 … 한글 문서를 만들어 주는 AI 에이전트 … 5개 이상」이 「로컬 자료 5개 이상 직접 열어 읽기」가 됐다.
이어서 시킨 판은 「(지금 그 파일은 머리줄만 있다)」의 「파일」 — **만들 파일 자신** — 을 읽을 자료로 셌다. 오독된 요구는
끝까지 미달이라 다음 수 안내가 「본문을 열어라」로만 나갔고, 「상세 대신 열기」 안전망도 꺼졌다.

거꾸로도 지킨다: 웹을 이름 댔어도 「내 PC 파일 3개를 읽어」처럼 **읽을 자료로 쓴** 「파일」은 로컬이다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import _last_file_as_source, _scoped_count_targets

FIRST_RUN = (
    "구글과 네이버에서 「한국 회사나 한국 개인이 만든, AI 에이전트 데스크톱 앱 또는 PC에서 일을 대신 해 주는 AI 도구」를 "
    "찾아 줘. 찾는 조건은 셋이다: ① 한국에서 만들었다 ② 웹 브라우저를 직접 조작해 조사하거나, 엑셀·한글·워드 같은 문서를 "
    "만들어 준다 ③ PC에 설치해 쓰거나 PC의 브라우저·파일을 다룬다. 검색어 예: 「국내 AI 에이전트 데스크톱 앱」, "
    "「로컬 AI 에이전트 한국」, 「한글 문서 AI 에이전트」. 5개 이상의 제품을 각각 공식 페이지나 기사를 직접 열어 읽고 "
    "엑셀 「국내_AI_에이전트_조사.xlsx」로 정리해 줘."
)
SECOND_RUN = (
    "이어서 해줘. 방금 판에서 이미 읽은 페이지(example.com, 네이버 블로그 글들, blog.example.org 등)에서 확인한 "
    "제품을 먼저 「국내_AI_에이전트_조사.xlsx」에 한 줄씩 채워 넣어 줘(지금 그 파일은 머리줄만 있다). 그다음 모자라면 "
    "구글·네이버에서 더 찾아 5개 이상이 되게 해 줘."
)


@pytest.mark.parametrize("request_text", [
    FIRST_RUN,
    "구글과 네이버에서 한글 문서를 만들어 주는 AI 에이전트 제품 5개를 찾아 읽고 엑셀로 정리해 줘",
    "네이버에서 파일을 다루는 국산 프로그램 4개를 검색해서 읽고 비교해 줘",
    "인터넷에서 PDF 파일 변환 도구 3개를 찾아 읽고 장단점을 정리해 줘",
])
def test_a_web_request_that_mentions_documents_or_files_is_not_read_as_local(request_text: str) -> None:
    assert "local" not in dict(_scoped_count_targets(request_text)), _scoped_count_targets(request_text)


def test_the_file_being_made_is_not_a_source_to_read() -> None:
    assert _scoped_count_targets(SECOND_RUN) == [("web", 5)]


@pytest.mark.parametrize("request_text", [
    "구글에서 찾아보고, 내 PC 파일 3개도 읽어서 같이 정리해 줘",
    "네이버에서 검색한 뒤 첨부한 파일 2개를 읽고 차이를 알려 줘",
    "인터넷 검색은 됐고, 다운로드 폴더의 파일 4개를 열어 요약해 줘",
    "구글에서 본 내용과 로컬 파일 3개를 비교해 줘",
])
def test_a_file_used_as_something_to_read_is_still_local_even_when_the_web_is_named(request_text: str) -> None:
    assert "local" in dict(_scoped_count_targets(request_text)), _scoped_count_targets(request_text)


@pytest.mark.parametrize("request_text", [
    "내 문서 3개를 읽고 요약해 줘",
    "폴더의 파일 5개를 비교해 줘",
    "로컬 문서 3개와 웹 자료 3개를 읽고 정리해 줘",
])
def test_requests_that_name_no_web_place_read_as_before(request_text: str) -> None:
    assert "local" in dict(_scoped_count_targets(request_text)), _scoped_count_targets(request_text)


def test_which_mentions_of_a_file_count_as_a_source() -> None:
    assert _last_file_as_source("PC의 브라우저·파일을 다룬다") == -1
    assert _last_file_as_source("지금 그 파일은 머리줄만 있다") == -1
    assert _last_file_as_source("엑셀 파일로 정리해") == -1
    assert _last_file_as_source("내 PC 파일 3개를 읽어") >= 0
    assert _last_file_as_source("첨부한 파일을 분석해") >= 0
    assert _last_file_as_source("파일 3개를 열어 보고") >= 0
