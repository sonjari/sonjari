"""「이 화면까지 가라」도 시킨 것이다 — 그 화면에 실제로 서기 전에는 「다 했다」로 접지 않는다 (2026-10-30 · 10-29 앱 판 cae8f0fe).

「…Compare the top 3 by their latest reviews, pick the best, and take it to the Confirm and pay page.」 — 계획에 「3개 이상 읽기」
한 칸만 서서, 넷째 숙소를 읽은 38걸음에서 `wrapped_up:goal_met` 으로 접었다. 답에는 스스로 결제 화면까지 못 갔다고 썼다.
채움은 모델 말이 아니라 **실제로 서 본 화면의 제목**으로 잰다. 운영 판 5,475개에 대 봄(`bench/reach_requirement`):
선 판 7(전부 진짜 결제 화면 요청 · 엉뚱하게 선 판 0) · 실제로 간 4판은 채워짐(바뀜 없음) · 못 간 3판만 「남은 것」이 생김.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import Requirement, all_met, check, extract, reach_target, remaining_note

FOUNDER_APP_RUN = (
    "Find me an Airbnb near Shibuya Station for Nov 14-16, 2 adults, entire home, rated 4.8+ (read the rating on each listing card). "
    "Compare the top 3 by their latest reviews, pick the best, and take it to the Confirm and pay page. Don't log in or pay. "
    "Start at airbnb.com/?locale=en&currency=USD"
)


@pytest.mark.parametrize("ask, page", [
    (FOUNDER_APP_RUN, "Confirm and pay"),
    ("Open the listing, click Reserve and stop at the Confirm and pay page.", "Confirm and pay"),
    ('Pick the cheapest nonstop and take it to the "Passenger details" page.', "Passenger details"),
])
def test_a_named_destination_is_a_requirement(ask: str, page: str) -> None:
    assert reach_target(ask, english=True) == page
    reaches = [req for req in extract(ask) if req.kind == "reach"]
    assert [req.target for req in reaches] == [page]


@pytest.mark.parametrize("ask", [
    "Find a place in Tokyo and stop at that page.",                 # 어느 화면인지 이름이 없다
    "Open the detail page of each of the top 3 and compare them.",  # 읽기 요구다
    "Don't go to the Checkout page, just compare prices.",          # 하지 말라는 말
    "go to the checkout page",                                      # 이름이 아닌 일반 말 — 제목과 못 맞춘다
    "사람인에서 공고 3개를 각각 상세 페이지까지 직접 열어 읽고 회사명을 알려줘",
])
def test_other_page_words_are_not(ask: str) -> None:
    assert not [req for req in extract(ask) if req.kind == "reach"]


def test_a_quoted_screen_in_korean_is_a_requirement() -> None:
    assert reach_target("크몽에서 「프로젝트 등록」 화면까지 이동해", english=False) == "프로젝트 등록"


def _step(tool: str, title: str, ok: bool = True) -> dict:
    return {"tool": tool, "ok": ok, "evidence": {"url": "https://www.airbnb.com/x", "title": title}}


def test_it_is_met_only_on_a_screen_whose_title_says_so() -> None:
    req = Requirement("reach", "「Confirm and pay」 화면까지 가기", "Confirm and pay")
    not_yet = check([req], sources=[], steps=[_step("browser_open", "StayFab - Apartments for Rent"), _step("browser_extract", "Felicia Resort")])
    assert not all_met(not_yet) and "Felicia Resort" in not_yet[0][2]
    assert "Confirm and pay" in remaining_note(not_yet), "아직 남은 것으로 모델에게 흘려 준다"
    there = check([req], sources=[], steps=[_step("browser_open", "StayFab"), _step("browser_click", "Confirm and pay")])
    assert all_met(there) and "도착" in there[0][2]


def test_a_failed_step_on_that_screen_does_not_count() -> None:
    req = Requirement("reach", "「Confirm and pay」 화면까지 가기", "Confirm and pay")
    assert not all_met(check([req], sources=[], steps=[_step("browser_click", "Confirm and pay", ok=False)]))


def test_the_founders_run_would_not_have_wrapped_up_as_done() -> None:
    """그 판의 계획: 읽기 셋은 채웠지만 이제 「Confirm and pay 화면까지」가 남는다 — goal_met 으로 접히지 않는다."""
    plan = extract(FOUNDER_APP_RUN)
    steps = [_step("browser_open", f"Listing {n}") for n in range(4)]
    results = check(plan, sources=[f"https://www.airbnb.com/rooms/{n}" for n in range(4)], steps=steps)
    assert not all_met(results)


def test_the_step_budget_makes_room_for_getting_there() -> None:
    import inspect

    from alture_jarvis.agent import BrowserAgent as Agent

    assert 'kind == "reach"' in inspect.getsource(Agent._step_budget)
