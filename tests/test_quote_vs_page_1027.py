"""「원문 한 문장」 칸이 정말 그 페이지의 원문인가 (2026-10-27 증상 시험 — 하이 몫).

운영 판 d72ca482 · f52e0d50: 「각 방법 옆에 그 문서의 원문 한 문장(영어 그대로)과 주소를 붙여 달라」는 요청에
엑셀의 「원문 한 문장」 칸 20줄을 채웠다. 걸음 기록에는 본문이 짧게만 남아 나중에 대조할 수 없었고,
실행 중에 그 칸을 읽은 본문과 맞춰 본 검사는 없다 — 모델이 고쳐 쓴 문장도 「원문」으로 나간다.
(금액은 이미 `_row_facts_vs_page_check` 가 그 줄의 페이지와 맞춘다. 인용은 아무도 안 본다.)

정한 모양(구현은 이 모양만 지키면 된다):
  BrowserAgent._quote_vs_page_check(asked, answer, steps, job_id) -> str
    · 인용 칸 = 머리줄에 「원문」 · 「인용」 · "quote" 가 든 칸. 답의 표와 `local_write_document` 의 표(sheets) 둘 다 본다.
    · 그 줄에 연 페이지 주소가 있으면 **그 페이지**의 본문에서, 없으면 읽은 본문 전체에서 찾는다.
    · 띄어쓰기 · 줄바꿈 · 곧은/굽은 따옴표 · 대소문자 차이는 같은 문장으로 본다. 빈 칸 · 아주 짧은 칸은 안 본다.
    · 못 찾은 줄이 있으면 「원문과 다름」이 든 경고를 돌려준다(그 줄의 첫 칸 이름 · 최대 셋). 없으면 빈 글.
  그리고 `run()` 이 다른 대조 경고 옆에서 이것을 붙인다.
"""
from __future__ import annotations

import inspect
from typing import Any

from alture_jarvis.agent import BrowserAgent

LIMITS = "https://support.claude.com/en/articles/9797557-usage-limit-best-practices"
CODE = "https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code"

PAGES = {
    LIMITS: ("Usage limit best practices",
             "Usage limit best practices\nYour usage limits are based on a 5-hour session limit and a weekly limit.\n"
             "When you reach a limit, you can wait for it to reset."),
    CODE: ("Models, usage, and limits in Claude Code",
           "Models, usage, and limits in Claude Code\nCLAUDE.md is loaded at the start of every session, "
           "so keep it concise — ideally under 200 lines.\nUse /usage to see where your usage went."),
}
ASKED = ("앤트로픽 공식 문서에서 Claude 사용 한도와 비용을 덜 쓰는 방법을 찾아, 각 방법 옆에 그 문서의 "
         "원문 한 문장(영어 그대로)과 문서 주소를 붙여 엑셀 한 장으로 정리해 주세요.")


def _steps(rows: list[list[str]] | None = None) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {"step": index, "tool": "browser_extract", "ok": True,
         "evidence": {"url": url, "title": title},
         "evidence_record": {"type": "body_read", "ok": True, "source_id": url, "step": index}}
        for index, (url, (title, _body)) in enumerate(PAGES.items(), start=1)
    ]
    if rows is not None:
        steps.append({
            "step": len(steps) + 1, "tool": "local_write_document", "ok": True,
            "arguments": {"format": "xlsx", "path": "정리.xlsx",
                          "sheets": {"정리": [["문서", "방법", "원문 한 문장", "주소"], *rows]}},
            "evidence": {"action": "local_write_document", "format": "xlsx", "verified": True},
        })
    return steps


def _agent() -> BrowserAgent:
    agent = object.__new__(BrowserAgent)
    bodies = {BrowserAgent._url_key(url): body for url, (_title, body) in PAGES.items()}
    agent._page_bodies = lambda _steps, _job: bodies  # type: ignore[method-assign]
    return agent


