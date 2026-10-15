"""읽을 재료로 쓰인 형식 낱말은 만들 파일의 형식이 아니다 — 「엑셀을 읽어서 웹페이지로」.

★ 2026-10-13 영상 촬영 판(코드 모드 · 27B): 「이 폴더의 가격표 엑셀을 읽어서 한눈에 보는 웹페이지로 만들어 줘」에 손자리는 html 을
  만들어 화면에 띄웠는데, 대조표는 「실제 산출물 파일 만들기 — 열 수 있는 산출물 없음」 · 판은 partial 로 끝났다.
  「엑셀」이라는 낱말만 보고 만들 파일을 .xlsx 로 정한 탓이다. 「파이썬 책」의 파이썬을 소재로 가려내는 것(09-07)과 같은 자리다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import artifact_extensions


@pytest.mark.parametrize("prompt,expected", [
    ("이 폴더의 가격표 엑셀을 읽어서 한눈에 보는 웹페이지로 만들어 줘", ()),
    ("엑셀 파일에서 매출을 뽑아 워드 보고서로 만들어줘", (".docx",)),
    ("매출표.xlsx 를 읽어서 요약 문서로 만들어줘", ()),
    ("이 워드 문서를 읽고 핵심만 엑셀로 정리해줘", (".xlsx",)),
    ("이 엑셀을 읽고 반별 평균을 내서 새 엑셀 파일로 저장해줘", (".xlsx",)),          # 앞의 엑셀은 재료, 뒤의 엑셀이 만들 것
    ("한글 파일의 내용을 피피티로 바꿔줘", (".pptx",)),
])
def test_a_format_that_is_the_source_is_not_required_as_the_output(prompt: str, expected: tuple[str, ...]) -> None:
    assert artifact_extensions(prompt) == expected


@pytest.mark.parametrize("prompt,expected", [
    ("Read INSTRUCTIONS.md and implement beer_song.py. Run the tests and make them all pass.", (".py",)),
    ("Read notes.md and make a Hangul document of the key points.", (".hwpx", ".hwp")),
    ("Fix the bug in tidy.py and save the notes to notes.md", (".py", ".md")),          # 「in tidy.py」는 고칠 파일이다
    ("Save the summary as report.md", (".md",)),
])
def test_english_reads_the_same_way(prompt: str, expected: tuple[str, ...]) -> None:
    """영어는 읽는 말이 파일 이름 앞에 온다. 한국어만 고치면 두 언어의 풀이가 갈린다(동등성 시험이 잡았다)."""
    assert artifact_extensions(prompt) == expected


@pytest.mark.parametrize("prompt,expected", [
    ("세 가게의 가격을 조사해서 엑셀로 정리해 줘", (".xlsx",)),
    ("엑셀 파일 만들어줘", (".xlsx",)),
    ("회의록을 워드 파일로 만들어줘", (".docx",)),
    ("조사한 내용을 한글이나 워드 파일로 전달해 줘", (".hwpx", ".hwp", ".docx")),
    ("결과를 report.md 로 저장해줘", (".md",)),
])
def test_a_format_that_is_asked_for_is_still_required(prompt: str, expected: tuple[str, ...]) -> None:
    assert artifact_extensions(prompt) == expected
