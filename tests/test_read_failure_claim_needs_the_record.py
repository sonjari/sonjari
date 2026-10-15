"""「읽지 못했다」는 답이 거짓인지는 **기록이 먼저 말한다** (2026-10-10).

운영 판 전체에 대 본 결과다(본문을 받아 온 2,039판). 옛 규칙은 답의 낱말만 보고 「읽지 못했다고 주장했다」를 세웠고,
모델의 글에서 129판이 걸렸다 — 글귀를 직접 보니 거의 전부 모르는 칸을 모른다고 적은 정직한 보고였다. 그 판정이 서면 답을
다시 쓰게 한다. 기록으로 보아 못 읽은 것이 없을 때만 글귀를 본다 — 같은 판들에서 129 → 8(남은 것도 대부분 정직한 보고).
처음엔 「129 → 1」이라고 적었다 — 재는 스크립트가 「직접 열어 읽기」 종류의 요구를 빠뜨리고 센 값이었다.
"""
from __future__ import annotations

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.answer_gate import _READ_FAILURE_CLAIM, nothing_was_left_unread, table_cells
from alture_jarvis.plan import Requirement

READ_ALL = [(Requirement("count", "3개 이상 직접 열어 읽기", 3, grounding_required=True), True, "3개 읽음")]
READ_SOME = [(Requirement("count", "3개 이상 직접 열어 읽기", 3, grounding_required=True), False, "2개 읽음")]
OBSERVED = [(Requirement("observe", "근거가 되는 대상 실제로 읽기", 1), True, "4개 실제로 읽음")]
ONLY_A_FILE = [(Requirement("artifact", "실제 산출물 파일 만들기", "xlsx"), False, "없음")]
LISTED_ONLY = [(Requirement("count", "25개 이상 목록으로 담기", 25), True, "25줄")]


def _read(url: str, ok: bool = True) -> dict:
    return {"tool": "browser_extract", "ok": ok, "arguments": {"url": url}, "evidence": {"url": url, "text": "본문 " * 200}}


CLEAN = [_read("https://a.example/1"), _read("https://a.example/2"), _read("https://a.example/3")]
ONE_FAILED = CLEAN + [{"tool": "browser_open", "ok": False, "error": "navigation_timeout", "arguments": {"url": "https://a.example/4"}}]


# ── 기록이 「못 읽은 것이 없다」고 말하는가 ────────────────────────────────────

def test_everything_asked_was_read_and_no_read_failed() -> None:
    assert nothing_was_left_unread(READ_ALL, CLEAN)
    assert nothing_was_left_unread(OBSERVED, CLEAN)


@pytest.mark.parametrize(
    ("plan", "steps", "why"),
    [
        (READ_SOME, CLEAN, "요청한 만큼 못 읽었다 — 「나머지는 못 읽었다」는 참말이다"),
        (READ_ALL, ONE_FAILED, "읽기 걸음이 하나 실패했다 — 못 읽은 것이 있을 수 있다"),
        (ONLY_A_FILE, CLEAN, "몇 개를 읽으라는 요구가 없던 판 — 모른다"),
        (LISTED_ONLY, CLEAN, "목록으로 담으라는 개수는 읽기 요구가 아니다"),
        ([], CLEAN, "요구를 하나도 못 뽑은 판 — 모른다"),
        (None, CLEAN, "계획이 없다"),
    ],
)
def test_when_the_record_cannot_say_so_it_does_not(plan, steps, why) -> None:  # noqa: ANN001
    assert not nothing_was_left_unread(plan, steps), why


def test_a_failed_step_that_is_not_a_read_does_not_count() -> None:
    steps = CLEAN + [{"tool": "local_write_document", "ok": False, "error": "numbers_not_in_what_you_read"}]
    assert nothing_was_left_unread(READ_ALL, steps)


# ── 글귀: 「확인하지 못했다」는 「읽지 못했다」가 아니다 ─────────────────────────

