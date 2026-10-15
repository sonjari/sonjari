"""연 바로 다음에 그 사이트를 읽었으면 읽은 것이다 (2026-10-08 전수조사 3-2).

「본문을 읽지 않은 출처를 근거로 적었습니다」 검사가 「읽었다」를 **주소 글자가 같은가**로만 가르고 있었다.
운영 판 2,501개: 이 검사가 「안 읽음」으로 친 열기 걸음 307개 가운데 59개는 열자마자 같은 호스트·같은 경로를 읽은 것이었다 —
읽은 걸음의 주소에 꼬리표(추적 인자·넘겨 보낸 뒤의 주소)가 붙어 글자가 안 맞았을 뿐이다.
장부에 이 충돌이 남아 「일부」가 된 12판 중 7판이 그런 판이었다.

걸음 순서라는 사실로 가른다. 다른 가게로 넘어가 읽힌 것(가격 비교 사이트 → 다른 쇼핑몰)은 예전처럼 잡는다.
"""
from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent

_ANSWER = "1. 무선마우스 A — 가격 19,900원 (shopmall 상세에서 확인)\n2. 무선마우스 B — 가격 24,000원\n"


def _step(tool: str, url: str, ok: bool = True) -> dict[str, Any]:
    return {"tool": tool, "ok": ok, "evidence": {"url": url}}


def _conflict(steps: list[dict[str, Any]]) -> str:
    return BrowserAgent._unread_source_attribution_conflict(_ANSWER, steps)


def test_opening_without_reading_is_still_caught() -> None:
    steps = [_step("browser_open_result", "https://shopmall.example/item/1"),
             _step("browser_open_result", "https://other.example/item/2"),
             _step("browser_extract", "https://other.example/item/2")]
    assert "shopmall" in _conflict(steps)


def test_a_read_right_after_opening_counts_even_when_the_address_grew_a_tail() -> None:
    steps = [_step("browser_open_result", "https://shopmall.example/item/1"),
             _step("browser_extract", "https://shopmall.example/item/1?ref=search&utm_source=x")]
    assert _conflict(steps) == ""


def test_a_read_after_a_redirect_inside_the_same_site_counts() -> None:
    steps = [_step("browser_open_result", "https://shopmall.example/go/1"),
             _step("browser_extract", "https://shopmall.example/item/1")]
    assert _conflict(steps) == ""


def test_looking_at_the_opened_page_counts_too() -> None:
    steps = [_step("browser_open_result", "https://shopmall.example/item/1"),
             _step("browser_snapshot", "https://shopmall.example/item/1")]
    assert _conflict(steps) == ""


def test_a_failed_step_in_between_does_not_break_the_pair() -> None:
    steps = [_step("browser_open_result", "https://shopmall.example/item/1"),
             _step("browser_extract", "", ok=False),
             _step("browser_extract", "https://shopmall.example/item/1?x=1")]
    assert _conflict(steps) == ""


def test_being_sent_on_to_another_store_is_still_not_reading_this_one() -> None:
    """가격 비교 사이트의 다리 주소를 열었는데 읽힌 곳은 다른 쇼핑몰이었다 — 2026-08-13 의 그 고장은 그대로 잡는다."""
    steps = [_step("browser_open_result", "https://shopmall.example/bridge/1"),
             _step("browser_extract", "https://elsewhere.example/products/9")]
    assert "shopmall" in _conflict(steps)


def test_a_fragment_is_not_a_different_page() -> None:
    steps = [_step("browser_open_result", "https://shopmall.example/item/1#reviews"),
             _step("browser_open_result", "https://other.example/x"),
             _step("browser_extract", "https://other.example/x"),
             _step("browser_extract", "https://shopmall.example/item/1")]
    assert _conflict(steps) == ""
