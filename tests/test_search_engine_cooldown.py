"""막힌 검색엔진을 세션이 기억한다 — 매번 처음부터 부딪히지 않도록.

2026-08-08 실측: 빙이 봇 검사로 막혀 있으면 `browser_search` 는 **호출할 때마다**
goto + 결과 대기 + 수집을 다 치르고 나서야 네이버로 넘어갔다. 검색 1회당 ~10초다.
게다가 이미 찍힌 엔진을 계속 두드리는 것 자체가 차단을 유지시킨다.

여기서 지키는 것은 넷이고, 넷째가 제일 중요하다:

  1. 한 번 막힌 엔진은 다음 검색에서 goto 조차 안 한다
  2. 쿨다운이 지나면 다시 시도한다 (영구 제외는 틀렸다 — 차단은 풀린다)
  3. **전부 쿨다운 중이어도 검색은 된다** (건너뛰기만 하면 검색이 통째로 죽는다)
  4. 건너뛴 사실이 증거에 남는다 — 조용히 건너뛰면 이 쿨다운이 "빙은 결과가 없다"는
     새로운 침묵이 된다. 그건 고치려던 바로 그 고장이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from test_search_bot_check_late import _CHALLENGE, _SHELL, _Page, _worker


class _BingBlocked(_Page):
    """빙에서만 봇 검사가 뜬다 — 네이버는 멀쩡하다."""

    def body_text(self) -> str:
        return _CHALLENGE if "bing.com" in self.url else "검색 결과"


def _hosts(calls: list[str]) -> list[str]:
    out = []
    for url in calls:
        if "bing.com" in url:
            out.append("bing")
        elif "naver.com" in url:
            out.append("naver")
        elif "google.com" in url:
            out.append("google")
        else:
            out.append(url)
    return out


def test_a_blocked_engine_is_not_visited_again_next_search(tmp_path: Path) -> None:
    page = _BingBlocked(challenge_after=0)
    worker = _worker(tmp_path)

    worker._search(page, {"query": "크몽 견적", "engine": "bing"})
    first_round = _hosts(page.goto_calls)
    page.goto_calls.clear()
    found = worker._search(page, {"query": "크몽 후기", "engine": "bing"})

    # 2026-08-12: 빙의 폴백이 네이버 → 구글로 바뀌었다(구글이 열리게 됐다).
    assert first_round == ["bing", "google"], "첫 검색은 빙을 실제로 시도해야 한다"
    assert _hosts(page.goto_calls) == ["google"], (
        "막힌 걸 알면서 또 부딪히면 검색마다 ~10초를 버린다 — "
        f"실제 이동={_hosts(page.goto_calls)}"
    )
    assert found["result_count"] > 0


def test_the_skip_is_written_down_not_silent(tmp_path: Path) -> None:
    """건너뛴 이유가 안 남으면 이 쿨다운이 새로운 침묵이 된다."""
    page = _BingBlocked(challenge_after=0)
    worker = _worker(tmp_path)

    worker._search(page, {"query": "크몽 견적", "engine": "bing"})
    found = worker._search(page, {"query": "크몽 후기", "engine": "bing"})

    assert {"engine": "bing", "status": "skipped", "seen": "cooldown"} in found["attempts"]


def test_a_skipped_preference_still_counts_as_a_fallback(tmp_path: Path) -> None:
    """빙을 건너뛰고 네이버로 갔으면 그건 폴백이다.

    재정렬한 목록의 첫째와 견주면 "네이버가 1순위였다"가 되어 폴백 사실이 증거에서
    사라진다. 원래 1순위와 견뎌야 한다.
    """
    page = _BingBlocked(challenge_after=0)
    worker = _worker(tmp_path)

    worker._search(page, {"query": "크몽 견적", "engine": "bing"})
    found = worker._search(page, {"query": "크몽 후기", "engine": "bing"})

    assert found["engine"] == "google"
    assert found["fallback_used"] is True


def test_search_still_works_when_every_engine_is_cooling_down(tmp_path: Path) -> None:
    """전부 막혀 있어도 시도는 한다 — 건너뛰기만 하면 검색이 통째로 죽는다."""
    import time as _time

    worker = _worker(tmp_path)
    worker._blocked_engines = {
        "bing": _time.monotonic(),
        "naver": _time.monotonic(),
        "google": _time.monotonic(),
    }
    page = _Page(challenge_after=99)  # 아무도 안 막는 화면

    found = worker._search(page, {"query": "크몽 견적", "engine": "bing"})

    assert _hosts(page.goto_calls)[:1] == ["bing"], (
        "전부 쿨다운이면 건너뛰지 말고 원래 순서대로 시도해야 한다 — "
        f"실제 이동={_hosts(page.goto_calls)}"
    )
    assert not [a for a in found["attempts"] if a["status"] == "skipped"], (
        "건너뛸 여유가 없을 때는 아무도 건너뛰지 않아야 한다"
    )


def test_cooldown_expires_and_the_engine_is_tried_again(tmp_path: Path) -> None:
    """차단은 풀린다 — 영구 제외는 틀렸다."""
    page = _BingBlocked(challenge_after=0)
    worker = _worker(tmp_path, browser_search_block_cooldown_sec=0)

    worker._search(page, {"query": "크몽 견적", "engine": "bing"})
    page.goto_calls.clear()
    worker._search(page, {"query": "크몽 후기", "engine": "bing"})

    assert _hosts(page.goto_calls) == ["bing", "google"], "쿨다운이 끝났으면 다시 시도해야 한다"


def test_an_engine_that_works_loses_its_mark(tmp_path: Path) -> None:
    """통하면 낙인을 지운다 — 그래야 차단이 풀린 순간 바로 원래 엔진으로 돌아간다.

    쿨다운 0 으로 둔 것은 일부러다. 그래야 네이버가 건너뛰이지 않고 실제로 시도되고,
    "시도해서 통했으니 낙인이 지워지는가"를 잰다.
    """
    import time as _time

    worker = _worker(tmp_path, browser_search_block_cooldown_sec=0)
    worker._blocked_engines = {"naver": _time.monotonic()}
    page = _Page(challenge_after=99)

    found = worker._search(page, {"query": "크몽 견적", "engine": "naver"})

    assert found["engine"] == "naver" and found["result_count"] > 0
    assert "naver" not in worker._blocked_engines


def test_routing_preference_is_untouched_by_the_cooldown_layer() -> None:
    """라우팅은 순수하게 남는다 — 쿨다운은 그 위에 얹은 별개 층이다."""
    assert BrowserWorker._search_engines("여수 지역 AI 지원사업", "auto") == ["naver", "google"]
    assert BrowserWorker._search_engines("Playwright 공식 문서", "auto") == ["google", "naver"]
