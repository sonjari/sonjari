"""링크를 모아 **거기서 글을 골라 연 목록 한 쪽**은 「직접 열어 읽은 N개」가 아니다 (2026-10-19).

`pages_turned_through`(fee4c84c)는 1 → 2 쪽으로 넘긴 목록만 잡았다 — 목록 한 쪽에서 글 아홉을 골라 열면 「10개 읽음」이었다
(그 커밋이 남은 구멍으로 적어 둔 것). 같은 날 긱뉴스 판 1bc39285 의 걸음이 이 모양이었다: `news.hada.io/show` 를 열어 읽고
`browser_links` 로 글 주소를 받아 `topic?id=…` 넷을 하나씩 열었다.

지키는 약속(`plan.pages_links_were_followed_from` → `plan.pages_results_were_opened_from` → `plan.check`):
- 그 화면에서 링크를 받았고, 그 **뒤에 처음** 연 글 가운데 **같은 모양의 주소**가 둘 이상 그 링크 목록에 있었으면 목록이다.
- 링크를 받기 전에 가 본 곳으로 돌아간 것 · 생김새가 다른 안내 페이지로 간 것(홈 → 요금 · 보안)은 목록의 증거가 아니다.
- 장부는 링크 한 줄을 80자 글로 접어 싣는다 — 잘린 주소는 앞부분으로 맞춘다.
(운영 919판 옛 · 새 대조: 충족 → 미달 3판 — steamcharts 「상위 5개」 판 셋, 홈 목록 + 게임 상세 4곳으로 「5개 읽음」이던 것.
 미달 → 충족 0판. 상세를 N개 열고도 잃은 판 0.)
"""

from __future__ import annotations

from typing import Any

from alture_jarvis import plan
from alture_jarvis.plan import Requirement, pages_links_were_followed_from

_LIST = "https://board.example/show"
_TITLE = "게시판 Show - 새 글 알리기"
_TEN = Requirement("count", "웹 자료 10개 이상 직접 열어 읽기", 10, True, "web")


def _post(n: int) -> str:
    return f"https://board.example/topic?id={35500 + 9 * n}"


