"""페이지가 이미 받아 온 JSON 에서 값을 찾는다 — 새 요청 없이, 같은 사이트만, 민감한 칸은 가려서 (2026-09-18)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis import page_data as pd

PAGE = """<!doctype html><html><body><canvas width=400 height=200></canvas>
<script>
fetch('https://api.shop.example/v2/items?q=mouse').then(r => r.json()).then(d => { window.loaded = d.items.length; });
fetch('https://ads.tracker.example/pixel').then(r => r.json());
</script></body></html>"""

ITEMS = {"items": [{"id": 1, "name": "ATK VXE R1 SE+ 무선 마우스", "price": 25900, "seller": {"name": "브라보텍"}},
                   {"id": 2, "name": "로지텍 G304", "price": 32000}],
         "accessToken": "abc123", "session": {"id": "s-1"},
         "debug": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig"}


def test_redaction_and_same_site_rules() -> None:
    red = pd.redact(ITEMS)
    assert red["accessToken"] == "[숨김]" and red["session"] == "[숨김]" and red["debug"] == "[숨김]"
    assert red["items"][0]["price"] == 25900
    assert pd.same_site("https://shop.example/list", "https://api.shop.example/v2/items")
    assert not pd.same_site("https://shop.example/list", "https://ads.tracker.example/pixel")
    assert pd.same_site("https://www.saramin.co.kr/a", "https://api.saramin.co.kr/b")
    assert not pd.same_site("https://a.co.kr/", "https://b.co.kr/")


def test_hits_carry_the_record_around_the_value() -> None:
    out = pd.summarize_responses("https://shop.example/list", [{"url": "https://api.shop.example/v2/items", "status": 200, "json": ITEMS}], "VXE")
    hit = out["responses"][0]["hits"][0]
    assert hit["path"] == "items[0].name" and hit["record"]["price"] == 25900
    assert "abc123" not in json.dumps(out, ensure_ascii=False)


def test_in_a_real_browser_only_what_the_page_fetched_is_read(tmp_path: Path) -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig

    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    requested: list[str] = []
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        page = browser.new_page()

        def serve(route):
            url = route.request.url
            requested.append(url)
            headers = {"access-control-allow-origin": "*"}
            if "api.shop.example" in url:
                route.fulfill(status=200, content_type="application/json", headers=headers, body=json.dumps(ITEMS))
            elif "ads.tracker.example" in url:
                route.fulfill(status=200, content_type="application/json", headers=headers, body=json.dumps({"items": [{"name": "ATK VXE 광고"}]}))
            else:
                route.fulfill(status=200, content_type="text/html", body=PAGE)

        page.route("**/*", serve)
        worker._watch_page(page)
        page.goto("https://shop.example/list")
        page.wait_for_function("() => window.loaded === 2")
        page.wait_for_timeout(200)
        before = len(requested)
        result = worker._page_data(page, {"query": "VXE"})
        shaped = worker._page_data(page, {})
        after = len(requested)
        browser.close()
    assert after == before, "도구가 새 요청을 보내면 안 된다"
    urls = [row["url"] for row in result["responses"]]
    assert urls == ["/v2/items"], "광고 도메인 응답은 빠져야 한다"
    assert result["responses"][0]["hits"][0]["record"]["price"] == 25900
    assert "abc123" not in json.dumps(result, ensure_ascii=False)
    assert shaped["responses"][0]["shape"]["items"]["list"] == 2
    assert "이미 받아 온" in result["instruction"]
