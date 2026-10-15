"""노트북 실사용(2026-09-26 밤)에서 나온 운영 버그 — 길찾기 판 두 개를 뜯어 본 것."""

from __future__ import annotations

from alture_jarvis.attention import AttentionService
from alture_jarvis.plan import Requirement, check


class _Events:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def publish(self, kind: str, payload: dict) -> None:
        self.sent.append((kind, payload))


def _unverified_click() -> dict:
    return {"ok": True, "result": {"action": "clicked", "verified": False, "url": "https://map.naver.com/p"}}


def test_a_read_only_click_that_could_not_be_verified_does_not_page_the_human() -> None:
    """검색 단추를 누르고 「다시 누르면 두 번 처리될 수 있어 멈췄습니다」 — 읽기 전용에서는 두 번 처리될 것이 없다."""
    events = _Events()
    service = AttentionService(events, browser_read_only=lambda: True)
    assert service.check(job_id="j", tool="browser_click", arguments={}, observation=_unverified_click()) is None
    assert not events.sent


def test_when_writes_are_possible_the_warning_still_goes_up() -> None:
    """★ 반대 표본: 읽기 전용을 끄면(저장·게시가 될 수 있으면) 지금처럼 사람을 부른다."""
    events = _Events()
    service = AttentionService(events, browser_read_only=lambda: False)
    notice = service.check(job_id="j", tool="browser_click", arguments={}, observation=_unverified_click())
    assert notice is not None and notice["code"] == "change_not_verified"


def test_a_half_filled_form_still_pages_even_in_read_only() -> None:
    events = _Events()
    service = AttentionService(events, browser_read_only=lambda: True)
    observation = {"ok": True, "result": {"action": "filled", "verified": False}}
    assert service.check(job_id="j", tool="browser_fill", arguments={}, observation=observation) is not None


def _step(tool: str, url: str, ok: bool = True) -> dict:
    return {"tool": tool, "ok": ok, "evidence": {"url": url}}


def test_working_on_the_named_site_counts_even_without_a_body_read() -> None:
    """네이버 지도에서 검색·길찾기까지 13걸음 — 「네이버에서 하기 — 거기서 아무것도 안 함」이 찍혔다."""
    req = Requirement("site", "네이버에서 하기", ("naver.com",))
    steps = [_step("browser_open", "https://map.naver.com/p/"), _step("browser_click", "https://map.naver.com/p/directions/x")]
    (_, ok, saw), = check([req], sources=[], steps=steps)
    assert ok and "map.naver.com" in saw


def test_a_failed_step_or_another_site_does_not_count() -> None:
    """★ 반대 표본: 실패한 걸음이나 다른 사이트에서 한 것은 「거기서 일했다」가 아니다."""
    req = Requirement("site", "네이버에서 하기", ("naver.com",))
    steps = [_step("browser_open", "https://map.naver.com/p/", ok=False), _step("browser_open", "https://www.google.com/search?q=x"),
             _step("browser_open", "https://evilnaver.com/")]
    (_, ok, _saw), = check([req], sources=[], steps=steps)
    assert not ok