@pytest.mark.parametrize(
    "honest",
    [
        "가격: 확인 불가",
        "쪽수: **확인되지 않음** (본문에 명시된 값 없음)",
        "검증 전용 두 번째 모델 호출 코드가 확인되지 않음",
        "저장 직후 화면에 완료 문구는 직접 확인하지 못했습니다",
        "요청 구현의 경계에서 결함이 확인되지 않았다",
        "두 번째 책은 아직 검색하지 못했습니다",
        "구체적인 조건은 확인되지 않았으나 지원은 가능합니다",
    ],
)
def test_saying_a_value_was_not_confirmed_is_not_a_reading_failure(honest: str) -> None:
    assert not _READ_FAILURE_CLAIM.search(honest)


@pytest.mark.parametrize(
    "claim",
    [
        "세 번째 공고는 본문 추출에 실패했습니다",
        "상세 페이지 진입 과정에서 오류가 발생하여 본문을 읽지 못했습니다",
        "검색어 입력 후 결과 목록이 나타나지 않고 화면이 변화하지 않는 상태입니다",
        "해당 페이지를 열 수 없었습니다",
    ],
)
def test_saying_the_page_could_not_be_read_is(claim: str) -> None:
    assert _READ_FAILURE_CLAIM.search(claim)


# ── 둘을 합친 판정 ─────────────────────────────────────────────────────────

def test_the_case_this_rule_was_made_for_is_still_caught() -> None:
    """제대로 셋을 읽고 「세 번째 추출 실패」라고 적은 판(사람인 라이브)."""
    answer = "두 건을 정리했습니다. 세 번째 공고는 본문 추출에 실패했습니다."
    conflict = BrowserAgent._answer_trace_conflict("공고 3개를 직접 열어 읽고 정리해줘", answer, CLEAN, READ_ALL)
    assert "읽지 못했다고 주장" in conflict


def test_an_honest_rest_was_not_read_is_left_alone() -> None:
    answer = "두 건을 정리했습니다. 나머지 한 건은 상세 페이지 진입 과정에서 막혀 본문을 읽지 못했습니다."
    for plan, steps in ((READ_SOME, CLEAN[:2]), (READ_ALL, ONE_FAILED), (ONLY_A_FILE, CLEAN)):
        assert "읽지 못했다고 주장" not in BrowserAgent._answer_trace_conflict("공고를 정리해줘", answer, steps, plan)


def test_an_unknown_cell_written_as_unknown_is_left_alone() -> None:
    """쓰기 전 숫자 문이 시키는 그대로 적은 답 — 옛 규칙은 이것을 다시 쓰게 했다."""
    answer = "| 책 | 쪽수 | ISBN |\n|---|---|---|\n| 가 | 320 | 확인 불가 |\n| 나 | 확인 불가 | 9791100000000 |\n| 다 | 412 | 9791100000001 |"
    assert "읽지 못했다고 주장" not in BrowserAgent._answer_trace_conflict("책 3권을 직접 열어 읽고 표로", answer, CLEAN, READ_ALL)


# ── 표의 칸 ────────────────────────────────────────────────────────────────

def test_an_escaped_bar_does_not_split_a_cell() -> None:
    line = '| 4 | `stopReason === "error" \\|\\| "aborted"` (하드 종료) | — |'
    assert [cell.strip() for cell in table_cells(line)] == ["4", '`stopReason === "error" || "aborted"` (하드 종료)', "—"]


@pytest.mark.parametrize(
    ("line", "cells"),
    [
        ("| a | b |", ["a", "b"]),
        ("a | b", ["a", "b"]),
        ("| a |  | c |", ["a", "", "c"]),
        ("|---|---|", ["---", "---"]),
        ("| 하나뿐 |", ["하나뿐"]),
    ],
)
def test_ordinary_rows_split_as_before(line: str, cells: list[str]) -> None:
    assert [cell.strip() for cell in table_cells(line)] == cells
