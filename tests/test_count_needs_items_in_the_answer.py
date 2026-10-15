"""읽은 개수가 아니라 **낸 개수**로 판정한다.

## 왜 (2026-09-12 실측)

yes24 판이 상세를 여섯 곳 읽고 표에 **한 권만** 써서 냈는데 개수 요구가
충족으로 통과했다. 장부에 자기 입으로 이렇게 적혀 있었다:

    count 요구  "3개 이상 직접 열어 읽기"  met=True  "6개 읽음 · 답에 1개"

읽기는 조건이고 목적이 아니다. 시킨 것은 「세 권을 내라」였다.

## 왜 눈금을 먼저 고쳤나

이 규칙만 켜고 과거 445판에 대 보니 **33.6%가 뒤집혔다.** 그 대부분이 진짜
미달이 아니라 `count_listed_items` 의 과소 계수였다 — 불릿이 하나라도 있으면
표를 아예 안 봤는데, 우리 답 끝에는 거의 항상 「산출물 정보: 파일명 / 경로」
불릿이 붙는다. 3줄짜리 표를 완성하고도 「답에 2개」로 찍혔고, 같은 판에
채움 채점기는 12/12 만점을 줬다.

눈금을 고치니 2.7%로 내려갔고 남은 것은 열어 보니 전부 진짜였다.
"""

from __future__ import annotations

from alture_jarvis.plan import check as check_plan, count_listed_items, extract as extract_plan

PROMPT = "YES24에서 파이썬 책 3권의 쪽수와 ISBN 을 조사해서 마크다운 문서로 만들어줘."

THREE_ROWS = """YES24 조사 결과입니다.

| 도서명 | 쪽수 | ISBN |
| :--- | :--- | :--- |
| 점프 투 파이썬 | 432쪽 | 9791163034735 |
| 혼자 공부하는 파이썬 | 552쪽 | 9791162245651 |
| 파이썬 EXPRESS | 732쪽 | 9791194630500 |

**[산출물 정보]**
*   **파일명:** python_books.md
*   **경로:** 문서 폴더
"""

ONE_ROW = """YES24 조사 결과입니다.

| 도서명 | 쪽수 | ISBN |
| :--- | :--- | :--- |
| 점프 투 파이썬 | 432쪽 | 9791163034735 |

**[산출물 정보]**
*   **파일명:** python_books.md
*   **경로:** 문서 폴더
"""


def _read(count: int) -> tuple[list[str], list[dict[str, object]]]:
    urls = [f"https://www.yes24.com/product/goods/{100 + i}" for i in range(count)]
    steps = [
        {"tool": "browser_extract", "ok": True, "evidence": {"url": url}} for url in urls
    ]
    return urls, steps


def _count_result(answer: str, read: int = 6):
    urls, steps = _read(read)
    plan = extract_plan(PROMPT, has_named_source=True)
    results = check_plan(plan, sources=urls, steps=steps, answer=answer)
    return next((ok, saw) for req, ok, saw in results if req.kind == "count")


def test_the_tail_bullets_no_longer_hide_the_table() -> None:
    """「산출물 정보」 불릿 둘이 3줄짜리 표를 가리고 있었다."""
    assert count_listed_items(THREE_ROWS) == 3


def test_six_pages_read_but_one_row_written_is_not_done() -> None:
    ok, saw = _count_result(ONE_ROW)
    assert ok is False
    assert "6개 읽음" in saw and "답에 1개" in saw


def test_three_rows_passes() -> None:
    ok, _saw = _count_result(THREE_ROWS)
    assert ok is True


def test_mid_run_has_no_answer_yet_so_it_does_not_block() -> None:
    """답을 쓰기 전에 「모자라다」고 말할 수는 없다 — 판 중간 대조는 읽기만 본다."""
    ok, _saw = _count_result("")
    assert ok is True


def test_a_sentence_that_lists_three_things_is_not_punished() -> None:
    """한 문장에 늘어놓은 답은 **세지 못한다** — 못 세는 것을 미달로 찍지 않는다.

    이 규칙을 넓게 걸었더니 기존 시험 하나가 깨져서 잡았다. 그 판의 답은
    「정규직 공고 1, 정규직 공고 2, 정규직 공고 3을 모두 확인했습니다」였다.
    셋을 제대로 냈는데 표도 불릿도 없어 0개로 세어진다. 막았으면 제대로 낸
    판을 막은 것이다.
    """
    ok, _saw = _count_result("정규직 공고 1, 정규직 공고 2, 정규직 공고 3을 모두 확인했습니다.")
    assert ok is True


def test_listing_fewer_than_asked_is_still_caught() -> None:
    """세어지는데 모자라면 막는다 — 「완료했습니다」 + 진척 불릿만 있던 실제 판."""
    progress = chr(10).join([
        "상위 3개 서비스 상세 읽기를 완료하였습니다.",
        "* **상세 읽기:** 완료",
        "* **데이터 검증:** 완료",
    ])
    ok, saw = _count_result(progress)
    assert ok is False
    assert "답에 2개" in saw