def _check(*, answer: str = "", rows: list[list[str]] | None = None, asked: str = ASKED) -> str:
    return _agent()._quote_vs_page_check(asked, answer, _steps(rows), "job")


GOOD = ["Usage limit best practices", "두 창으로 센다",
        "Your usage limits are based on a 5-hour session limit and a weekly limit.", LIMITS]
REWRITTEN = ["Models, usage, and limits in Claude Code", "지침은 200줄 아래로",
             "Keep your CLAUDE.md file under 200 lines.", CODE]


# --- 엑셀에 쓴 표 ---------------------------------------------------------------

def test_a_rewritten_quote_in_the_written_sheet_is_named() -> None:
    notes = _check(rows=[GOOD, REWRITTEN])

    assert "원문과 다름" in notes
    assert "Models, usage, and limits in Claude Code" in notes
    assert "Usage limit best practices" not in notes, "그 페이지에 그대로 있는 문장은 부르지 않는다"


def test_spacing_quotes_and_case_are_the_same_sentence() -> None:
    loose = ["Usage limit best practices", "두 창",
             "  your usage limits are based on a 5-hour  session limit\nand a weekly limit ", LIMITS]
    curly = ["Models, usage, and limits in Claude Code", "/usage",
             "Use “/usage” to see where your usage went.", CODE]
    # 굽은 따옴표는 본문에 없지만 곧은 따옴표도 없다 — 따옴표를 떼고 보면 같은 문장이다.
    assert _check(rows=[loose]) == ""
    assert _check(rows=[curly]) == ""


def test_a_quote_that_lives_on_another_page_is_still_named() -> None:
    """금액 검사가 「읽은 글 어딘가에 있으면 통과」로 틀렸던 자리(10-04). 주소가 있는 줄은 그 페이지에서만 찾는다."""
    swapped = ["Models, usage, and limits in Claude Code", "두 창",
               "Your usage limits are based on a 5-hour session limit and a weekly limit.", CODE]
    assert "원문과 다름" in _check(rows=[swapped])


def test_a_row_without_an_opened_address_is_looked_up_in_every_page() -> None:
    no_url = ["한도 문서", "두 창", "Your usage limits are based on a 5-hour session limit and a weekly limit.", ""]
    assert _check(rows=[no_url]) == ""
    made_up = ["한도 문서", "두 창", "Limits reset every Monday at midnight UTC for all plans.", ""]
    assert "원문과 다름" in _check(rows=[made_up])


def test_empty_and_tiny_cells_are_not_checked() -> None:
    empty = ["Models, usage, and limits in Claude Code", "-", "", CODE]
    tiny = ["Models, usage, and limits in Claude Code", "-", "200", CODE]
    assert _check(rows=[empty, tiny]) == ""


def test_a_link_column_named_original_is_not_a_quote_column() -> None:
    """「원문 링크」 칸의 주소를 문장처럼 대조하면 모든 줄에 경고가 난다. 문장 칸이 틀리면 여전히 경고한다."""
    head = ["문서", "원문 링크", "원문 한 문장"]
    ok = ["한도 문서", LIMITS, "Your usage limits are based on a 5-hour session limit and a weekly limit."]
    bad = ["코드 문서", CODE, "Keep your CLAUDE.md file under 200 lines."]

    def run(rows: list[list[str]]) -> str:
        steps = _steps()
        steps.append({"step": 9, "tool": "local_write_document", "ok": True,
                      "arguments": {"format": "xlsx", "path": "x.xlsx", "sheets": {"정리": [head, *rows]}}})
        return _agent()._quote_vs_page_check(ASKED, "", steps, "job")

    assert run([ok]) == ""
    notes = run([ok, bad])
    assert "원문과 다름" in notes and "코드 문서" in notes and "한도 문서" not in notes


# --- 답의 표 ----------------------------------------------------------------------

