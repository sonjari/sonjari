"""Site recipes: what a data file is allowed to do, and what it cannot.

A recipe is meant to be edited quickly -- that is the whole point of moving site
knowledge out of Python. Which means the rules protecting the user cannot be
conventions written in the README; they have to be checks. Most of these tests
are about a *bad* recipe being refused, and refused when it loads rather than
half-way through running against a live page.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.site_recipes import RecipeError, SiteRecipeTools, load_recipes


def _write(directory: Path, name: str, data: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _recipe(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "demo",
        "hosts": ["example.test"],
        "urls": {"editor": "https://example.test/write"},
        "targets": {"title": ["#title"], "save": ["#save"]},
        "actions": {
            "save_draft": {
                "risk": "L2",
                "steps": [
                    {"do": "open", "url_key": "editor"},
                    {"do": "dismiss"},
                    {"do": "fill", "target": "title", "value": "{title}"},
                    {
                        "do": "click",
                        "target": "save",
                        "expect": {"kind": "number_increases", "selector": "#save"},
                    },
                ],
            }
        },
    }
    base.update(overrides)
    return base


class FakeWorker:
    """Records every browser call a recipe makes."""

    def __init__(self, *, verified: bool = True) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.verified = verified

    def execute(self, action: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = dict(arguments or {})
        self.calls.append((action, arguments))
        if action == "browser_open":
            return {"url": arguments.get("url", "")}
        if action == "browser_find_selector":
            return {"ref": "j901", "selector": arguments["selectors"][0], "frame": "main"}
        if action in {"browser_click", "browser_press"}:
            return {
                "verified": self.verified,
                "verification": {
                    "status": "verified" if self.verified else "unknown",
                    "evidence": "number:3->4" if self.verified else "",
                },
            }
        if action == "browser_verify":
            return {"verification": {"status": "verified", "evidence": "text_present"}}
        if action == "browser_dismiss_dialog":
            return {"dialog_count": 1}
        return {}

    # 레시피는 셀렉터를 쓰는 expect 를 써도 되므로 **신뢰 문**으로 들어온다.
    # 진짜 워커도 두 문이 같은 핸들러로 이어지므로 여기서도 같은 자리에 기록한다 —
    # 문만 다르고 하는 일이 달라지면 이 가짜가 진짜를 대변하지 못한다.
    def execute_trusted(
        self, action: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.execute(action, arguments)


def _tools(tmp_path: Path, worker: FakeWorker, data: dict[str, Any] | None = None):
    directory = tmp_path / "recipes"
    _write(directory, "demo", data if data is not None else _recipe())
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "out",
        site_recipe_dir=directory,
    )
    return SiteRecipeTools(config, worker)


# ── a recipe that would lie is refused at load time ──────────────────────────
def test_a_mutating_click_without_evidence_is_refused_when_it_loads(
    tmp_path: Path,
) -> None:
    """The rule the whole verification layer exists for. Catching it at load
    means it cannot first surface as a false "저장했습니다"."""
    broken = _recipe()
    broken["actions"]["save_draft"]["steps"][3].pop("expect")

    with pytest.raises(RecipeError, match="expect가 필요하다"):
        _tools(tmp_path, FakeWorker(), broken)


def test_typing_into_a_field_does_not_need_evidence(tmp_path: Path) -> None:
    # Filling is undone by filling again; its proof is the save that follows.
    # Requiring evidence here would push authors toward meaningless checks.
    data = _recipe()
    data["actions"]["save_draft"]["steps"] = [
        {"do": "fill", "target": "title", "value": "{title}"}
    ]
    assert _tools(tmp_path, FakeWorker(), data).recipes["demo"]


def test_a_target_that_was_never_declared_is_refused(tmp_path: Path) -> None:
    data = _recipe()
    data["actions"]["save_draft"]["steps"][2]["target"] = "subtitle"
    with pytest.raises(RecipeError, match="targets에 'subtitle'가 없다"):
        _tools(tmp_path, FakeWorker(), data)


def test_a_recipe_with_no_hosts_is_refused(tmp_path: Path) -> None:
    # hosts is the safety line -- an empty one means "anywhere".
    with pytest.raises(RecipeError, match="hosts"):
        _tools(tmp_path, FakeWorker(), _recipe(hosts=[]))


def test_an_unknown_step_is_named_rather_than_skipped(tmp_path: Path) -> None:
    data = _recipe()
    data["actions"]["save_draft"]["steps"].append({"do": "publish"})
    with pytest.raises(RecipeError, match="모르는 단계 'publish'"):
        _tools(tmp_path, FakeWorker(), data)


def test_broken_json_names_the_file(tmp_path: Path) -> None:
    directory = tmp_path / "recipes"
    directory.mkdir()
    (directory / "bad.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(RecipeError, match="bad.json"):
        load_recipes(directory)


# ── running one ──────────────────────────────────────────────────────────────
def test_the_steps_run_in_order_through_the_ordinary_browser_tools(
    tmp_path: Path,
) -> None:
    """A recipe gets the guarded click, the read-only gate and the evidence
    check for free precisely because it owns no click path of its own."""
    worker = FakeWorker()

    result = _tools(tmp_path, worker).run(
        {"site": "demo", "action": "save_draft", "params": {"title": "제목입니다"}}
    )

    assert result["status"] == "done"
    assert [call[0] for call in worker.calls] == [
        "browser_open",
        "browser_dismiss_dialog",
        "browser_find_selector",
        "browser_fill",
        "browser_find_selector",
        "browser_click",
    ]
    assert worker.calls[3][1]["value"] == "제목입니다"
    assert worker.calls[5][1]["expect"]["kind"] == "number_increases"


def test_an_unverified_step_stops_the_recipe_rather_than_carrying_on(
    tmp_path: Path,
) -> None:
    """Continuing would run the remaining steps against a page that is not in
    the state they assume -- and the answer would still read as success."""
    worker = FakeWorker(verified=False)

    result = _tools(tmp_path, worker).run(
        {"site": "demo", "action": "save_draft", "params": {"title": "x"}}
    )

    assert result["status"] == "unverified"
    assert "다시 실행하지 마시고" in result["reason"]
    assert result["steps"][-1]["verified"] is False


def test_a_missing_value_stops_before_touching_the_browser(tmp_path: Path) -> None:
    # Guessing here is how a post goes up with a placeholder in the title.
    worker = FakeWorker()
    with pytest.raises(RecipeError, match=r"값이 없다 — \['title'\]"):
        _tools(tmp_path, worker).run({"site": "demo", "action": "save_draft"})
    assert worker.calls == []


def test_a_url_outside_the_declared_hosts_is_refused(tmp_path: Path) -> None:
    data = _recipe()
    data["urls"]["editor"] = "https://evil.test/write"
    tools = _tools(tmp_path, FakeWorker(), data)

    with pytest.raises(RecipeError, match="허용되지 않은 주소"):
        tools.run({"site": "demo", "action": "save_draft", "params": {"title": "x"}})


def test_an_unknown_site_or_action_says_what_does_exist(tmp_path: Path) -> None:
    tools = _tools(tmp_path, FakeWorker())
    with pytest.raises(RecipeError, match=r"등록된 것: \['demo'\]"):
        tools.run({"site": "coupang", "action": "buy"})
    with pytest.raises(RecipeError, match=r"있는 것: \['save_draft'\]"):
        tools.run({"site": "demo", "action": "publish"})


def test_the_listing_reports_which_values_each_action_needs(tmp_path: Path) -> None:
    listing = _tools(tmp_path, FakeWorker()).list_actions()

    action = listing["sites"][0]["actions"][0]
    assert action["params"] == ["title"]
    assert action["risk"] == "L2"


def test_comment_keys_are_ignored_so_authors_can_explain_themselves(
    tmp_path: Path,
) -> None:
    # The reason a selector exists is the part that took two days to learn. It
    # has to be storable next to the selector.
    data = _recipe()
    data["_note"] = "왜 이렇게 했는지"
    data["actions"]["save_draft"]["steps"][0]["_why"] = "글쓰기 버튼을 찾지 않는다"

    result = _tools(tmp_path, FakeWorker(), data).run(
        {"site": "demo", "action": "save_draft", "params": {"title": "x"}}
    )

    assert result["status"] == "done"


# ── the shipped recipe ───────────────────────────────────────────────────────
def test_the_naver_blog_recipe_in_the_repo_actually_loads(tmp_path: Path) -> None:
    """A recipe that ships broken is worse than no recipe: it looks available in
    the tool listing and fails only when someone asks for it."""
    del tmp_path
    directory = Path(__file__).resolve().parents[1] / "recipes"
    recipes = load_recipes(directory)

    assert "naver_blog" in recipes
    save = recipes["naver_blog"].actions["save_draft"]
    assert save["risk"] == "L2", "임시저장은 화면 승인 대상이다"
    assert save["steps"][-1]["expect"]["kind"] == "number_increases"
