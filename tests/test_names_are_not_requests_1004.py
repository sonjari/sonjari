"""파일 이름 속 낱말은 시킨 일이 아니다 · 사이트 이름표로 묶은 규칙 표는 항목 표가 아니다 (2026-10-04 밤 판 98ae0a6b).

「긱뉴스 Show GN 과 해커뉴스 Show HN 의 게시 규칙을 공식 안내에서 읽어 엑셀 「커뮤니티_게시규칙.xlsx」로」를 맡겼다.
손자리는 아홉 쪽을 읽고 스물네 줄짜리 엑셀을 만들었는데 판정은 「일부만 끝냄」이었다:

1. 파일 이름의 「게시」가 **발행 요구**로 잡혔다 → 「발행 — 실행 안 됨」.
2. 「해커뉴스 (Show HN) | ② 금지되는 것 | … | newsguidelines.html」 줄들에 「줄과 출처 페이지가 안 맞습니다」가 붙었다.
"""
from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent


def _labels(text: str) -> list[str]:
    return [requirement.label for requirement in plan.extract(text)]


# --- 1. 파일 이름 -----------------------------------------------------------------

@pytest.mark.parametrize("ask", [
    "규칙을 읽어 정리하고 결과는 엑셀 파일 「커뮤니티_게시규칙.xlsx」로 만들어 줘",
    "정리해서 게시규칙.md 로 저장해",
    "읽은 것을 블로그_발행_체크리스트.docx 로 만들어 줘",
])
def test_a_word_inside_a_file_name_is_not_a_request(ask: str) -> None:
    assert "발행" not in _labels(ask)


@pytest.mark.parametrize("ask", [
    "블로그에 글을 써서 발행해 줘",
    "네이버 블로그에 게시해줘",
    "발행_체크리스트.docx 를 읽고 블로그에 발행해 줘",
])
def test_a_real_request_is_still_read(ask: str) -> None:
    assert "발행" in _labels(ask)


def test_a_match_that_reaches_the_extension_is_kept() -> None:
    """「index.html 을 만들어 띄워」는 파일 이름이 곧 신호다 — 몸통 안에서만 걸린 것만 건너뛴다."""
    assert plan._inside_a_file_name("게시규칙.xlsx 로", 0, 2) is True
    assert plan._inside_a_file_name("index.html 로", 0, 10) is False
    assert plan._inside_a_file_name("블로그에 게시해 줘", 5, 7) is False


# --- 2. 묶음 이름표 ----------------------------------------------------------------

GUIDE = "https://news.ycombinator.com/newsguidelines.html"
FAQ = "https://news.ycombinator.com/newsfaq.html"


def _step(n: int, url: str, title: str) -> dict[str, Any]:
    return {"step": n, "tool": "browser_read", "ok": True, "error": "", "evidence": {"url": url, "title": title},
            "evidence_record": {"source_id": url, "type": "body_read", "ok": True}}


STEPS = [_step(1, GUIDE, "Hacker News Guidelines"), _step(2, FAQ, "Hacker News FAQ")]


def _table(rows: list[tuple[str, str, str, str]]) -> str:
    head = "| 사이트 | 항목 | 규칙 요약 | 출처 주소 |\n|---|---|---|---|\n"
    return head + "\n".join(f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows)


def test_rules_grouped_under_a_site_label_are_not_items() -> None:
    answer = _table([
        ("해커뉴스 (Show HN)", "① 올릴 수 있는 조건", "본인의 개인 작업을 공유할 때", FAQ),
        ("해커뉴스 (Show HN)", "② 금지되는 것", "생성된 글 금지", GUIDE),
        ("해커뉴스 (Show HN)", "② 금지되는 것", "추천·댓글 부탁 금지", GUIDE),
        ("해커뉴스 (Show HN)", "③ 제목 형식", "제목에서 사이트 이름 제거", GUIDE),
        ("해커뉴스 (Show HN)", "④ 규칙 페이지", "소개는 FAQ, 상세는 가이드라인", FAQ),
    ])

    assert BrowserAgent._row_page_binding_check(answer, STEPS) == ""


def test_an_item_row_citing_another_items_page_is_still_caught() -> None:
    """갈래 칸이 앞에 온 항목 표 — 줄마다 제 페이지가 있다. 묶음 이름표로 보지 않는다."""
    steps = [
        _step(1, "https://product.kyobobook.co.kr/detail/S000001", "초보자를 위한 파이썬 200제 | 장삼용 - 교보문고"),
        _step(2, "https://product.kyobobook.co.kr/detail/S000002", "혼자 공부하는 파이썬 | 윤인성 - 교보문고"),
    ]
    answer = (
        "| 갈래 | 책 | 가격 | 주소 |\n|---|---|---|---|\n"
        "| 국내도서 | 초보자를 위한 파이썬 200제 | 18,000원 | https://product.kyobobook.co.kr/detail/S000001 |\n"
        "| 국내도서 | 혼자 공부하는 파이썬 | 22,000원 | https://product.kyobobook.co.kr/detail/S000002 |\n"
        "| 국내도서 | 파이썬 3학년 머신러닝의 구조 | 26,000원 | https://product.kyobobook.co.kr/detail/S000001 |"
    )

    note = BrowserAgent._row_page_binding_check(answer, steps)

    assert "줄과 출처 페이지가 안 맞습니다" in note and "200제" in note
