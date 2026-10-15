"""없는 페이지(404)는 「열었다」가 아니다 · 같은 사이트에서 같은 검색어를 되풀이하면 걸린다 (2026-10-04 허깅페이스 판 56247177).

모델이 기억으로 지어낸 모델 이름(`huggingface.co/Qwen/Qwen3-32B-A3B-Instruct`)을 열었고, 404 화면인데 도구는 OK 를
돌려줬다. 모델은 그 이름이 있는 줄 알고 같은 이름을 다섯 번 더 검색했다 — 20걸음 중 14걸음이 헛걸음.
없는 사이트(DNS 실패)는 8월에 막았는데 **사이트는 있고 페이지가 없는** 경우가 비어 있었다.
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from alture_jarvis import narration
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.browser import BrowserWorker


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status


class _Page:
    def __init__(self, title: str, body: str = "") -> None:
        self._title, self._body = title, body

    def title(self) -> str:
        return self._title

    def evaluate(self, _script: str) -> str:
        return self._body


def _missing(status: int, title: str, body: str = "") -> int:
    return BrowserWorker._not_found_page(BrowserWorker, _Page(title, body), _Response(status))  # type: ignore[arg-type]


# --- 없는 페이지 ---------------------------------------------------------------

def test_a_404_page_that_says_so_is_missing() -> None:
    assert _missing(404, "404 – Hugging Face") == 404
    assert _missing(404, "GitHub", "Page not found · This is not the web page you are looking for.") == 404
    assert _missing(410, "안내", "삭제된 게시물입니다") == 410
    assert _missing(404, "알림", "요청하신 페이지를 찾을 수 없습니다") == 404


def test_a_page_that_loaded_fine_is_not_missing() -> None:
    assert _missing(200, "Qwen/Qwen3-30B-A3B-Instruct-2507 · Hugging Face") == 0
    assert _missing(200, "404 오류 해결법 정리", "이 글은 404 not found 를 다룹니다") == 0  # 404 를 **다루는** 글
    assert _missing(403, "Forbidden") == 0  # 막힌 것은 다른 장치의 일


def test_a_404_status_alone_does_not_block_a_page_that_renders() -> None:
    """상태 코드만 믿지 않는다 — 404 로 답하면서 제대로 그리는 한 장짜리 앱이 있다."""
    assert _missing(404, "My Dashboard", "Welcome back. Today's tasks: write the report.") == 0


def test_an_unreadable_page_is_not_judged() -> None:
    class _Broken:
        def title(self) -> str:
            raise RuntimeError("target closed")

    assert BrowserWorker._not_found_page(BrowserWorker, _Broken(), _Response(404)) == 0  # type: ignore[arg-type]
    assert BrowserWorker._not_found_page(BrowserWorker, _Page("x"), None) == 0  # type: ignore[arg-type]


def test_the_open_path_raises_before_the_page_counts_as_opened() -> None:
    source = inspect.getsource(BrowserWorker._goto_checked)

    assert "missing = self._not_found_page(page, response)" in source
    assert "page_not_found:" in source and "짐작해서 만들지 마세요" in source
    assert source.index("self._not_found_page(page, response)") < source.index("self._under_maintenance(page)")


# --- 같은 사이트 · 같은 검색어 ---------------------------------------------------

def _on(url: str) -> list[dict[str, Any]]:
    return [{"tool": "browser_open", "ok": True, "evidence": {"url": url}}]


def test_the_same_site_search_from_another_page_is_the_same_action() -> None:
    query = {"query": "Qwen3-32B-A3B-Instruct", "limit": "5"}

    first = BrowserAgent._fingerprint("browser_site_search", query, _on("https://huggingface.co/Qwen/Qwen3-32B-A3B-Instruct"))
    second = BrowserAgent._fingerprint("browser_site_search", query, _on("https://huggingface.co/models?sort=trending"))
    elsewhere = BrowserAgent._fingerprint("browser_site_search", query, _on("https://github.com/search"))
    other_words = BrowserAgent._fingerprint("browser_site_search", {"query": "Qwen3 30B", "limit": "5"}, _on("https://huggingface.co/"))

    assert first == second          # 같은 사이트 · 같은 말 — 되풀이로 센다
    assert first != elsewhere       # 다른 사이트면 다른 검색이다
    assert first != other_words     # 낱말을 바꾸면 새 검색이다


def test_reading_stays_scoped_to_the_exact_page() -> None:
    """다음 글을 열고 읽는 것은 되풀이가 아니다(08-13) — 그건 그대로다."""
    one = BrowserAgent._fingerprint("browser_extract", {}, _on("https://huggingface.co/a/b"))
    two = BrowserAgent._fingerprint("browser_extract", {}, _on("https://huggingface.co/c/d"))

    assert one != two


# --- 중계에 새어 나온 내부 지시 ---------------------------------------------------

@pytest.mark.parametrize("echoed", [
    "사용자님, 정확한 모델명을 확인하겠습니다.\n\n더 생각하지 말고 지금 바로 다음 도구를 부르거나 최종 답을 내라.\n\n---\n\n정확한 모델명을 site_search로 확인하겠습니다.",
    "[생각 시간이 다 됐다]\n지금까지 네가 한 생각의 끝부분이다:\n모델명을 다시 찾겠습니다.",
])
def test_an_echoed_internal_nudge_is_not_shown(echoed: str) -> None:
    shown = narration.clean(echoed)

    assert "더 생각하지 말고" not in shown and "생각 시간이 다 됐다" not in shown and "---" not in shown
    assert "끝부분이다" not in shown
    assert "모델명" in shown  # 모델이 한 말은 남는다


def test_ordinary_narration_is_untouched() -> None:
    assert narration.clean("검색 결과에서 상위 세 개를 열어 보겠습니다.") == "검색 결과에서 상위 세 개를 열어 보겠습니다."
