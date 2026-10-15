"""막혔을 때 갈 공개 출처 — 피드·공식 링크·robots.txt (2026-09-18)."""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis import site_sources as ss

ROBOTS = """User-agent: *
Disallow: /api/
Disallow: /member/
Allow: /

Sitemap: https://shop.example/sitemap.xml
Sitemap: https://shop.example/sitemap-products.xml
"""

PAGE = """<!doctype html><html><head>
<link rel="alternate" type="application/rss+xml" title="새 소식" href="https://shop.example/feed.xml">
</head><body>
<a href="https://maker.example/">제조사 공식 홈페이지</a>
<a href="https://shop.example/cart">장바구니</a>
<app-card></app-card>
<script>customElements.define('app-card', class extends HTMLElement { constructor() { super();
  this.attachShadow({mode:'open'}).innerHTML = '<a href="https://dev.example/">게시자 웹 사이트</a>'; } });</script>
</body></html>"""


def test_robots_says_which_paths_are_off_limits_and_where_the_sitemaps_are() -> None:
    open_path = ss.robots_verdict(ROBOTS, "https://shop.example/products/1")
    closed = ss.robots_verdict(ROBOTS, "https://shop.example/api/items?q=1")
    assert open_path["path_allowed"] is True and closed["path_allowed"] is False
    assert open_path["sitemaps"] == ["https://shop.example/sitemap.xml", "https://shop.example/sitemap-products.xml"]
    assert "자동 수집을 막았다" in ss.note_for({**closed, "feeds": [], "official": []})
    assert ss.robots_url("https://www.yes24.com/product/goods/1") == "https://www.yes24.com/robots.txt"


def test_in_a_real_browser_feeds_official_links_and_robots_are_found(tmp_path: Path) -> None:
    """진짜 HTTP 서버로 — robots.txt 는 페이지 가로채기를 안 거치는 요청이라 실제 경로 그대로 재야 한다."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    playwright_api = pytest.importorskip("playwright.sync_api")
    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body, ctype = (ROBOTS.replace("https://shop.example", f"http://127.0.0.1:{port}"), "text/plain; charset=utf-8")                 if self.path == "/robots.txt" else (PAGE, "text/html; charset=utf-8")
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # noqa: D401
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    try:
        with playwright_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"chromium not installed: {exc}")
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/products/1")
            page.wait_for_timeout(100)
            result = worker._site_sources(page, {})
            page.goto(f"http://127.0.0.1:{port}/api/items")
            closed = worker._site_sources(page, {})
            browser.close()
    finally:
        server.shutdown()
    assert result["feeds"][0]["href"] == "https://shop.example/feed.xml"
    texts = [o["text"] for o in result["official"]]
    assert "제조사 공식 홈페이지" in texts and "게시자 웹 사이트" in texts, "섀도 DOM 안 공식 링크도"
    assert not any("장바구니" in t for t in texts)
    assert result["robots"] == "read" and result["path_allowed"] is True
    assert result["sitemaps"][0] == f"http://127.0.0.1:{port}/sitemap.xml"
    assert closed["path_allowed"] is False and "자동 수집을 막았다" in closed["instruction"]
