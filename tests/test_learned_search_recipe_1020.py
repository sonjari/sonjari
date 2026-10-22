"""잘 끝난 판 → 「레시피로 저장해 둘까요?」 → 「응」 → 다음 판은 그 주소로 바로 (2026-10-20 · 확장 설계 P1 · T5).

P0 재생 실측(설계 §10): 주소 열기 초안 28/30 · 평균 1.2초, 누르는 절차 1/14. 그래서 첫 판은 잘 도는 쪽(검색 주소 + 빈칸
하나)만 저장을 권한다. 권하기 · 읽어 주기 · 「응」은 모델이 아니라 도구가 한다 — 그림 읽기 제안(`self_talk`)과 같은 틀.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alture_jarvis.config import JarvisConfig
from alture_jarvis.recipe_from_run import draft_from_run, learned_search_recipe, read_out
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.self_talk import SelfContext, SelfTalk, recipe_offer_text
from alture_jarvis.site_recipes import SiteRecipeTools

SEARCH_URL = "https://www.yes24.com/Product/Search?domain=ALL&query=%ED%8C%8C%EC%9D%B4%EC%8D%AC"


def _steps() -> list[dict[str, Any]]:
    return [
        {"tool": "browser_open", "ok": True, "arguments": {"url": "https://www.yes24.com/"}, "evidence": {"url": "https://www.yes24.com/"}},
        {"tool": "browser_open", "ok": True, "arguments": {"url": SEARCH_URL}, "evidence": {"url": SEARCH_URL}},
    ]


def _recipe() -> dict[str, Any]:
    recipe = learned_search_recipe(draft_from_run("예스24 에서 파이썬 책 찾아 줘", _steps(), job_id="j-9"))
    assert recipe is not None
    return recipe


def test_a_search_address_run_becomes_a_learned_l0_search() -> None:
    recipe = _recipe()
    assert recipe["name"] == "yes24_learned"
    assert recipe["actions"]["search"]["risk"] == "L0"
    assert recipe["actions"]["search"]["steps"] == [{"do": "open", "url": "https://www.yes24.com/Product/Search?domain=ALL&query={query}"}]
    assert recipe["_learned_from"]["job_id"] == "j-9"
    text = read_out(recipe)
    assert "읽기만" in text and "확인" in text and "{찾을 말}" in text


def test_procedures_are_not_offered_yet() -> None:
    """누르는 절차는 재생 1/14 — 시연 입구(P2)로 간다. 첫 판은 권하지 않는다."""
    steps = _steps() + [{"tool": "browser_click", "ok": True, "arguments": {"ref": "j1", "expect": {"kind": "url_changes"}},
                         "evidence": {"url": SEARCH_URL + "&sort=low", "verified": True, "selectors": ['text="낮은 가격순"']}}]
    assert learned_search_recipe(draft_from_run("예스24", steps)) is None


def _ctx(saved: list, forgotten: list, declined: list) -> SelfContext:
    return SelfContext(
        version=lambda: "0.4.30.0", lang=lambda: "ko", current_eyes=lambda: {}, apply_eyes=lambda on: {}, summary=lambda: {},
        save_recipe=lambda recipe: saved.append(recipe) or {"saved": True, "name": recipe["name"], "path": "x"},
        forget_recipe=lambda name: forgotten.append(name) or {"removed": True, "name": name},
        decline_recipe=declined.append,
    )


def test_yes_saves_exactly_what_was_shown_and_undo_removes_it() -> None:
    talk, saved, forgotten, declined = SelfTalk(), [], [], []
    talk.offer_recipe("s1", _recipe())
    reply = talk.intercept("응", "s1", _ctx(saved, forgotten, declined))
    assert reply["kind"] == "recipe_saved" and saved == [_recipe()]
    assert "되돌려" in reply["answer"]
    undone = talk.intercept("되돌려", "s1", _ctx(saved, forgotten, declined))
    assert undone["kind"] == "recipe_forgotten" and forgotten == ["yes24_learned"]


def test_no_is_remembered_and_another_sentence_drops_the_offer() -> None:
    talk, saved, forgotten, declined = SelfTalk(), [], [], []
    talk.offer_recipe("s1", _recipe())
    assert talk.intercept("아니", "s1", _ctx(saved, forgotten, declined))["kind"] == "recipe_declined"
    assert declined == ["yes24_learned"] and saved == []
    talk.offer_recipe("s1", _recipe())
    assert talk.intercept("다나와에서 마우스 찾아 줘", "s1", _ctx(saved, forgotten, declined)) is None
    assert talk.intercept("응", "s1", _ctx(saved, forgotten, declined)) is None, "엇갈린 「응」이 저장하면 안 된다"
    assert saved == []


def test_offer_text_shows_the_read_out_and_asks_once() -> None:
    text = recipe_offer_text(read_out(_recipe()))
    assert text.startswith("\n\n---\n이 일을 레시피로 저장해 둘까요?") and text.endswith("(응 / 아니)")


class _Worker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute_trusted(self, action: str, arguments: dict) -> dict:
        self.calls.append((action, dict(arguments)))
        return {"url": str(arguments.get("url") or "")}

    def execute(self, action: str, arguments: dict) -> dict:
        self.calls.append((action, dict(arguments)))
        return {}


def _tools(tmp_path: Path) -> SiteRecipeTools:
    builtin = tmp_path / "recipes"
    builtin.mkdir(parents=True)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o",
                          site_recipe_dir=builtin, documents_dir=tmp_path / "docs")
    return SiteRecipeTools(config, _Worker())


def test_a_saved_recipe_is_used_by_the_next_site_search_and_can_be_forgotten(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    saved = tools.save_learned(_recipe())
    assert Path(saved["path"]).parent == tmp_path / "docs" / "recipes", "사람 폴더(문서)에 둔다 — 프로그램 폴더 아님"
    assert tools.has_search_for("https://www.yes24.com/")
    result = tools._auto_search_recipe("https://www.yes24.com/", {"query": "러스트"})
    assert result and result["status"] == "done" and result["site"] == "yes24_learned"
    assert tools.worker.calls[0] == ("browser_open", {"url": "https://www.yes24.com/Product/Search?domain=ALL&query=러스트"})
    assert tools.forget_learned("yes24_learned")["removed"] is True
    assert not tools.has_search_for("https://www.yes24.com/")


def test_a_built_in_recipe_wins_over_a_learned_one_with_the_same_name(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    (tmp_path / "recipes" / "yes24_learned.json").write_text(json.dumps(
        {"name": "yes24_learned", "hosts": ["yes24.com"], "actions": {"search": {"risk": "L0", "steps": [{"do": "open", "url": "https://www.yes24.com/built?q={query}"}]}}}),
        encoding="utf-8")
    tools.recipes = tools._load_all()
    tools.save_learned(_recipe())
    assert "built" in tools.recipes["yes24_learned"].actions["search"]["steps"][0]["url"]


def test_the_receipt_is_one_quiet_line_and_says_when_it_stopped() -> None:
    ok = [{"tool": "browser_site_search", "ok": True, "evidence": {"site": "yes24_learned", "strategy": "reviewed_site_recipe", "status": "done"}}]
    assert JarvisRuntime._learned_recipe_receipt(ok) == "\n\n— 저장한 레시피(「yes24 검색」)로 바로 열었습니다 · 1/1 ✓"
    stopped = [{"tool": "site_run", "ok": False, "arguments": {"site": "yes24_learned"}, "evidence": {}}]
    assert "멈춰" in JarvisRuntime._learned_recipe_receipt(stopped)
    assert JarvisRuntime._learned_recipe_receipt([{"tool": "browser_open", "ok": True, "evidence": {"url": "x"}}]) == ""


class _Runtime:
    """`JarvisRuntime` 의 레시피 제안 함수만 빌려 쓴다 — 무거운 런타임을 띄우지 않는다."""

    RECIPE_OFFER_MAX = JarvisRuntime.RECIPE_OFFER_MAX
    _recipe_offers_path = JarvisRuntime._recipe_offers_path
    _recipe_offer_book = JarvisRuntime._recipe_offer_book
    _write_recipe_offer_book = JarvisRuntime._write_recipe_offer_book
    _declined_recipe_names = JarvisRuntime._declined_recipe_names
    _decline_recipe_offer = JarvisRuntime._decline_recipe_offer
    _count_recipe_offer = JarvisRuntime._count_recipe_offer
    _recipe_offer = JarvisRuntime._recipe_offer

    def __init__(self, tmp_path: Path) -> None:
        self.site_recipes = _tools(tmp_path)
        self.config = self.site_recipes.config


def _trace(**overrides: Any) -> dict[str, Any]:
    trace = {"steps": _steps(), "plan": {"met": 1, "total": 1}, "verification": {"completion_state": "complete", "answer_conflict": ""}}
    trace.update(overrides)
    return trace


def test_the_runtime_offers_only_for_clean_runs_and_stops_asking(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    text, recipe = runtime._recipe_offer("예스24 에서 파이썬 책 찾아 줘", "책 셋입니다.", _trace())
    assert "레시피로 저장해 둘까요?" in text and recipe["name"] == "yes24_learned"
    assert runtime._recipe_offer("x", "⚠ 읽지 않고 적은 것이 있습니다", _trace()) == ("", {}), "경고 붙은 판은 권하지 않는다"
    assert runtime._recipe_offer("x", "답", _trace(verification={"completion_state": "partial"})) == ("", {})
    runtime._count_recipe_offer("yes24_learned")
    runtime._count_recipe_offer("yes24_learned")
    assert runtime._recipe_offer("x", "답", _trace()) == ("", {}), "대답 없이 두 번 지나가면 더 묻지 않는다"


def test_the_runtime_does_not_offer_after_no_or_when_a_search_exists(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    runtime._decline_recipe_offer("yes24_learned")
    assert runtime._recipe_offer("x", "답", _trace()) == ("", {})
    other = _Runtime(tmp_path / "b")
    other.site_recipes.save_learned(_recipe())
    assert other._recipe_offer("x", "답", _trace()) == ("", {}), "이미 검색 절차가 있으면 묻지 않는다"


def test_search_engines_and_per_search_tags_are_not_learned() -> None:
    naver = [{"tool": "browser_open", "ok": True, "arguments": {}, "evidence": {"url": "https://search.naver.com/search.naver?query=%ED%8C%8C%EC%9D%B4%EC%8D%AC"}}]
    assert learned_search_recipe(draft_from_run("파이썬 찾아 줘", naver)) is None, "검색엔진은 검색 도구가 따로 있다"
    coupang = [{"tool": "browser_open", "ok": True, "arguments": {}, "evidence": {"url": "https://www.coupang.com/np/search?q=%EB%A7%88%EC%9A%B0%EC%8A%A4&traceId=mt09uel1&channel=user"}}]
    recipe = learned_search_recipe(draft_from_run("쿠팡에서 마우스 찾아 줘", coupang))
    assert recipe["actions"]["search"]["steps"][0]["url"] == "https://www.coupang.com/np/search?q={query}&channel=user"


def test_the_read_out_names_the_site_once() -> None:
    """첫 실사용 판(ec217c11): 「www.yes24.com, yes24.com 검색 · www.yes24.com, yes24.com 안에서만」 — 한 번만 보인다."""
    recipe = _recipe()
    assert recipe["_where"] == "yes24.com"
    text = read_out(recipe)
    assert "www.yes24.com, yes24.com" not in text and text.startswith("배운 것: yes24.com 검색")
