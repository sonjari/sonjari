"""막히면 다른 길을 알려 준다 — 검색으로 되돌아가지 않게.

실측(2026-08-10): `browser_open_result` 가 타임아웃 나면 모델은 거의 언제나 검색으로
되돌아갔다. 검색 8번·공고 1개가 그 결과다. 검색은 늘 성공하니까 가장 싼 행동이고,
그래서 막히면 그리로 간다 — 답에서 멀어지는 방향인데도.

실패는 "이 방향이 막혔다"가 아니라 "이 **한 걸음**이 막혔다"인 경우가 대부분이다.
그 구별을 모델이 스스로 못 하니 실패마다 다음 수를 같이 준다. 프롬프트에 적어 두는
것으로는 안 된다는 것을 이미 배웠다(_search_instruction 과 같은 방식).

지키는 것 넷:

  1. 열기 실패에는 "다시 검색하지 말고 다음 순위로"
  2. 이미 읽은 글에는 "안 읽은 순위로"
  3. 같은 도구가 연달아 막히면 말이 세진다 — 두 번은 사고가 아니라 방법이 틀린 것
  4. **모르는 실패에는 아무 말도 안 한다** — 잦은 지시는 무시되고, 무시되면 없는 것과 같다
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent


def _step(tool: str, ok: bool = False) -> dict[str, Any]:
    return {"tool": tool, "ok": ok}


def test_a_dead_result_sends_it_to_the_next_rank_not_back_to_search() -> None:
    hint = BrowserAgent._recovery_hint(
        "browser_open_result", "browser_action_timeout — 시간이 끊겼을 뿐", []
    )
    assert "검색을 다시 하지 마라" in hint
    assert "rank" in hint


def test_an_already_read_page_sends_it_to_an_unread_one() -> None:
    hint = BrowserAgent._recovery_hint("browser_extract", "duplicate_action_blocked", [])
    assert "안 읽은 순위" in hint


def test_a_missing_selector_never_invites_inventing_one() -> None:
    hint = BrowserAgent._recovery_hint("browser_click", "selector_not_found: .nope", [])
    assert "지어내지 마라" in hint
    assert "browser_snapshot" in hint


def test_an_invented_domain_is_sent_to_search_for_the_real_one() -> None:
    hint = BrowserAgent._recovery_hint("browser_open", "host_does_not_exist:kmon.co.kr", [])
    assert "browser_search" in hint


def test_the_second_failure_in_a_row_raises_its_voice() -> None:
    """한 번은 사고지만 두 번은 방법이 틀린 것이다."""
    steps = [_step("browser_open_result"), _step("browser_open_result")]
    hint = BrowserAgent._recovery_hint("browser_open_result", "browser_action_timeout", steps)
    assert hint.startswith("★")
    assert "다른 도구" in hint


def test_a_success_in_between_keeps_the_voice_down() -> None:
    steps = [_step("browser_open_result", ok=True), _step("browser_open_result")]
    hint = BrowserAgent._recovery_hint("browser_open_result", "browser_action_timeout", steps)
    assert not hint.startswith("★")


def test_an_unknown_failure_says_nothing() -> None:
    """모르는 실패에까지 아무 말이나 붙이면 잦아져서 무시된다."""
    assert BrowserAgent._recovery_hint("browser_click", "뭔가 이상하다", []) == ""
    assert BrowserAgent._recovery_hint("naver_blog_save_draft", "", []) == ""
