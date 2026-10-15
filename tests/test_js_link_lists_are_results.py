"""`javascript:go_view(N)` 목록도 결과 목록이다 (2026-10-02 K-Startup 4차 판 70a447c4).

사이트 검색 「AI」가 공고 목록을 띄워 놓고 `result_count: 0` 을 보고했다 — 결과 판정이 http 주소만 받아서 K-Startup 공고
(전부 `javascript:go_view(N)`)가 통째로 빠졌다. 모델은 그 0 을 믿고 검색칸·필터를 35걸음 다시 만졌고, 상세는 하나만 읽고
걸음 상한(48)에 걸렸다. 진짜 크롬에 K-Startup 모양 목록·상세를 띄워 처음부터 끝까지 본다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

LIST = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?page=1&schStr=AI"
ROWS = [(176076, "2026년 팁스(TIPS) 창업기업 지원계획 수정 공고"), (179353, "AI 올라운더 창업가육성과정 8기 모집"),
        (178802, "초격차 스타트업 프로젝트 주관기관 모집")]
LIST_HTML = (
    "<html><head><title>K-Startup 창업지원포털>사업공고>모집중</title><script>"
    "function go_view(n){ location.href='/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn='+n; }"
    "function fn_delete(n){ document.title='지움'; }</script></head><body>"
    "<div id='header'><a href='/web/main.do'>홈</a><a href='/web/contents/bizpbanc-ongoing.do'>사업공고</a></div>"
    "<div class='board_list'><ul>"
    + "".join(f"<li><a href='javascript:go_view({n});'><p class='tit'>{t}</p><span>창업진흥원 · 마감일자 2026-12-31</span></a></li>"
              for n, t in ROWS)
    + "<li><a href='javascript:fn_delete(1);'>관심 공고 지우기 버튼</a></li>"
    + "</ul></div></body></html>"
)


def _detail(n: int) -> str:
    title = dict(ROWS).get(n, "공고")
    return (f"<html><head><title>{title} | K-Startup</title></head><body><main><h2>{title}</h2>"
            + "<p>신청 자격: 창업 7년 이내 기업. 사업자등록기준 3년 이상의 창업자는 제외대상.</p>" * 6 + "</main></body></html>")


def _serve(route) -> None:  # noqa: ANN001 — playwright Route
    url = route.request.url
    if "schM=view" in url:
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=_detail(int(url.split("pbancSn=")[1].split("&")[0])))
    else:
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=LIST_HTML)


def test_a_js_link_list_is_ranked_and_each_rank_opens_its_detail(tmp_path: Path) -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.route("https://www.k-startup.go.kr/**", _serve)
            page.goto(LIST)
            results = worker._collect_results(page, limit=10)
            assert [item["url"] for item in results] == [f"javascript:go_view({n})" for n, _ in ROWS], \
                "공고 셋이 순위로 잡히고, 지우기 같은 함수는 결과가 아니다"
            worker._last_results = results
            worker._remember_results_origin(page)

            first = worker._open_result(page, {"rank": 1})
            assert first["followed_js_link"] == "go_view"
            assert page.url.endswith("pbancSn=176076")

            # 상세에 서 있다(목록 함수가 없다). 통한 길 기억으로 2번을 바로 연다.
            second = worker._open_result(page, {"rank": 2})
            assert page.url.endswith("pbancSn=179353")
            assert second["remaining"] == [3]
        finally:
            browser.close()
