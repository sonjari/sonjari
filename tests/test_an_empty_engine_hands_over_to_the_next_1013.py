"""검색 엔진이 **0건으로 돌아와도** 다음 엔진으로 넘어간다 — 막혔을 때만이 아니라 (2026-10-13).

가격 조사 판을 걸음 순서로 읽다 찾았다. 재는 판의 네이버 통합검색 129번 중 68번이 `result_count 0` 이었고, 검색어에 달려 있었다:

    상품 이름 하나(마우스)        33번 중 28번이 0건      화면은 다 그려져 있었다(요소 500개 안팎 · 제목에 검색어)
    상품 이름 하나(게임기 본체)    26번 중 19번이 0건
    같은 검색어 · 블로그 탭        매번 10건

상품 이름으로 찾으면 통합검색 첫 화면이 광고와 쇼핑 묶음으로 찬다 — 광고는 결과가 아니라서 걸러지고, 남는 것이 없다.
도구는 「결과가 없다. 낱말을 바꾸거나 engine 을 지정해라」고 돌려줬고, 0건 바로 뒤 걸음 77번 중 41번이 **다시 검색**이었다
(게임기 과제에서 검색 엔진만 돌다 가게에 못 간 판들이 이 모양이다). 흔한 상품 이름에 「결과가 없다」는 사실이 아니다.

엔진 차례(네이버 → 구글)는 이미 있다. 넘어가는 문이 **막혔을 때**에만 열렸을 뿐이다 — 08-07 에 「봇 검사 화면이 0건으로 둔갑해
폴백이 안 열린다」를 고친 것과 같은 자리의 나머지 반쪽이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from test_search_bot_check_late import _CHALLENGE, _Element, _Page, _worker


class _NaverShowsOnlyAds(_Page):
    """네이버 통합검색은 탭과 광고뿐, 구글은 웹 결과를 준다."""

    def __init__(self, *, google: str = "results") -> None:
        super().__init__(challenge_after=99)
        self._google = google

    def body_text(self) -> str:
        return _CHALLENGE if ("google.com" in self.url and self._google == "blocked") else "검색 결과"

    def elements(self) -> list[_Element]:
        if "naver.com" in self.url and "ssc=tab.blog" not in self.url:
            return [_Element("쇼핑", "https://search.naver.com/search.naver?where=shopping&query=x"),
                    _Element("이미지", "https://search.naver.com/search.naver?where=image&query=x")]
        if "google.com" in self.url and self._google != "results":
            return [_Element("이미지", "https://www.google.com/search?tbm=isch&q=x")]
        return [_Element(f"가상 마우스 X1 판매처 {i}", f"https://shop{i}.example/products/90{i}") for i in range(6)]


def _engines(page: _Page) -> list[str]:
    return ["naver" if "naver.com" in url else "google" if "google.com" in url else url for url in page.goto_calls]


def test_an_engine_that_came_back_empty_hands_over_to_the_next(tmp_path: Path) -> None:
    page = _NaverShowsOnlyAds()

    found = _worker(tmp_path)._search(page, {"query": "가상 마우스 X1"})

    assert _engines(page) == ["naver", "google"]
    assert found["result_count"] == 6 and found["engine"] == "google"
    assert found["fallback_used"] is True
    assert {"engine": "naver", "status": "empty"} in found["attempts"], "왜 넘어갔는지가 증거에 남아야 한다"


def test_when_every_engine_is_empty_it_says_zero_once_with_the_whole_story(tmp_path: Path) -> None:
    page = _NaverShowsOnlyAds(google="empty")

    found = _worker(tmp_path)._search(page, {"query": "가상 마우스 X1"})

    assert found["result_count"] == 0
    assert [item["status"] for item in found["attempts"]] == ["empty", "ok"], found["attempts"]


def test_an_empty_engine_followed_by_a_blocked_one_is_still_an_honest_zero(tmp_path: Path) -> None:
    """다음 엔진이 막혔다고 「검색엔진이 전부 막혔다」로 끝내지 않는다 — 앞 엔진은 열렸고 0건이었다."""
    page = _NaverShowsOnlyAds(google="blocked")

    found = _worker(tmp_path)._search(page, {"query": "가상 마우스 X1"})

    assert found["result_count"] == 0 and found["engine"] == "naver"
    assert [(item["engine"], item["status"]) for item in found["attempts"]] == [("naver", "empty"), ("google", "blocked")]


def test_a_tab_search_stays_on_the_engine_that_has_that_tab(tmp_path: Path) -> None:
    """블로그 · 뉴스 탭은 그 엔진의 것이다. 다른 엔진으로 넘기면 시킨 것과 다른 것을 찾아 온다."""

    class _BlogTabEmpty(_NaverShowsOnlyAds):
        def elements(self) -> list[_Element]:
            return [] if "naver.com" in self.url else super().elements()

    page = _BlogTabEmpty()

    found = _worker(tmp_path)._search(page, {"query": "가상 마우스 X1", "tab": "blog"})

    assert _engines(page) == ["naver"]
    assert found["result_count"] == 0


def test_an_engine_with_results_is_not_second_guessed(tmp_path: Path) -> None:
    page = _Page(challenge_after=99)

    found = _worker(tmp_path)._search(page, {"query": "가상 마우스 후기"})

    assert _engines(page) == ["naver"], "흔한 길에 이동을 보태지 않는다"
    assert found["fallback_used"] is False and found["result_count"] > 0


@pytest.mark.parametrize("engine", ["naver", "google"])
def test_naming_the_engine_does_not_turn_the_handover_off(tmp_path: Path, engine: str) -> None:
    """모델이 engine 을 지정해도 0건이면 넘긴다 — 지정한 엔진이 0건이었다는 것은 증거에 남는다."""
    page = _NaverShowsOnlyAds(google="results" if engine == "naver" else "empty")
    if engine == "google":
        # 구글이 비고 네이버 통합검색도 광고뿐 — 둘 다 0건. 차례(구글 → 네이버)를 다 돈 것만 본다.
        found = _worker(tmp_path)._search(page, {"query": "virtual mouse x1", "engine": engine})
        assert _engines(page) == ["google", "naver"] and found["result_count"] == 0
        return
    found = _worker(tmp_path)._search(page, {"query": "가상 마우스 X1", "engine": engine})
    assert found["engine"] == "google" and found["requested_engine"] == "naver"
