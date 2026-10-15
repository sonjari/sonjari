"""반쯤 그려진 검색 결과를 "성공"으로 내보내지 않는다.

2026-08-08 실측: `limit=10` 으로 요청했는데 빙이 **1건**만 돌려주고 `polls=1`,
`status: ok`. 같은 질의가 다른 시점에는 8건이었다.

원인은 `_wait_for_results` 가 **결과가 하나라도 잡히면 즉시 돌아간** 것이다. 반쯤
그려진 화면의 첫 결과 하나를 잡고 끝낸다. "덜 그려졌다"를 "결과가 적다"로 내보내는
것이고, 봇 검사를 "결과 0건"으로 읽던 것과 같은 계열이다 — **부분을 성공으로 보고한다.**

고치는 방향에 함정이 있다. `limit` 이 찰 때까지 기다리게 하면 결과가 정말 3건뿐인
질의에서 **매번 타임아웃을 다 쓴다.** 그래서 **자라기를 멈출 때까지**만 본다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Page:
    """폴을 거듭할수록 결과가 더 그려지는 화면."""

    def __init__(self, counts: list[int]) -> None:
        self.counts = counts
        self.asked = 0
        self.url = "https://search.naver.com/search.naver?query=x"

    def take(self) -> int:
        value = self.counts[min(self.asked, len(self.counts) - 1)]
        self.asked += 1
        return value


def _worker(tmp_path: Path, page: _Page, **overrides: Any) -> BrowserWorker:
    worker = BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_ready_timeout_ms=overrides.pop("timeout_ms", 4000),
        )
    )
    # 진짜 DOM 대신 "이번 폴에 몇 건 보이나"만 흉내 낸다 — 여기서 재는 것은 파싱이
    # 아니라 **언제 그만 보는가** 이다.
    worker._collect_results = lambda p, limit=12: [  # type: ignore[assignment]
        {"rank": i + 1, "title": f"결과 {i + 1}", "url": f"https://example.test/{i}"}
        for i in range(min(page.take(), limit))
    ]
    worker._search_blocked = staticmethod(lambda p: False)  # type: ignore[assignment]
    return worker


def test_a_half_drawn_page_is_not_reported_as_the_whole_answer(tmp_path: Path) -> None:
    """1건 -> 5건 -> 8건 으로 그려지는 화면에서 1건을 답으로 내보내면 안 된다."""
    page = _Page([1, 5, 8, 8])

    settled = _worker(tmp_path, page)._wait_for_results(page, limit=10)

    assert len(settled["results"]) == 8, (
        f"자라는 중에 끊으면 반쪽을 답으로 내보낸다 — {len(settled['results'])}건에서 멈췄다"
    )
    assert settled["polls"] >= 3


def test_it_stops_as_soon_as_the_list_stops_growing(tmp_path: Path) -> None:
    """정말 3건뿐인 질의에서 타임아웃을 다 쓰면 안 된다."""
    page = _Page([3, 3, 3, 3, 3])

    settled = _worker(tmp_path, page)._wait_for_results(page, limit=10)

    assert len(settled["results"]) == 3
    assert settled["polls"] == 2, (
        "안 자라는 것을 확인하는 데 한 번이면 충분하다 — 더 보면 그냥 낭비다"
    )


def test_a_full_page_returns_on_the_first_poll(tmp_path: Path) -> None:
    """달라는 만큼 찼으면 더 볼 것이 없다 — 흔한 길이고 여기서 끝나야 싸다."""
    page = _Page([10, 10])

    settled = _worker(tmp_path, page)._wait_for_results(page, limit=10)

    assert len(settled["results"]) == 10
    assert settled["polls"] == 1, "가장 흔한 경우에 폴을 더 쓰면 모든 검색이 그만큼 느려진다"


def test_an_empty_page_still_gives_up_at_the_deadline(tmp_path: Path) -> None:
    # 아무것도 안 그려지는 화면에서 영원히 기다리면 안 된다.
    page = _Page([0])

    settled = _worker(tmp_path, page, timeout_ms=700)._wait_for_results(page, limit=10)

    assert settled["results"] == []
    assert settled["blocked"] is False


def test_growth_that_never_settles_is_capped_by_the_deadline(tmp_path: Path) -> None:
    """계속 자라기만 하는 화면에서도 시간 안에는 돌아온다."""
    page = _Page(list(range(1, 200)))

    settled = _worker(tmp_path, page, timeout_ms=900)._wait_for_results(page, limit=150)

    assert settled["results"], "자라는 중이라고 빈손으로 돌아가면 안 된다"