def _step(tool: str, url: str, title: str = "", **extra: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {"url": url, **extra}
    if title:
        evidence["title"] = title
    return {"tool": tool, "ok": True, "evidence": evidence}


def _ledger_link(url: str) -> str:
    """장부에 실린 모양 그대로 — `str(dict)[:80]`."""
    return str({"url": url, "domain": "board.example", "text": "글 제목이 여기 들어간다"})[:80]


def _links(page: str, urls: list[str]) -> dict[str, Any]:
    return _step("browser_links", page, _TITLE, action="links", links=[_ledger_link(u) for u in urls], link_count=len(urls))


def _one_list_page_then(posts: int) -> list[dict[str, Any]]:
    steps = [_step("browser_open", _LIST, _TITLE), _step("browser_extract", _LIST, _TITLE, char_count=4174, link_ratio=78),
             _links(_LIST, [_post(n) for n in range(1, posts + 1)])]
    for n in range(1, posts + 1):
        steps.append(_step("browser_open", _post(n), f"글 {n} 제목"))
        steps.append(_step("browser_extract", _post(n), f"글 {n} 제목", char_count=2400, link_ratio=14))
    return steps


def _read(steps: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for step in steps:
        if step["tool"] == "browser_extract" and step["evidence"]["url"] not in seen:
            seen.append(step["evidence"]["url"])
    return seen


_ANSWER = "| # | 제목 |\n|---|---|\n" + "".join(f"| {n} | 글 {n} |\n" for n in range(1, 11))


def test_one_list_page_and_nine_posts_are_nine_not_ten() -> None:
    steps = _one_list_page_then(9)
    assert pages_links_were_followed_from(steps) == {_LIST}
    (_req, met, saw), = plan.check([_TEN], sources=_read(steps), steps=steps, answer=_ANSWER)
    assert not met
    assert saw.startswith("9개 읽음")
    assert "목록 화면 1곳은 세지 않음" in saw


def test_ten_posts_picked_from_one_list_page_still_count_ten() -> None:
    steps = _one_list_page_then(10)
    (_req, met, saw), = plan.check([_TEN], sources=_read(steps), steps=steps, answer=_ANSWER)
    assert met
    assert saw.startswith("10개 읽음")


def test_the_geeknews_run_marks_the_show_page() -> None:
    """1bc39285 의 걸음 모양 — 링크를 글 이름마다 따로 받았다(`contains`)."""
    steps = [_step("browser_open", _LIST, _TITLE), _step("browser_extract", _LIST, _TITLE, link_ratio=78)]
    steps += [_links(_LIST, [_post(n)]) for n in range(1, 5)]
    for n in range(1, 5):
        steps += [_step("browser_open", _post(n), f"글 {n}"), _step("browser_extract", _post(n), f"글 {n}")]
    assert pages_links_were_followed_from(steps) == {_LIST}


def test_a_long_link_cut_in_the_ledger_still_matches_by_its_front() -> None:
    long_post = "https://board.example/r/sub/comments/1wv9rzc/a_very_long_post_title_that_runs_past_eighty_chars/"
    other = "https://board.example/r/sub/comments/1wullxh/another_long_post_title_here_for_the_test/"
    page = "https://board.example/r/sub/search/?q=slow"
    steps = [_links(page, [long_post, other]),
             _step("browser_read", long_post, "글 하나"), _step("browser_read", other, "글 둘")]
    assert "'" not in _ledger_link(long_post)[-3:]          # 정말 잘렸다(닫는 따옴표가 없다)
    assert pages_links_were_followed_from(steps) == {page}


def test_one_post_reached_from_an_article_is_not_a_list() -> None:
    """글 하나에서 관련 글 하나로 건너간 것 — 본문 글은 그대로 센다."""
    steps = [_step("browser_read", _post(1), "글 1"), _links(_post(1), [_post(2)]), _step("browser_read", _post(2), "글 2")]
    assert pages_links_were_followed_from(steps) == set()


def test_site_menu_links_to_differently_shaped_pages_are_not_a_list() -> None:
    """운영 대조에서 잡은 자리(d0d36f19) — 회사 홈의 메뉴로 제품 · 보안 페이지에 간 것. 생김새가 다르다."""
    home = "https://www.company.example/"
    steps = [_step("browser_open", home, "회사"), _links(home, [f"{home}product/ai-browser/", f"{home}trust/", f"{home}blog/"]),
             _step("browser_extract", f"{home}product/ai-browser/", "제품"), _step("browser_extract", f"{home}trust/", "보안")]
    assert pages_links_were_followed_from(steps) == set()


def test_going_back_to_pages_seen_before_the_links_is_not_following_them() -> None:
    """보안 페이지의 메뉴에 홈 · 블로그가 있었고, 그 뒤에 그리로 갔다 — 링크를 받기 전에 이미 가 본 곳이다."""
    base = "https://www.company.example"
    steps = [_step("browser_read", f"{base}/item/1", "하나"), _step("browser_read", f"{base}/item/2", "둘"),
             _step("browser_read", f"{base}/trust/", "보안"),
             _links(f"{base}/trust/", [f"{base}/item/1", f"{base}/item/2"]),
             _step("browser_read", f"{base}/item/1", "하나"), _step("browser_read", f"{base}/item/2", "둘")]
    assert pages_links_were_followed_from(steps) == set()


def test_a_failed_links_step_marks_nothing() -> None:
    steps = [{"tool": "browser_links", "ok": False, "evidence": {"url": _LIST, "links": [_ledger_link(_post(1)), _ledger_link(_post(2))]}},
             _step("browser_read", _post(1), "글 1"), _step("browser_read", _post(2), "글 2")]
    assert pages_links_were_followed_from(steps) == set()


def test_a_list_only_request_still_counts_what_the_answer_lists() -> None:
    """목록이 답인 요구(「열 필요 없다」)는 그대로다 — 목록 화면을 걸러 내는 것은 읽기 근거를 따지는 요구에만."""
    listed = Requirement("count", "웹 자료 10개 이상 목록으로 담기", 10, False, "web", "", True)
    steps = _one_list_page_then(9)
    (_req, met, _saw), = plan.check([listed], sources=_read(steps), steps=steps, answer=_ANSWER)
    assert met
