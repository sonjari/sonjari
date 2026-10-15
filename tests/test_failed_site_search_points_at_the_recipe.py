"""일반 검색이 실패하면, **되는 길이 이미 있는지** 그 자리에서 알려 준다.

## 2026-08-16 실측 (사용자님이 쓰다가)

    "사람인에서 '연구비 관리'로 검색해서 정규직 공고 3개를 골라줘"

    2  browser_site_search   실패      <- 사람인 검색칸은 width=0 이라 원래 안 된다
    6~8 ui_find_target       j35, j35, j33
    11 browser_fill          ref=j79   <- 비전이 찾은 것과 **다른 칸**
    12 browser_press Enter
    -> 쿠팡풀필먼트·토목시공·배민캡틴 (연구비와 무관)

**사람인에는 그 실패 때문에 사람이 만들어 둔 레시피가 이미 있다**
(`recipes/saramin.json` 의 `search_jobs`, 주석에 "일반 경로가 이 사이트에서만 계속
실패했다"고 적혀 있다). 그 길을 두고 손으로 더듬다 엉뚱한 칸을 채운 것이다.

조건을 아무리 잘 대조해도 **엉뚱한 것을 검색하면 소용없다.** 그래서 도구가
실패하는 그 자리에서 되는 길을 알려 준다(사고 R: 안내문이 아니라 그 자리에서).

## 방향이 한쪽인 이유

레시피가 브라우저에게 알려 준다. 반대로 브라우저가 레시피를 뒤지면 순환한다 —
`site_recipes` 는 이미 `BrowserWorker` 를 쥐고 있다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.site_recipes import SiteRecipeTools


class _Worker:
    """레시피가 무엇을 알려 주는지만 본다."""

    def __init__(self) -> None:
        self._recipe_search: dict[str, str] = {}
        self._recipe_result_markers: dict[str, list[str]] = {}
        self._site_search_delegate: Any = None
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def execute_trusted(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("trusted", action, dict(arguments)))
        return {"url": str(arguments.get("url") or "")}

    def execute(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("plain", action, dict(arguments)))
        return {}


def _tools(tmp_path: Path, actions: dict[str, Any], hosts: list[str]) -> SiteRecipeTools:
    directory = tmp_path / "recipes"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "demo.json").write_text(
        json.dumps(
            {"name": "demo", "hosts": hosts, "urls": {"s": "https://demo.test/?q={query}"},
             "actions": actions},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o",
        site_recipe_dir=directory,
    )
    tools = SiteRecipeTools(config, _Worker())
    return tools


_READ_ONLY = {"steps": [{"do": "open", "url_key": "s"}]}


def test_a_search_recipe_is_advertised_by_host(tmp_path: Path) -> None:
    tools = _tools(tmp_path, {"search_jobs": dict(_READ_ONLY)}, ["demo.test", "www.demo.test"])
    tools._tell_browser_about_search_recipes()
    table = tools.worker._recipe_search
    assert table["demo.test"] == 'site_run(site="demo", action="search_jobs")'
    assert table["www.demo.test"] == table["demo.test"], "hosts 에 적힌 것 전부에 걸어야 한다"


def test_a_search_recipe_advertises_its_result_url_markers_too(tmp_path: Path) -> None:
    """순위를 나중에 복구해도 검색 직후와 같은 상세 URL만 남겨야 한다."""
    tools = _tools(
        tmp_path,
        {
            "search_jobs": {
                **_READ_ONLY,
                "result_url_contains": ["/jobs/view"],
            }
        },
        ["demo.test", "www.demo.test"],
    )

    tools._tell_browser_about_search_recipes()

    assert tools.worker._recipe_result_markers == {
        "demo.test": ["/jobs/view"],
        "www.demo.test": ["/jobs/view"],
    }


def test_generic_result_collection_keeps_reviewed_url_markers() -> None:
    """회사·기업정보 링크가 open_result 복구에서 다시 끼어들지 않는다."""
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._recipe_result_markers = {"demo.test": ["/jobs/view"]}
    page = SimpleNamespace(url="https://www.demo.test/search?q=x")
    assert worker._result_markers_for(page) == ["/jobs/view"]


def test_korean_action_names_count_too(tmp_path: Path) -> None:
    """레시피를 쓰는 사람이 특별한 이름을 외울 필요는 없다."""
    tools = _tools(tmp_path, {"공고검색": dict(_READ_ONLY)}, ["demo.test"])
    tools._tell_browser_about_search_recipes()
    assert "공고검색" in tools.worker._recipe_search["demo.test"]


def test_a_recipe_without_a_search_says_nothing(tmp_path: Path) -> None:
    """검색 절차가 없으면 알릴 것도 없다 — 엉뚱한 절차를 검색이라고 하면 안 된다."""
    tools = _tools(tmp_path, {"scrap": dict(_READ_ONLY)}, ["demo.test"])
    tools._tell_browser_about_search_recipes()
    assert tools.worker._recipe_search == {}


def test_a_matching_l0_search_is_run_automatically(tmp_path: Path) -> None:
    """모델이 site_run 이름을 기억하지 못해도 이미 검토된 읽기 길을 탄다."""
    tools = _tools(
        tmp_path,
        {"search_jobs": {**_READ_ONLY, "risk": "L0"}},
        ["demo.test"],
    )
    tools._tell_browser_about_search_recipes()

    result = tools.worker._site_search_delegate(
        "https://www.demo.test/jobs", {"query": "연구비 관리"}
    )

    assert result["status"] == "done"
    assert result["strategy"] == "reviewed_site_recipe"
    assert result["delegated_from"] == "browser_site_search"
    assert tools.worker.calls == [
        ("trusted", "browser_open", {"url": "https://demo.test/?q=연구비 관리"})
    ]


def test_direct_site_run_returns_ranked_search_results(tmp_path: Path) -> None:
    """site_run 뒤 snapshot j번호를 rank로 착각하지 않게 목록도 같은 결과에 싣는다."""
    tools = _tools(
        tmp_path,
        {
            "search_jobs": {
                **_READ_ONLY,
                "risk": "L0",
                "result_url_contains": ["/jobs/view"],
            }
        },
        ["demo.test"],
    )
    tools.worker.collect_reviewed_search_results = lambda markers, limit=15: {
        "results": [
            {"rank": 1, "title": "공고 A", "url": "https://demo.test/jobs/view/1"}
        ],
        "result_count": 1,
        "url": "https://demo.test/search?q=x",
    }

    result = tools.run(
        {"site": "demo", "action": "search_jobs", "params": {"query": "x"}}
    )

    assert result["result_count"] == 1
    assert result["results"][0]["title"] == "공고 A"
    assert "results의 rank" in result["instruction"]


def test_a_non_l0_search_is_never_run_automatically(tmp_path: Path) -> None:
    """이 연결은 게이트웨이 밖이므로 L1/L2를 넣으면 승인 경계가 무너진다."""
    tools = _tools(
        tmp_path,
        {"search_jobs": {**_READ_ONLY, "risk": "L1"}},
        ["demo.test"],
    )
    tools._tell_browser_about_search_recipes()

    assert (
        tools.worker._site_search_delegate(
            "https://demo.test/jobs", {"query": "연구비 관리"}
        )
        is None
    )
    assert tools.worker.calls == []


def test_another_host_does_not_run_the_recipe(tmp_path: Path) -> None:
    tools = _tools(
        tmp_path,
        {"search_jobs": {**_READ_ONLY, "risk": "L0"}},
        ["demo.test"],
    )
    tools._tell_browser_about_search_recipes()

    assert tools.worker._site_search_delegate(
        "https://wishket.com/project", {"query": "연구비 관리"}
    ) is None
    assert tools.worker.calls == []


def test_browser_site_search_enters_the_delegate_before_generic_dom_search() -> None:
    """안내문이 아니라 실제 브라우저 도구 진입점에서 연결되어야 한다."""
    worker = BrowserWorker.__new__(BrowserWorker)
    worker.config = SimpleNamespace(browser_task_timeout_sec=30)
    worker._current_page = lambda: SimpleNamespace(url="https://www.demo.test/jobs")
    seen: list[tuple[str, Any]] = []

    def submit(function: Any, timeout: Any = None, **kwargs: Any) -> Any:
        seen.append((str(kwargs.get("operation") or ""), timeout))
        return function()

    worker._submit = submit
    worker._site_search_delegate = lambda url, args: {
        "site": "demo",
        "action": "search_jobs",
        "status": "done",
        "seen_url": url,
        "seen_query": args["query"],
    }
    worker._finish_delegated_site_search = lambda result, args: {
        "strategy": "reviewed_site_recipe",
        "site": result["site"],
        "query": args["query"],
    }

    result = worker.execute("browser_site_search", {"query": "연구비 관리"})

    assert result == {
        "strategy": "reviewed_site_recipe",
        "site": "demo",
        "query": "연구비 관리",
    }
    assert [name for name, _ in seen] == [
        "browser_site_search:recipe_lookup",
        "browser_site_search:recipe_results",
    ]


def test_reviewed_result_url_markers_remove_card_side_links() -> None:
    """사람인 카드의 회사·기업정보 링크는 공고 순위가 아니다."""
    rows = [
        {"rank": 1, "title": "공고 A", "url": "https://demo.test/jobs/view?id=1"},
        {"rank": 2, "title": "기업 A", "url": "https://demo.test/company?id=1"},
        {"rank": 3, "title": "공고 B", "url": "https://demo.test/jobs/view?id=2"},
        {"rank": 4, "title": "기업 B", "url": "https://demo.test/company?id=2"},
    ]

    filtered = BrowserWorker._filter_reviewed_results(
        rows, ["/jobs/view"], limit=2
    )

    assert [item["title"] for item in filtered] == ["공고 A", "공고 B"]
    assert [item["rank"] for item in filtered] == [1, 2]


# ── 실패 자리에서 실제로 그 말이 나오는가 ────────────────────────────────────


def _worker_knowing(table: dict[str, str]) -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._recipe_search = table
    return worker


def test_the_hint_names_the_recipe_call() -> None:
    worker = _worker_knowing({"saramin.co.kr": 'site_run(site="saramin", action="search_jobs")'})
    hint = worker._recipe_search_hint("www.saramin.co.kr")
    assert 'site_run(site="saramin", action="search_jobs")' in hint
    assert "사람이 검토해 둔" in hint


def test_an_unknown_site_gets_no_hint() -> None:
    """레시피가 없는 사이트에 있지도 않은 길을 대면 그게 더 나쁘다."""
    worker = _worker_knowing({"saramin.co.kr": "site_run(...)"})
    assert worker._recipe_search_hint("www.wishket.com") == ""


def test_a_worker_that_was_never_told_is_quiet() -> None:
    assert _worker_knowing({})._recipe_search_hint("www.saramin.co.kr") == ""
