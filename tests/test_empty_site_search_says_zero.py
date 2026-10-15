"""사이트 검색이 0건이면 0건이라고 말한다 (2026-10-01 밤 운영 판 b9f90b2c).

허깅페이스에서 「7B 14B model GGUF Q4」를 쳤더니 맞는 모델이 0개였다. 진짜 목록이 없자 도구는 화면의 아무 링크나
모아 왔는데 그게 왼쪽 필터 20개였고, 「이 사이트가 직접 준 목록이다(20건)」라고 알렸다. 1번을 열자 「Text Generation」
필터 화면이 열렸고 판은 모델 이름 하나 없이 끝났다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

FILTERS = [{"rank": i + 1, "title": name, "url": f"https://huggingface.co/models?pipeline_tag={name}"}
           for i, name in enumerate(["text-generation", "any-to-any", "image-to-text", "text-to-image"])]


class _Page:
    def __init__(self, text: str) -> None:
        self.url = "https://huggingface.co/models"
        self._text = text

    def evaluate(self, script: str, *args: Any) -> Any:
        if script is BrowserWorker._NO_RESULTS_JS:
            return self._text
        if "data-jarvis-sitesearch" in script and "removeAttribute" in script:
            return None
        return {"score": 11, "name": "Filter by name", "tag": "input"}

    def locator(self, selector: str) -> Any:
        page = self

        class _L:
            first = None

            def click(self, timeout: int = 0) -> None:
                pass

            def fill(self, value: str) -> None:
                pass

            def press(self, key: str) -> None:
                page.url = "https://huggingface.co/models?search=7B+14B+model+GGUF+Q4"

        loc = _L()
        loc.first = loc
        return loc

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        pass

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "Models – Hugging Face"


def _worker(tmp_path: Path, listed: int) -> BrowserWorker:
    worker = BrowserWorker(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_visual_overlay=False, browser_evidence_dir=tmp_path / "evidence",
    ))
    worker._wait_until_operable = lambda page: {"count": 42, "ms": 1, "polls": 1}  # type: ignore[method-assign]
    worker._collect_results = lambda page, limit=12: list(FILTERS)  # type: ignore[method-assign]
    worker._result_list_rows = lambda page: [{"name": "m", "href": f"https://huggingface.co/a/m{i}"} for i in range(listed)]  # type: ignore[method-assign]
    return worker


def test_no_results_screen_returns_zero_and_says_so(tmp_path: Path) -> None:
    worker = _worker(tmp_path, listed=0)
    page = _Page("Models 0 Base only Sort: Trending No results found. Try Full-text search instead.")
    result = worker._site_search(page, {"query": "7B 14B model GGUF Q4"})
    assert result["result_count"] == 0
    assert result.get("no_results") is True
    assert "0건" in result["instruction"] and "필터" in result["instruction"]
    assert "직접 준 목록이다" not in result["instruction"]


def test_a_real_list_is_kept_even_if_the_words_appear(tmp_path: Path) -> None:
    """판정기가 목록을 찾았으면(3개 이상) 「no results」 글자가 어딘가 있어도 결과를 지우지 않는다."""
    worker = _worker(tmp_path, listed=5)
    page = _Page("No results found in Datasets. Models 4,614 Qwen/Qwen3-14B-GGUF …")
    result = worker._site_search(page, {"query": "14B"})
    assert result["result_count"] == len(FILTERS)
    assert "no_results" not in result


def test_without_the_words_nothing_changes(tmp_path: Path) -> None:
    worker = _worker(tmp_path, listed=0)
    page = _Page("Models 30 Sort: Trending")
    result = worker._site_search(page, {"query": "14B"})
    assert result["result_count"] == len(FILTERS)
    assert "직접 준 목록이다" in result["instruction"]
