"""검색엔진 결과 화면은 「못 읽은 사이트 → 레시피 제안」 대상이 아니다 (2026-10-01 VRAM 조사 판 e84ae679).

조사 답 끝에 「www.google.com 의 본문을 끝내 못 읽은 게 이번이 7번째입니다 … 레시피 초안 써 둘까요?」가 붙었다.
검색 화면 목록(`_SEARCH_HOSTS`)에 네이버 검색·빙만 있고 구글이 없었다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent


def _step(url: str, ok: bool) -> dict:
    return {"tool": "browser_extract", "ok": ok, "evidence": {"url": url} if ok else {}, "arguments": {"url": url}}


def test_google_search_is_not_counted_but_other_google_sites_are() -> None:
    steps = [
        _step("https://www.google.com/search?q=steam+vram", False),
        _step("https://google.com/search?q=x", False),
        _step("https://docs.google.com/document/d/abc", False),
        _step("https://search.daum.net/search?q=x", False),
    ]
    hosts = BrowserAgent._unreadable_hosts(steps)
    assert "www.google.com" not in hosts and "google.com" not in hosts and "search.daum.net" not in hosts
    assert "docs.google.com" in hosts
