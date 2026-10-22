"""GitHub 은 브라우저로 간다 (2026-10-21 판 b3ace188 · 대표: 「깃허브는 API 굳이 안 쓰고 브라우저로 치고 가면 된다」).

손자리가 이미 아는 「주인/저장소」 일곱 개를 API 로 다시 검색했고, 일곱 번째는 한도 메시지가 **성공으로** 와서
실패인 줄도 몰랐다. 3개를 못 열고 끝났다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent

LIMITED = {"ok": True, "result": {"message": '{"message":"API rate limit exceeded for 1.2.3.4. (But here\'s the good news...)"}'}}
FOUND = {"ok": True, "result": {"ok": True, "items": ["{'full_name': 'alirezamika/autoscraper'}"]}}


def test_a_rate_limit_is_a_failure_with_the_browser_address_to_open() -> None:
    out = BrowserAgent._github_to_browser("github_search", {"query": "browser-use/workflow-use"}, LIMITED)
    assert out["ok"] is False and out["result"]["error"] == "github_api_rate_limited"
    assert "browser_open https://github.com/browser-use/workflow-use" in out["result"]["instruction"]


def test_a_rate_limit_on_a_free_search_points_at_githubs_own_search_page() -> None:
    out = BrowserAgent._github_to_browser("github_search", {"query": "wrapper induction python"}, LIMITED)
    assert "https://github.com/search?q=wrapper+induction+python&type=repositories" in out["result"]["instruction"]


def test_a_known_repo_name_says_open_it_in_the_browser() -> None:
    out = BrowserAgent._github_to_browser("github_search", {"query": "alirezamika/autoscraper"}, FOUND)
    assert out["ok"] is True and out["result"]["instruction"].startswith("★ 이미 아는 저장소다")
    assert "browser_open https://github.com/alirezamika/autoscraper" in out["result"]["instruction"]


def test_other_tools_and_free_searches_are_untouched() -> None:
    assert BrowserAgent._github_to_browser("browser_open", {"query": "a/b"}, FOUND) == FOUND
    assert BrowserAgent._github_to_browser("github_search", {"query": "scraping library"}, FOUND) == FOUND
