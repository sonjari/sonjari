"""사이트 성질 기억 (2026-09-18) — 본 것만 세고, 다시 올 때 한 줄로."""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.site_traits import STALE_AFTER_SEC, SiteTraits, site_key


def test_hosts_are_kept_apart_but_www_is_ignored() -> None:
    assert site_key("https://apps.microsoft.com/detail/x") == "apps.microsoft.com"
    assert site_key("https://www.microsoft.com/ko-kr/") == "microsoft.com"
    assert site_key("https://www.yes24.com/product/goods/1") == "yes24.com"
    assert site_key("") == ""


def test_counts_details_and_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "site_traits.json"
    traits = SiteTraits(path)
    traits.record("https://apps.microsoft.com/home", "shadow_dom")
    traits.record("https://apps.microsoft.com/detail/9", "shadow_dom")
    traits.record("https://apps.microsoft.com/detail/9", "structured_data", "softwareapplication")
    again = SiteTraits(path)
    found = {t["trait"]: t for t in again.traits_for("https://apps.microsoft.com/search?query=AI")}
    assert found["shadow_dom"]["count"] == 2 and found["structured_data"]["details"] == ["softwareapplication"]
    note = again.note_for("https://apps.microsoft.com/")
    assert note.startswith("[도구가 보낸 안내] 전에 apps.microsoft.com 에서 본 것:") and "섀도 DOM" in note
    assert again.traits_for("https://www.microsoft.com/") == [], "다른 호스트에 새지 않는다"


def test_only_the_latest_of_two_opposites_is_told(tmp_path: Path) -> None:
    traits = SiteTraits(tmp_path / "t.json")
    traits.record("https://webawesome.com/", "site_search_fails", now=1000)
    traits.record("https://webawesome.com/", "site_search_ok", now=2000)
    names = [t["trait"] for t in traits.traits_for("https://webawesome.com/docs", now=2001)]
    assert names == ["site_search_ok"]


def test_old_traits_fade(tmp_path: Path) -> None:
    traits = SiteTraits(tmp_path / "t.json")
    traits.record("https://coupang.com/", "bot_wall", now=0)
    assert traits.traits_for("https://coupang.com/", now=STALE_AFTER_SEC + 10) == []


def test_unknown_traits_and_empty_urls_are_ignored(tmp_path: Path) -> None:
    traits = SiteTraits(tmp_path / "t.json")
    traits.record("", "shadow_dom")
    traits.record("https://x.com/", "made_up_trait")
    assert traits.traits_for("https://x.com/") == []


def test_the_browser_remembers_a_shadow_page_and_tells_on_the_next_open(tmp_path: Path) -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig

    import test_shadow_dom_reach as shadow

    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out"))
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        page = browser.new_page()
        page.route("https://store.example/**", lambda route: route.fulfill(content_type="text/html", body=shadow.SHADOW_PAGE))
        page.goto("https://store.example/detail/app1")
        # 고정 100ms 는 병렬 부하에서 가끔 모자랐다(-n 8 에서만 깨짐) — 섀도 루트가 실제로 채워질 때까지 기다린다.
        page.wait_for_function(
            "() => { const g = document.querySelector('store-grid'); return !!(g && g.shadowRoot && g.shadowRoot.childElementCount); }",
            timeout=10_000,
        )
        worker._sweep_for_lazy_content = lambda _page: None  # type: ignore[method-assign]
        read = worker._read_with_data(page, {})
        assert read.get("shadow_dom") is True
        told = worker._with_site_traits(page, {"action": "opened", "instruction": "원래 안내"})
        browser.close()
    assert [t["trait"] for t in told["site_traits"]] == ["shadow_dom"]
    assert "store.example" in told["instruction"] and told["instruction"].endswith("원래 안내")
    assert (tmp_path / "data" / "site_traits.json").exists()
