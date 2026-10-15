"""산출물 차례에서도 **방금 처음 연 페이지의 첫 읽기**는 막지 않는다 (2026-10-04 새벽 레딧 판 33cac79a).

글 다섯을 찾아 엑셀로 정리하라는 과제에서, 다섯째 글을 **연 바로 그 순간** 산출물 차례가 시작됐다. 그 글을 읽는 걸음이
네 번 거절됐고, 모델은 연 글을 못 읽은 채로는 파일을 안 쓰고 예고로 끝났다 — 엑셀 0개.

차례의 뜻은 「새로 검색·열기를 하지 마라」다(9d6942f2: 차례를 받고도 페이지를 세 번 더 열어 걸음을 다 썼다).
이미 연 페이지를 읽는 것은 거기 안 든다. 예외는 좁다 — 바로 앞 걸음이 그 주소의 첫 열기일 때 읽기 한 번.
"""
from __future__ import annotations

import inspect
from typing import Any

from alture_jarvis import agent

POST = "https://www.reddit.com/r/LocalLLaMA/comments/1vl3frs/llamacpp_parallel_agents/"
LIST = "https://www.reddit.com/r/LocalLLaMA/search/?q=parallel"


def _open(url: str, ok: bool = True) -> dict[str, Any]:
    return {"tool": "browser_open", "ok": ok, "arguments": {"url": url}, "evidence": {"url": url}}


def _read(tool: str = "browser_extract", ok: bool = True) -> dict[str, Any]:
    return {"tool": tool, "ok": ok, "arguments": {}, "evidence": {}}


def test_the_first_read_of_a_page_just_opened_is_allowed() -> None:
    steps = [_open(LIST), _read(), _open(POST)]

    assert agent._reads_page_just_opened("browser_extract", steps)
    assert agent._reads_page_just_opened("browser_read", steps)


def test_rereads_and_reopens_stay_refused() -> None:
    # 이미 읽었다 — 바로 앞 걸음이 열기가 아니다.
    assert not agent._reads_page_just_opened("browser_extract", [_open(POST), _read()])
    # 같은 주소를 다시 연 뒤의 읽기 — 되읽기다.
    assert not agent._reads_page_just_opened("browser_extract", [_open(POST), _read(), _open(POST)])
    # 열기가 실패했다 — 읽을 페이지가 없다.
    assert not agent._reads_page_just_opened("browser_extract", [_open(POST, ok=False)])
    assert not agent._reads_page_just_opened("browser_extract", [])


def test_only_reading_is_let_through_not_more_searching() -> None:
    steps = [_open(POST)]

    for hand in ("browser_open", "browser_search", "browser_site_search", "browser_open_result", "browser_links", "browser_scroll"):
        assert not agent._reads_page_just_opened(hand, steps), hand


def test_the_stage_refusal_asks_this_before_refusing() -> None:
    source = inspect.getsource(agent)
    refusal = source[source.index("elif stage_hands is not None and name not in stage_hands and not ("):]
    refusal = refusal[:refusal.index("observation = {")]

    assert "or _reads_page_just_opened(name, steps)" in refusal
    # 「전부」 판에만 걸려 있던 예외의 읽기 쪽을 넓힌 것이다 — 새 주소 열기는 여전히 그 판에서만.
    assert "_wants_everything" in refusal and "_fresh_read_for_everything(name, arguments, steps)" in refusal
    # 차례가 없는 자리(코드 판의 최종 답 강제 — 손이 하나도 없다)에는 안 걸린다.
    assert "stage_hands and (" in refusal


# --- 열어 놓고 못 읽은 글 (93f08e95) -------------------------------------------

OTHER = "https://www.reddit.com/r/LocalLLaMA/comments/1wullxh/tp6_can_work_on_vllm/"


def test_a_page_opened_but_never_read_may_be_reopened_once_and_read() -> None:
    """다섯 글 중 하나를 열고 안 읽은 채 다음 글로 갔다 — 차례 뒤에 돌아가려는 것을 「이미 연 주소」로 막아 표가 네 줄이 됐다."""
    steps = [_open(LIST), _read(), _open(POST), _open(OTHER), _read()]  # POST 는 열기만 했다

    assert agent._reopens_unread_page("browser_open", {"url": POST}, steps)
    after = [*steps, _open(POST)]
    assert agent._reads_page_just_opened("browser_extract", after)  # 두 번째 열기지만 한 번도 못 읽었다


def test_read_pages_and_third_opens_stay_refused() -> None:
    read_already = [_open(POST), _read(), _open(OTHER)]
    assert not agent._reopens_unread_page("browser_open", {"url": POST}, read_already)  # 읽은 글로 돌아가기
    twice = [_open(POST), _open(OTHER), _open(POST)]
    assert not agent._reopens_unread_page("browser_open", {"url": POST}, twice)  # 세 번째 열기
    assert not agent._reopens_unread_page("browser_open", {"url": "https://new.example.com/x"}, read_already)  # 새 주소
    assert not agent._reopens_unread_page("browser_search", {"query": "x"}, read_already)


def test_the_stage_refusal_also_asks_about_unread_pages() -> None:
    source = inspect.getsource(agent)
    refusal = source[source.index("elif stage_hands is not None and name not in stage_hands and not ("):]
    refusal = refusal[:refusal.index("observation = {")]

    assert "or _reopens_unread_page(name, arguments, steps)" in refusal