def test_the_answer_table_is_checked_too() -> None:
    answer = (
        "| 문서 | 방법 | 원문 한 문장 | 주소 |\n|---|---|---|---|\n"
        f"| Models, usage, and limits in Claude Code | 200줄 | Keep your CLAUDE.md file under 200 lines. | {CODE} |\n"
    )
    assert "원문과 다름" in _check(answer=answer)


def test_no_quote_column_means_no_note() -> None:
    plain = [["Usage limit best practices", "두 창", "5시간", LIMITS]]
    steps = _steps()
    steps.append({"step": 9, "tool": "local_write_document", "ok": True,
                  "arguments": {"format": "xlsx", "path": "x.xlsx",
                                "sheets": {"정리": [["문서", "방법", "숫자", "주소"], *plain]}}})
    assert _agent()._quote_vs_page_check(ASKED, "", steps, "job") == ""


# --- 붙는 자리 ----------------------------------------------------------------------

def test_run_attaches_the_quote_check_next_to_the_other_page_checks() -> None:
    source = inspect.getsource(BrowserAgent.run)
    assert "self._quote_vs_page_check(" in source
    assert source.index("self._row_facts_vs_page_check(") < source.index("self._quote_vs_page_check(") < source.index(
        "friction_note ="
    ), "다른 대조 경고(check_notes.wrap) 안에 붙어야 한다"


# --- 인용 칸이 아닌 머리말 (10-27 손질) ------------------------------------------------

def test_quote_head_rule_drops_non_sentence_headers_and_keeps_real_quote_headers() -> None:
    """머리말 판정: 빠져야 하는 것은 링크 · 출처 · 요지 · 요약 · 방식 · 검증 · 개수 칸, 남아야 하는 것은 진짜 인용 칸."""
    def is_quote_column(head: str) -> bool:
        return bool(BrowserAgent._QUOTE_HEAD.search(head) and not BrowserAgent._QUOTE_HEAD_NOT.search(head))

    dropped = ["원문 링크", "인용 출처", "원문 요지", "설명 (원문 요약)", "인용 및 검증 방식 (Citation)", "인용 수",
               "원문 수", "원문 수 (개)", "인용 수:", "Quote URL"]
    kept = ["원문 한 문장", "원문 수록 문장", "수정 전 원문", "수정한 원문", "인용", "quote", "Quote", "인용문", "원문(영어)"]
    for head in dropped:
        assert not is_quote_column(head), f"{head!r} 는 인용 칸이 아니다"
    for head in kept:
        assert is_quote_column(head), f"{head!r} 는 인용 칸이다"


def test_summary_and_method_columns_are_not_compared_with_the_page() -> None:
    """실제로 대조에서도 빠진다 — 요지 · 방식 칸의 문장이 본문에 없어도 경고가 나지 않고, 문장 칸이 틀리면 여전히 경고한다."""
    head = ["문서", "원문 요지", "인용 및 검증 방식 (Citation)", "수정한 원문"]

    def run(rows: list[list[str]]) -> str:
        steps = _steps()
        steps.append({"step": 9, "tool": "local_write_document", "ok": True,
                      "arguments": {"format": "xlsx", "path": "x.xlsx", "sheets": {"정리": [head, *rows]}}})
        return _agent()._quote_vs_page_check(ASKED, "", steps, "job")

    ok = ["한도 문서", "한도를 두 창으로 센다는 뜻의 요약 문장입니다", "페이지에서 직접 옮겨 적음 확인",
          "Your usage limits are based on a 5-hour session limit and a weekly limit."]
    bad = ["코드 문서", "지침은 짧게 두라는 요지의 문장입니다", "페이지에서 직접 옮겨 적음 확인",
           "Keep your CLAUDE.md file under 200 lines."]
    assert run([ok]) == ""
    notes = run([ok, bad])
    assert "원문과 다름" in notes and "코드 문서" in notes and "한도 문서" not in notes
