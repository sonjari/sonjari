"""쪽만 넘긴 **같은 목록 화면**은 「직접 열어 읽은 N개」가 아니다 (2026-10-19 운영 판 1b6df02d).

「목록을 1쪽부터 10쪽까지(…?page=2 처럼) 넘기며 … 10개 골라 하나씩 직접 열어 읽어 줘」에 손자리는 목록 열 쪽만
`browser_open` → `browser_read` 로 읽고 글은 하나도 안 열었다. 계획은 「웹 자료 10개 이상 직접 열어 읽기 — 10개 읽음」으로
충족을 찍었고(진행 표시도 같았다), 남은 요구가 없는 줄 안 마무리 문이 판을 접었다 — 표 아홉 칸 중 다섯이 「확인 못 함」.
마무리 검사는 「못 읽었다」는 정직한 답을 「본문을 10곳에서 받아 왔는데 읽지 못했다고 주장」으로 몰기까지 했다.

지키는 약속(`plan.pages_turned_through` → `plan.pages_results_were_opened_from` → `plan.check`):
- 같은 자리 · 같은 나머지 조건에서 **숫자 값 하나만** 첫 쪽 → 2 로 이어지고, 읽은 화면의 **제목이 같으면** 쪽을 넘긴 목록이다.
- 글 번호만 다른 상세는 목록이 아니다 — 제목이 다르거나(보통), 제목이 사이트 이름뿐이어도 번호가 1 · 2 로 이어지지 않는다.
- 제목을 모르면 가르지 않는다.
(운영 919판 옛 · 새 대조: 충족 → 미달 2판 — 이 판과, 상세 셋 + 빈 목록 두 쪽으로 「5개 읽음」이던 판. 미달 → 충족 0판.)
"""

from __future__ import annotations

from typing import Any

from alture_jarvis import plan
from alture_jarvis.answer_gate import nothing_was_left_unread
from alture_jarvis.plan import Requirement, pages_turned_through

_LIST = "https://board.example/show"
_LIST_TITLE = "게시판 Show - 새 글 알리기"
_TEN = Requirement("count", "웹 자료 10개 이상 직접 열어 읽기", 10, True, "web")


def _page(n: int) -> str:
    return _LIST if n == 1 else f"{_LIST}?page={n}"


def _post(n: int) -> str:
    return f"https://board.example/topic?id={30000 + 37 * n}"


def _step(tool: str, url: str, title: str = "", **extra: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {"url": url, **extra}
    if title:
        evidence["title"] = title
    return {"tool": tool, "ok": True, "evidence": evidence}


def _paging_steps() -> list[dict[str, Any]]:
    """1b6df02d 의 걸음 모양 — 목록 열 쪽을 열고 읽은 뒤, 마지막 쪽에서 링크만 모았다."""
    steps: list[dict[str, Any]] = [{"tool": "site_list", "ok": True, "evidence": {}}]
    for n in range(1, 11):
        steps.append(_step("browser_open", _page(n), _LIST_TITLE, action="opened"))
        steps.append(_step("browser_read", _page(n), _LIST_TITLE, action="read", char_count=5200))
    steps.append(_step("browser_links", _page(10), _LIST_TITLE, action="links"))
    return steps


def _read(steps: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for step in steps:
        if step["tool"] == "browser_read":
            url = step["evidence"]["url"]
            if url not in seen:
                seen.append(url)
    return seen


_ANSWER = "| # | 제목 | 점수 |\n|---|---|---|\n" + "".join(f"| {n} | 글 {n} | {50 - n} |\n" for n in range(1, 11))


def test_ten_pages_of_one_list_are_not_ten_posts_read() -> None:
    steps = _paging_steps()
    assert pages_turned_through(steps) == {_page(n) for n in range(1, 11)}
    (_req, met, saw), = plan.check([_TEN], sources=_read(steps), steps=steps, answer=_ANSWER)
    assert not met
    assert saw.startswith("0개 읽음")
    assert "목록 화면 10곳은 세지 않음" in saw


def test_the_reading_is_still_unmet_in_the_middle_of_the_run_so_the_loop_is_told_what_is_left() -> None:
    steps = _paging_steps()
    results = plan.check([_TEN], sources=_read(steps), steps=steps)
    assert not plan.enough_to_stop(results)
    assert "웹 자료 10개 이상 직접 열어 읽기" in plan.remaining_note(results)
    # 정직하게 「못 읽었다」고 쓴 답을 「받아 와 놓고 못 읽었다고 주장」으로 몰지 않는다.
    assert not nothing_was_left_unread(results, steps)


def test_after_paging_the_ten_opened_posts_are_what_count() -> None:
    steps = _paging_steps()
    for n in range(1, 11):
        steps.append(_step("browser_open", _post(n), f"글 {n} 제목", action="opened"))
        steps.append(_step("browser_read", _post(n), f"글 {n} 제목", action="read", char_count=3000))
    (_req, met, saw), = plan.check([_TEN], sources=_read(steps), steps=steps, answer=_ANSWER)
    assert met
    assert saw.startswith("10개 읽음")


def test_nine_posts_after_paging_are_nine_not_ten() -> None:
    steps = _paging_steps()
    for n in range(1, 10):
        steps.append(_step("browser_read", _post(n), f"글 {n} 제목", char_count=3000))
    (_req, met, saw), = plan.check([_TEN], sources=_read(steps), steps=steps, answer=_ANSWER)
    assert not met
    assert saw.startswith("9개 읽음")


def test_posts_whose_title_is_only_the_site_name_stay_posts() -> None:
    """운영 대조에서 잡은 자리 — 상세 제목이 사이트 이름뿐인 곳. 글 번호는 크고 띄엄띄엄이라 쪽 넘김이 아니다."""
    steps = [_step("browser_read", f"https://gov.example/notice.do?menu=1&sn={sn}", "포털>공고>상세화면")
             for sn in (175783, 176076, 177210)]
    assert pages_turned_through(steps) == set()


def test_the_same_page_reopened_with_a_numeric_flag_is_not_a_list() -> None:
    steps = [_step("browser_read", "https://video.example/watch?v=abc", "영상 제목"),
             _step("browser_read", "https://video.example/watch?v=abc&refresh=1", "영상 제목")]
    assert pages_turned_through(steps) == set()


def test_posts_numbered_one_and_two_with_their_own_titles_stay_posts() -> None:
    steps = [_step("browser_read", "https://small.example/view?id=1", "첫 글"),
             _step("browser_read", "https://small.example/view?id=2", "둘째 글")]
    assert pages_turned_through(steps) == set()


def test_without_titles_nothing_is_guessed() -> None:
    steps = [_step("browser_read", _page(n)) for n in range(1, 4)]
    assert pages_turned_through(steps) == set()


def test_a_failed_step_does_not_mark_a_page() -> None:
    steps = [_step("browser_read", _page(1), _LIST_TITLE),
             {"tool": "browser_read", "ok": False, "evidence": {"url": _page(2), "title": _LIST_TITLE}}]
    assert pages_turned_through(steps) == set()


def test_a_list_only_request_still_counts_what_the_answer_lists() -> None:
    """목록이 답인 요구(「열 필요 없다」)는 그대로다 — 목록 화면을 걸러 내는 것은 읽기 근거를 따지는 요구에만."""
    listed = Requirement("count", "웹 자료 10개 이상 목록으로 담기", 10, False, "web", "", True)
    steps = _paging_steps()
    (_req, met, _saw), = plan.check([listed], sources=_read(steps), steps=steps, answer=_ANSWER)
    assert met
