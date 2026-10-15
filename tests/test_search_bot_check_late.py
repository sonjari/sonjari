"""봇 검사 화면은 문서보다 **늦게** 온다 — 한 번만 보면 못 본다.

2026-08-07 제보: 한 세션에서 검색을 여러 번 하고 나면 `browser_search engine=bing`
이 `result_count=0` 을 돌려준다. 새 세션에서는 같은 질의가 8건이다. 실사이트에서
같은 페이지를 300ms 간격으로 재 봤더니 원인이 그대로 나왔다:

    t=0.6초   탭·검색창만 있는 껍데기        차단 아님   결과 0건
    t=4.7초   "마지막 한 단계 · 계속하려면 아래 과제 해결"   차단      결과 0건

`_search` 는 `goto` 직후 **한 번만** 차단을 봤다. 그 시점(0.6초)에는 아직 검사
화면이 안 왔으므로 `status: ok` 로 지나가고, 그 뒤 6초를 기다렸다가 0건을
**성공으로** 돌려줬다. 그래서:

  · 봇 검사가 "이 질의는 결과가 없다"로 둔갑한다 — 모델은 낱말을 바꾸러 간다
  · 멀쩡한 네이버 폴백이 있는데도 쓰이지 않는다 (차단으로 안 세니 넘어갈 이유가 없다)

문구는 `_SEARCH_BLOCK_MARKERS` 에 이미 다 있었다. 못 알아본 게 아니라 **너무 일찍
봤을 뿐**이다. 시점을 여기서 잠근다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

# 실측에서 실제로 걸린 문구 그대로.
_CHALLENGE = "콘텐츠로 건너뛰기 접근성 피드백 Rewards 마지막 한 단계 계속하려면 아래 과제 해결"
_SHELL = "콘텐츠로 건너뛰기 접근성 피드백 전체이미지동영상지도뉴스 더 보기 개인 정보 보호"


class _Element:
    def __init__(self, name: str, href: str) -> None:
        self.name = name
        self.href = href

    def is_visible(self) -> bool:
        return True

    def is_disabled(self) -> bool:
        return False

    def evaluate(self, script: str, *args: Any) -> Any:
        return "a" if "tagName" in script else None

    def get_attribute(self, name: str) -> str | None:
        return self.href if name == "href" else None

    def inner_text(self, timeout: int = 0) -> str:
        del timeout
        return self.name


class _Body:
    def __init__(self, page: "_Page") -> None:
        self._page = page

    def inner_text(self, timeout: int = 0) -> str:
        del timeout
        return self._page.body_text()


class _Elements:
    def __init__(self, items: list[_Element]) -> None:
        self.items = items

    def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> _Element:
        return self.items[index]


class _Frame:
    name = ""

    def __init__(self, page: "_Page") -> None:
        self._page = page
        self.url = page.url

    def locator(self, selector: str) -> Any:
        return _Elements(self._page.elements())

    def evaluate(self, script: str, *args: Any) -> Any:
        del args
        # ★ 이 가짜는 **두 가지 질문**을 받는다. 예전에는 무엇을 묻든 `[]` 를
        # 돌려줬는데, 화면 읽기가 브라우저 안에서 한 번에 도는 방식으로 바뀌면서
        # (2026-08-10) 그 `[]` 가 "이 화면에 요소가 하나도 없다"로 읽혀 검색 결과가
        # 통째로 0건이 됐다. 무엇을 묻는지에 따라 답한다.
        if "data-jarvis-ref" in script:
            # 요소 훑기는 이 가짜가 흉내 낼 수 없다(진짜 DOM 이 없다). 못 한다고
            # 답하면 느린 길로 돌아가고, 그쪽이 `locator` 로 이 가짜를 읽는다.
            raise RuntimeError("no_dom_in_fake")
        return []  # 머리말·꼬리말 링크 없음


class _Page:
    """검색 결과 대신 **뒤늦게** 봇 검사를 그리는 화면.

    `body_calls` 로 시점을 흉내 낸다: 처음 볼 때는 껍데기, 그 다음부터는 검사 화면.
    실제 페이지가 4초에 걸쳐 하는 일을 폴 횟수로 압축한 것이다.
    """

    def __init__(self, *, challenge_after: int, results_on_naver: int = 8) -> None:
        self.url = "about:blank"
        self.frames = [_Frame(self)]
        self.goto_calls: list[str] = []
        self._body_seen = 0
        self._challenge_after = challenge_after
        self._results_on_naver = results_on_naver

    def _on_bing(self) -> bool:
        return "bing.com" in self.url

    def body_text(self) -> str:
        if not self._on_bing():
            return "검색 결과"
        self._body_seen += 1
        return _SHELL if self._body_seen <= self._challenge_after else _CHALLENGE

    def elements(self) -> list[_Element]:
        if self._on_bing():
            return [_Element("검색", "https://www.bing.com/search?q=x")]  # 결과 없음
        return [
            _Element(f"블로그 글 {i}", f"https://blog.naver.com/writer{i}/22400000{i}")
            for i in range(self._results_on_naver)
        ]

    def goto(self, url: str, wait_until: str = "") -> None:
        del wait_until
        self.goto_calls.append(url)
        self.url = url
        self.frames = [_Frame(self)]

    def locator(self, selector: str) -> Any:
        return _Body(self) if selector == "body" else _Elements(self.elements())

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "검색"


def _worker(tmp_path: Path, **overrides: Any) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            # 폴이 두어 번 돌 만큼만. 테스트가 6초를 기다릴 이유는 없다.
            browser_ready_timeout_ms=1200,
            **overrides,
        )
    )


def test_a_late_bot_check_is_not_reported_as_zero_results(tmp_path: Path) -> None:
    """첫 검사를 통과한 뒤에 뜬 검사 화면도 차단으로 센다."""
    page = _Page(challenge_after=1)

    found = _worker(tmp_path)._search(page, {"query": "크몽 견적 사례", "engine": "bing"})

    statuses = {item["engine"]: item["status"] for item in found["attempts"]}
    assert statuses["bing"] == "blocked", (
        "봇 검사 화면을 '결과 0건'으로 돌려주면 모델은 낱말을 바꾸러 간다 — "
        f"attempts={found['attempts']}"
    )
    # 늦게 잡혔다는 사실 자체가 증거에 남아야 다음에 같은 걸 또 진단하지 않는다.
    assert any(item.get("seen") == "while_waiting" for item in found["attempts"])


def test_a_blocked_engine_falls_back_and_actually_returns_results(tmp_path: Path) -> None:
    """차단은 폴백으로 가는 문이다 — 0건으로 세면 그 문이 안 열린다.

    이게 사용자가 실제로 잃고 있던 것이다: 빙이 막혔을 뿐 다음 엔진은 멀쩡했는데,
    빙의 0건이 '성공'이라 거기까지 가 보지도 않고 빈손으로 끝났다.

    2026-08-12: 빙의 다음 엔진이 네이버 → 구글로 바뀌었다(구글이 열리게 됐다).
    이 시험이 지키는 것은 "차단이 폴백의 문을 연다"이지 특정 엔진 이름이 아니다.
    """
    page = _Page(challenge_after=1)

    found = _worker(tmp_path)._search(page, {"query": "크몽 견적 사례", "engine": "bing"})

    assert found["engine"] == "google"
    assert found["fallback_used"] is True
    assert found["result_count"] > 0
    assert "bing.com" in page.goto_calls[0] and "google.com" in page.goto_calls[1]


def test_an_immediate_bot_check_is_still_caught(tmp_path: Path) -> None:
    # 원래 있던 검사를 늦은 검사로 대체한 게 아니다 — 둘 다 있어야 한다.
    page = _Page(challenge_after=0)

    found = _worker(tmp_path)._search(page, {"query": "크몽 견적 사례", "engine": "bing"})

    assert found["attempts"][0] == {
        "engine": "bing", "status": "blocked", "seen": "immediately",
    }


def test_a_page_with_results_is_never_called_blocked(tmp_path: Path) -> None:
    """결과가 잡히면 차단을 묻지 않는다.

    'captcha' 같은 낱말이 실린 멀쩡한 결과 페이지를 차단으로 오인하면, 이번 고장을
    거울로 뒤집은 것과 같다 — 이번엔 있는 결과가 사라진다.
    """
    page = _Page(challenge_after=0)
    page.goto("https://search.naver.com/search.naver?query=captcha")

    settled = _worker(tmp_path)._wait_for_results(page, limit=8)

    assert settled["blocked"] is False
    assert len(settled["results"]) == 8


def test_all_engines_blocked_raises_instead_of_answering_emptily(tmp_path: Path) -> None:
    """폴백까지 다 막히면 조용한 0건이 아니라 **에러**여야 한다.

    사람이 화면의 확인을 직접 통과할 수 있다는 것을 알려주는 유일한 경로다.
    """

    class _AllBlocked(_Page):
        def body_text(self) -> str:
            return _CHALLENGE

    found: Exception | None = None
    try:
        _worker(tmp_path)._search(_AllBlocked(challenge_after=0), {"query": "x", "engine": "bing"})
    except RuntimeError as exc:
        found = exc
    assert found is not None and "search_engines_blocked" in str(found)
