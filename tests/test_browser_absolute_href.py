"""스냅샷의 주소는 **절대경로**여야 한다 — 아니면 대조하는 쪽과 하나도 안 맞는다.

2026-08-12 실측. 목록 판정기를 만들어 놓고도 다나와에서 계속 경쟁사 광고(에누리)가
1번이었다. 직접 진단하면 판정기는 진짜 상품 묶음(prod_main_info, 76개)을 정확히
고르는데, 자비스 경로에서는 안 먹혔다. 둘이 갈리는 지점이 여기였다:

    스냅샷            el.getAttribute("href")  ->  "/prod/123"          (상대)
    목록 판정기        a.href                   ->  "https://.../prod/123" (절대)
    네비게이션 필터    a.href                   ->  절대

**내부 링크는 어느 쪽과도 안 맞았다.** 그래서

  - 목록으로 좁히기가 통째로 실패 → **외부 광고만 절대경로라 살아남았다**
  - `_chrome_links` 가 내부 메뉴를 한 번도 못 걸러냈다 (오늘 이전부터)
  - `_validate_url` 은 상대경로를 받으면 "https:///prod/123" 을 만든다

한 줄짜리 차이가 세 군데를 조용히 망가뜨리고 있었다. 조용한 것이 제일 나쁘다.
"""

from __future__ import annotations

import re

from alture_jarvis.browser import BrowserWorker


def _collector_js() -> str:
    """요소 수집 JS 본문. 문자열로 박혀 있어 실행 대신 내용을 본다."""
    import inspect

    return inspect.getsource(BrowserWorker._frame_elements_fast)


def test_the_snapshot_resolves_relative_hrefs() -> None:
    source = _collector_js()

    assert "new URL(href, document.baseURI)" in source, (
        "상대경로를 그대로 담으면 대조하는 쪽과 안 맞는다"
    )


def test_the_resolution_cannot_throw_away_the_link() -> None:
    """javascript: · mailto: 처럼 URL() 이 못 다루는 것도 버리지 않는다."""
    source = _collector_js()

    match = re.search(r"try \{ absolute = new URL\(href, document\.baseURI\)\.href; \} catch", source)
    assert match, "실패하면 원래 값을 쓰도록 감싸야 한다"
    assert "let absolute = href;" in source


def test_the_comparers_use_absolute_urls() -> None:
    """대조하는 쪽이 절대경로를 쓴다는 사실 자체가 이 시험의 전제다."""
    assert "a.href" in BrowserWorker._RESULT_LIST_JS
