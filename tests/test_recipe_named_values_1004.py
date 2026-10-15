"""레시피가 **이름**을 받아 사이트의 값으로 바꾼다 — 번호를 짐작하지 않게 (2026-10-04 실전 판 574826ac).

「대전·세종·충남 지역의 정규직 공고 5개」를 맡겼더니 손자리가 지역을 걸려고 번호를 짐작해 주소를 조립했다
(`loc_mcd=41,42,44` · `85,86,51` · `47,55,46`). 사람인은 틀린 번호에 오류 대신 **개수 없는 서초구 공고 20개**를 돌려주고,
손자리는 「대전·세종·충남 0건 — 없다는 결론은 유효」라고 답했다. 진짜 번호(대전 105000 · 세종 118000 · 충남 115000)로는 16건이 있다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.site_recipes import RecipeError, SiteRecipeTools, load_recipes

RECIPES = Path(__file__).resolve().parents[1] / "recipes"


class _Worker:
    def __init__(self) -> None:
        self._recipe_search: dict[str, str] = {}
        self._recipe_result_markers: dict[str, list[str]] = {}
        self._site_search_delegate: Any = None
        self.opened: list[str] = []

    def execute_trusted(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.opened.append(str(arguments.get("url") or ""))
        return {"url": str(arguments.get("url") or "")}

    def execute(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {}


def _tools(tmp_path: Path, extra: dict[str, Any] | None = None) -> SiteRecipeTools:
    directory = tmp_path / "recipes"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "demo.json").write_text(
        json.dumps({
            "name": "demo", "hosts": ["demo.test"],
            "urls": {"s": "https://demo.test/?q={query}&loc={region}"},
            "actions": {"search_in_region": {"risk": "L0", "steps": [{"do": "open", "url_key": "s"}]}},
            "param_values": {"region": {"대전": "105000", "세종": "118000", "충남": "115000", "충청남도": "115000"}},
            "param_joins": {"region": "%2C"},
            **(extra or {}),
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o", site_recipe_dir=directory)
    return SiteRecipeTools(config, _Worker())


def _run(tools: SiteRecipeTools, region: str) -> str:
    tools.run({"site": "demo", "action": "search_in_region", "params": {"query": "연구비", "region": region}})
    return tools.worker.opened[-1]


# --- 이름 → 값 -----------------------------------------------------------------

def test_a_name_becomes_the_sites_own_value(tmp_path: Path) -> None:
    assert _run(_tools(tmp_path), "대전").endswith("&loc=105000")


@pytest.mark.parametrize("said", ["대전,세종,충남", "대전, 세종 · 충남", "대전/세종/충청남도", "대전 세종 충남"])
def test_several_names_are_joined_the_way_the_site_wants(tmp_path: Path, said: str) -> None:
    assert _run(_tools(tmp_path), said).endswith("&loc=105000%2C118000%2C115000")


def test_a_value_from_the_table_is_accepted_as_it_is(tmp_path: Path) -> None:
    assert _run(_tools(tmp_path), "105000").endswith("&loc=105000")


def test_a_guessed_number_is_refused_with_the_names_it_can_use(tmp_path: Path) -> None:
    tools = _tools(tmp_path)

    with pytest.raises(RecipeError) as refused:
        _run(tools, "41,42,44")

    assert "쓸 수 있는 이름" in str(refused.value) and "대전" in str(refused.value) and "짐작" in str(refused.value)
    assert tools.worker.opened == [], "틀린 값으로는 열지 않는다 — 그럴듯한 엉뚱한 목록이 근거가 된다"


def test_an_unknown_name_among_known_ones_refuses_the_whole_call(tmp_path: Path) -> None:
    with pytest.raises(RecipeError) as refused:
        _run(_tools(tmp_path), "대전,강남")

    assert "강남" in str(refused.value)


def test_a_recipe_without_a_table_runs_as_before(tmp_path: Path) -> None:
    tools = _tools(tmp_path, {"param_values": {}})

    assert _run(tools, "아무거나").endswith("&loc=아무거나")


def test_the_site_list_shows_the_names_to_choose_from(tmp_path: Path) -> None:
    listing = _tools(tmp_path).list_actions({})
    action = listing["sites"][0]["actions"][0]

    assert action["params"] == ["query", "region"]
    assert action["param_names"] == {"region": ["대전", "세종", "충남"]}


# --- 실제 사람인 레시피 -----------------------------------------------------------

def test_the_saramin_recipe_searches_by_region_name() -> None:
    saramin = load_recipes(RECIPES)["saramin"]
    table = saramin.param_values["region"]

    assert "search_jobs_in_region" in saramin.actions
    assert SiteRecipeTools._params_of(saramin, "search_jobs_in_region") == {"query", "region"}
    assert {table["대전"], table["세종"], table["충남"]} == {"105000", "118000", "115000"}
    assert table["대전광역시"] == table["대전"] and table["충청남도"] == table["충남"]
    assert len({name for name in table if len(name) <= 2}) == 17
    assert all(value.isdigit() and len(value) == 6 for value in table.values())
    filled = SiteRecipeTools._named_values(saramin, "saramin", "search_jobs_in_region", {"query": "연구비 정산", "region": "대전,세종,충남"})
    assert filled["region"] == "105000%2C118000%2C115000"


def test_the_plain_search_still_takes_only_a_query() -> None:
    """범용 사이트 검색이 대신 불러 주는 절차는 「값이 query 하나뿐」이어야 한다 — 그 조건을 깨지 않는다."""
    saramin = load_recipes(RECIPES)["saramin"]

    assert SiteRecipeTools._params_of(saramin, "search_jobs") == {"query"}
    assert saramin.actions["search_jobs_in_region"]["risk"] == "L0"
