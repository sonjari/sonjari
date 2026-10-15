"""사이트 안 목록에도 **순위**를 매기고, 무한스크롤로 뒤에 숨은 것까지 불러온다.

2026-08-12 실측. 잡코리아 목록을 스냅샷으로 85개 잡아 놓고도 상세를 못 열었다:

    9.  browser_snapshot            → 요소 85개 (공고 목록 다 보임)
    10. browser_open_result rank=32 → result_rank_not_found:32 — 있는 순위: 1~9
    11. browser_open_result rank=1  → 인디드로 튕겨 나감

그 "1~9" 는 **네이버 검색 결과**였다. 사이트 안 목록에는 부를 이름이 아예 없었다.
그래서 상세를 못 열고 목록에 적힌 분류를 그대로 옮겼다 — 실제 직무는 "KB라이프
청약매니저"인데 답에는 "전산설계사무"로 나갔다.

여기서 지키는 것 넷:

  1. 사이트 검색 결과에도 순위를 매겨 `_last_results` 에 넣는다
  2. 지시는 "상세 원문에서 읽어라"까지 말한다 — 목록의 분류는 원문이 아니다
  3. 무한스크롤은 **더 안 늘면 멈춘다**. 끝까지 내려가면 안 끝나는 사이트가 있다
  4. 스크롤로 안 늘면 '더보기' 버튼을 한 번 눌러 본다
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Page:
    """스크롤할 때마다 링크가 늘어나는(또는 안 늘어나는) 페이지."""

    def __init__(self, counts: list[int], more_text: str | None = None) -> None:
        self._counts = counts
        self._index = 0
        self.url = "https://www.jobkorea.co.kr/Search/"
        self.scrolls = 0
        self.more_clicked = 0
        self._more_text = more_text

    def evaluate(self, script: str, *args: Any) -> Any:
        if "scrollHeight" in script:
            self.scrolls += 1
            self._index = min(self._index + 1, len(self._counts) - 1)
            return None
        # 링크 세기는 섀도 DOM 안까지 센다(2026-09-17 `_deep_js`) — 질의가 `__deepAll(...)` 로 바뀌었다.
        if any(probe in script for probe in ("querySelectorAll('a[href]')", 'querySelectorAll("a[href]")', "__deepAll('a[href]')")):
            return self._counts[self._index]
        if "data-jarvis-more" in script and "removeAttribute" in script:
            return None
        if "role=button" in script or "role=button]" in script:
            return self._more_text
        return None

    def locator(self, selector: str) -> Any:
        page = self

        class _L:
            @property
            def first(self) -> "_L":
                return self

            def click(self, timeout: int = 0) -> None:
                del timeout
                page.more_clicked += 1
                page._index = min(page._index + 1, len(page._counts) - 1)

        return _L()

    def wait_for_timeout(self, ms: int) -> None:
        del ms

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "잡코리아 검색"


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_visual_overlay=False,
            browser_evidence_dir=tmp_path / "evidence",
        )
    )


def test_scrolling_stops_when_nothing_new_arrives(tmp_path: Path) -> None:
    """끝까지 내려가면 목록이 수천 개인 사이트에서 영영 안 끝난다."""
    worker = _worker(tmp_path)
    page = _Page([40, 80, 120, 120, 120])

    loaded = worker._load_more(page, rounds=8)

    assert loaded["grew"] is True
    assert loaded["link_counts"][-1] == 120
    assert page.scrolls <= 4, "더 안 늘어나는데 계속 내렸다"


def test_a_more_button_is_pressed_when_scrolling_does_nothing(tmp_path: Path) -> None:
    """스크롤이 안 먹는 사이트는 '더보기'로 늘린다 — 늘어나는 동안만."""
    worker = _worker(tmp_path)
    page = _Page([30, 30, 90], more_text="더보기")

    loaded = worker._load_more(page, rounds=5)

    assert page.more_clicked >= 1, "스크롤이 안 먹는데 더보기를 안 눌렀다"
    assert loaded["grew"] is True
    assert page.more_clicked < 5, "더 안 늘어나는데 계속 눌렀다"


def test_zero_rounds_does_not_touch_the_page(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page([30])

    assert worker._load_more(page, rounds=0) is None
    assert page.scrolls == 0


def test_a_handmade_search_url_is_named_and_redirected(tmp_path: Path) -> None:
    """막지는 않는다 — 다음에 무엇을 쓰면 되는지를 그 자리에서 준다."""
    worker = _worker(tmp_path)

    note = worker._handmade_search_note("https://www.jobkorea.co.kr/Search/?stext=%EA%B4%91")

    assert note.strip().startswith("★")
    assert "browser_site_search" in note
    assert "jobkorea.co.kr" in note


def test_a_real_search_engine_is_not_scolded(tmp_path: Path) -> None:
    """네이버·구글 검색 주소는 browser_search 가 만드는 정상 경로다."""
    worker = _worker(tmp_path)

    assert worker._handmade_search_note("https://search.naver.com/search.naver?query=x") == ""
    assert worker._handmade_search_note("https://www.google.com/search?q=x") == ""


def test_an_ordinary_page_is_not_scolded(tmp_path: Path) -> None:
    worker = _worker(tmp_path)

    assert worker._handmade_search_note("https://www.jobkorea.co.kr/Recruit/GI_Read/49554994") == ""
