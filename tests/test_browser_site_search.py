"""사이트 안에서 그 사이트의 검색으로 찾는다 — 검색엔진에 사이트 이름을 끼워 넣지 않고.

2026-08-12 실측. "여수·순천·광양 채용 공고"를 시켰더니 16스텝 중 **7번이 네이버
검색**이었고, 질의는 이렇게 흘렀다:

    "여수 순천 광양 회계 재무 채용 공고"
    "여수 순천 광양 회계 채용 공고 사람인 잡코리아"      ← 잡코리아를 낱말로
    "여수 순천 광양 회계 재무 채용 공고 사람인 잡코리아 2026"
    "여수 회계 채용 공고 사람인 잡코리아"

잡코리아로 **들어가서** 그 사이트 검색을 쓰는 것이 사람이 하는 일인데, 그 걸음을
밟을 도구가 없었다. 그래서 제일 싼 행동(또 검색)을 되풀이했다. `google_drive_read`
가 없어서 이력서를 못 읽던 것과 **같은 모양**이다 — 연장이 없으면 그 일을 못 한다.

여기서 지키는 것 넷:

  1. 검색칸은 사이트 목록이 아니라 **구조**로 찾는다 (type=search·role·이름·form[role=search])
  2. 검색엔진 결과 화면에서는 거절한다 — 먼저 사이트에 들어가라는 뜻이다
  3. 못 찾으면 조용히 넘어가지 않고, 무엇을 대신 쓰라고 말한다
  4. 이건 **읽기**다. L0 이고 읽기 전용 모드에서도 막히지 않는다
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.agent import _LISTING_TOOLS
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Locator:
    def __init__(self, page: "_Page") -> None:
        self._page = page

    @property
    def first(self) -> "_Locator":
        return self

    def click(self, timeout: int = 0) -> None:
        del timeout
        if self._page.click_blocked:
            raise RuntimeError("Locator.click: Timeout 2500ms exceeded — overlay intercepts")
        self._page.acted.append("click")

    def fill(self, value: str) -> None:
        self._page.acted.append(f"fill:{value}")

    def press(self, key: str) -> None:
        self._page.acted.append(f"press:{key}")
        self._page.url = self._page.after_url


class _Page:
    def __init__(
        self,
        url: str,
        box: dict[str, Any] | None,
        after_url: str = "",
        click_blocked: bool = False,
    ) -> None:
        self.url = url
        self.after_url = after_url or url + "?searched=1"
        self._box = box
        self.acted: list[str] = []
        # 공지 팝업이 포인터를 가로채는 상태(잡코리아에서 실제로 그랬다).
        self.click_blocked = click_blocked

    def evaluate(self, script: str, *args: Any) -> Any:
        if "data-jarvis-sitesearch" in script and "removeAttribute" in script:
            return None
        return self._box

    def locator(self, selector: str) -> _Locator:
        del selector
        return _Locator(self)

    def wait_for_timeout(self, ms: int) -> None:
        del ms

    def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        del state, timeout

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "검색 결과"


def _worker(tmp_path: Path) -> BrowserWorker:
    worker = BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_visual_overlay=False,
            browser_evidence_dir=tmp_path / "evidence",
        )
    )
    worker._wait_until_operable = lambda page: {"count": 42, "ms": 1, "polls": 1}  # type: ignore[method-assign]
    return worker


def test_it_types_into_the_sites_own_box_and_submits(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page("https://www.jobkorea.co.kr/", {"score": 11, "name": "검색어 입력", "tag": "input"})

    result = worker._site_search(page, {"query": "여수 회계"})

    assert page.acted == ["click", "fill:여수 회계", "press:Enter"]
    assert result["action"] == "site_searched"
    assert result["site"] == "jobkorea.co.kr"
    assert result["url_changed"] is True


def test_it_refuses_on_a_search_engine_page(tmp_path: Path) -> None:
    """검색엔진 결과 화면에서 부르면 그건 사이트에 안 들어갔다는 뜻이다."""
    worker = _worker(tmp_path)
    page = _Page("https://search.naver.com/search.naver?query=x", {"score": 9, "name": "검색"})

    with pytest.raises(RuntimeError) as error:
        worker._site_search(page, {"query": "여수 회계"})

    assert "not_on_a_site" in str(error.value)
    assert page.acted == [], "검색엔진 검색창에 글자를 넣었다"


def test_no_search_box_says_what_to_do_instead(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    worker._open_search_box = lambda page: False  # type: ignore[method-assign]
    page = _Page("https://example.com/", None)

    with pytest.raises(RuntimeError) as error:
        worker._site_search(page, {"query": "여수 회계"})

    assert "site_search_box_not_found" in str(error.value)
    assert "browser_fill" in str(error.value), "대신 무엇을 쓰라는 말이 없다"


def test_a_folded_search_box_is_opened_first(tmp_path: Path) -> None:
    """2026-08-12 실측(사람인). 검색칸이 DOM 에 있는데 width=0 · 안 보임이었다.

    돋보기를 눌러야 펼쳐지는 형태였는데 "이 사이트엔 검색이 없다"로 읽고 멈췄다.
    없는 게 아니라 **접혀 있었다.**
    """
    worker = _worker(tmp_path)
    page = _Page("https://www.saramin.co.kr/", None)
    opened: list[str] = []

    def _open(target: Any) -> bool:
        del target
        opened.append("clicked")
        # 편 뒤에는 검색칸이 보인다.
        page._box = {"score": 8, "name": "직무, 회사, 지역, 키워드로 검색해보세요"}
        return True

    worker._open_search_box = _open  # type: ignore[method-assign]

    result = worker._site_search(page, {"query": "여수 회계"})

    assert opened == ["clicked"], "접힌 칸을 펴 보지도 않고 포기했다"
    assert result["action"] == "site_searched"
    assert page.acted[-2:] == ["fill:여수 회계", "press:Enter"]


def test_an_empty_query_is_rejected(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page("https://www.jobkorea.co.kr/", {"score": 11, "name": "검색"})

    with pytest.raises(ValueError):
        worker._site_search(page, {"query": "  "})


def test_the_result_tells_the_model_not_to_go_back_to_naver(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page("https://www.saramin.co.kr/", {"score": 12, "name": "검색"})

    result = worker._site_search(page, {"query": "여수 회계"})

    assert "네이버로 돌아가 다시 검색하지 마라" in result["instruction"]


def test_a_blocking_popup_does_not_stop_the_search(tmp_path: Path) -> None:
    """2026-08-12 실측. 잡코리아 검색칸("JOB 검색")을 정확히 찾아 놓고도 공지 팝업이
    포인터를 가로채 20초를 버티다 통째로 실패했다.

    `fill` 은 포인터를 쓰지 않는다 — 누르기가 막혀도 값은 들어간다.
    """
    worker = _worker(tmp_path)
    page = _Page(
        "https://www.jobkorea.co.kr/",
        {"score": 12, "name": "JOB 검색", "tag": "input"},
        click_blocked=True,
    )

    result = worker._site_search(page, {"query": "여수 회계"})

    assert page.acted == ["fill:여수 회계", "press:Enter"], "팝업에 막혀 통째로 포기했다"
    assert result["action"] == "site_searched"


def test_site_search_is_a_listing_tool() -> None:
    """여기서 나온 목록을 **열어야** 출처가 된다. 목록 자체는 근거가 아니다."""
    assert "browser_site_search" in _LISTING_TOOLS


def test_standing_on_a_site_is_told_the_search_box_exists(tmp_path: Path) -> None:
    """★ 도구를 만들어 두는 것으로는 안 된다 — 붙인 첫 판에서 한 번도 안 불렀다.

    쓸 수 있다는 사실은 **쓸 수 있는 그 순간에** 줘야 한다.
    """
    worker = _worker(tmp_path)
    page = _Page("https://www.jobkorea.co.kr/recruit/12345", {"score": 11, "name": "검색어"})

    offer = worker._site_search_offer(page)

    assert offer.strip().startswith("★"), "따로 올라가지 않으면 긴 결과 안에 묻힌다"
    assert "browser_site_search" in offer
    assert "jobkorea.co.kr" in offer


def test_a_blog_is_not_offered_site_search(tmp_path: Path) -> None:
    """블로그에도 검색칸은 있지만 거기서 찾는 건 그 사람 글이다. 잦은 안내는 안 읽힌다."""
    worker = _worker(tmp_path)
    page = _Page("https://blog.naver.com/someone/123", {"score": 11, "name": "블로그 검색"})

    assert worker._site_search_offer(page) == ""


def test_a_page_without_a_search_box_is_not_offered(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page("https://example.com/article", None)

    assert worker._site_search_offer(page) == ""
