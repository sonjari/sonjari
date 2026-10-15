"""확정(promote)은 되돌릴 수 있어야 한다.

## 왜 이게 필요했나 (2026-08-15)

`InverseSpec` 의 문서는 이렇게 적혀 있다:

    자율성은 더 대담해져서 얻는 게 아니라 되돌릴 수 있어서 얻는 것이다.
    ... 역동작을 아무도 안 짜놨을 뿐이다.

재 보니 그 말이 그대로 사실이었다 — **쓰기 도구 22개 중 되돌리기 명세가 달린 것이
2개**(캘린더 생성=자동, 블로그 임시저장=수동)뿐이고, **자동으로 되돌아가는 것은
캘린더 하나**였다. `undo_action` 실적 0회의 진짜 이유는 "안 써서"가 아니라
**되돌릴 것이 없어서**였다.

확정은 되돌리기 재료가 이미 다 있었다 — `promote_draft` 가 덮어쓸 때 예전 것을
`drafts/{site}.replaced-{시각}.json` 으로 남긴다. 그걸 쓰지 않고 있었을 뿐이다.

## 무엇을 지키나

되돌리기가 **일을 없애 버리면 안 된다.** 자비스가 만든 절차는 남기고, "앞으로
실제로 쓰인다"는 것만 취소한다. 초안 폴더는 `load_recipes` 의 glob 에 안 잡히므로
그 자리가 곧 '안 쓰임'이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.site_recipes import DRAFTS_DIRNAME, SiteRecipeTools


def _recipe(name: str, url: str) -> dict:
    return {
        "name": name,
        "description": "시험용",
        "hosts": ["example.test"],
        "urls": {"home": url},
        "actions": {"open_home": {"risk": "L0", "steps": [{"do": "open", "url": "home"}]}},
    }


def _recipes(tmp_path: Path) -> SiteRecipeTools:
    directory = tmp_path / "recipes"
    directory.mkdir(parents=True, exist_ok=True)
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "out",
        site_recipe_dir=directory,
    )
    # 되돌리기는 파일만 만진다 — 브라우저가 필요 없다.
    return SiteRecipeTools(config, worker=None)


def _write_draft(recipes: SiteRecipeTools, site: str, url: str) -> Path:
    drafts = recipes.config.site_recipe_dir / DRAFTS_DIRNAME
    drafts.mkdir(parents=True, exist_ok=True)
    path = drafts / f"{site}.json"
    path.write_text(json.dumps(_recipe(site, url), ensure_ascii=False), encoding="utf-8")
    return path


def test_a_brand_new_recipe_goes_back_to_being_a_draft(tmp_path: Path) -> None:
    """새로 확정한 것은 되돌리면 **초안으로 돌아간다** — 지워지는 게 아니다."""
    recipes = _recipes(tmp_path)
    _write_draft(recipes, "shopfoo", "https://example.test/a")

    result = recipes.promote_draft({"site": "shopfoo"})
    assert "shopfoo" in recipes.recipes, "확정이 안 됐다"

    handle = recipes._promote_handle(result)
    assert handle is not None
    undone = recipes._undo_promote(handle)

    assert undone["restored"] == "removed"
    assert undone["active"] is False, "되돌렸는데 아직 쓰이고 있다"
    assert "shopfoo" not in recipes.recipes
    # ★ 일이 사라지면 안 된다.
    draft = Path(undone["draft_path"])
    assert draft.exists(), "되돌리기가 절차를 통째로 없앴다"
    assert json.loads(draft.read_text(encoding="utf-8"))["urls"]["home"] == "https://example.test/a"


def test_an_overwrite_puts_the_previous_version_back(tmp_path: Path) -> None:
    """덮어쓴 것은 되돌리면 **예전 확정본**이 그 자리로 돌아온다."""
    recipes = _recipes(tmp_path)
    _write_draft(recipes, "shopfoo", "https://example.test/old")
    recipes.promote_draft({"site": "shopfoo"})

    _write_draft(recipes, "shopfoo", "https://example.test/new")
    result = recipes.promote_draft({"site": "shopfoo"})
    assert result["replaced_backup"], "덮어쓰기인데 백업을 안 남겼다"

    undone = recipes._undo_promote(recipes._promote_handle(result))

    assert undone["restored"] == "previous"
    assert undone["active"] is True, "예전 확정본이 살아 있어야 한다"
    live = json.loads((recipes.config.site_recipe_dir / "shopfoo.json").read_text(encoding="utf-8"))
    assert live["urls"]["home"] == "https://example.test/old"
    # 물린 새 버전은 초안으로 남는다.
    draft = json.loads(Path(undone["draft_path"]).read_text(encoding="utf-8"))
    assert draft["urls"]["home"] == "https://example.test/new"


def test_undoing_twice_is_refused_rather_than_pretending(tmp_path: Path) -> None:
    """게이트웨이가 두 번 못 부르게 막지만(claim), 역동작 자체도 거짓말하면 안 된다."""
    recipes = _recipes(tmp_path)
    _write_draft(recipes, "shopfoo", "https://example.test/a")
    handle = recipes._promote_handle(recipes.promote_draft({"site": "shopfoo"}))
    recipes._undo_promote(handle)

    with pytest.raises(Exception):
        recipes._undo_promote(handle)


def test_the_gateway_actually_offers_the_undo(tmp_path: Path) -> None:
    """★ 핸들러가 되는 것과 **도구로 불렀을 때 되돌리기가 생기는 것**은 다른 얘기다.

    명세를 짜 놓고 `ToolSpec(inverse=...)` 에 안 물리면 아무 일도 안 일어난다.
    오늘만 같은 모양을 두 번 봤다(도구 결과 첨부가 result 밖에 있어 사라진 것,
    새 도구가 눈금 분류표에 없어 안 세어진 것). 그래서 끝단으로 건다.
    """
    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.tool_gateway import ToolGateway

    recipes = _recipes(tmp_path)
    gateway = ToolGateway(JobStore(tmp_path / "j.db"), EventBus())
    recipes.register(gateway)
    _write_draft(recipes, "shopfoo", "https://example.test/a")

    # 읽기만 하는 절차라 L1 — 승인 없이 그냥 확정된다.
    done = gateway.execute("site_promote_draft", {"site": "shopfoo"}, job_id="job-1")
    assert done.ok, done.error
    assert "shopfoo" in recipes.recipes

    offers = gateway.store.list_undo_offers()
    assert offers, "확정했는데 되돌리기가 안 생겼다 — inverse 가 ToolSpec 에 안 물렸다"
    assert offers[0]["tool"] == "site_promote_draft"
    assert offers[0]["automatic"] is True, "자동으로 되돌아가야 한다(수동 안내가 아니다)"

    undone = gateway.undo(str(offers[0]["undo_id"]))
    assert undone["ok"], undone
    assert "shopfoo" not in recipes.recipes, "되돌렸는데 아직 쓰이고 있다"
    # 두 번은 안 된다 — 되돌리기가 스스로 새로운 사고가 되면 안 된다.
    assert gateway.undo(str(offers[0]["undo_id"]))["ok"] is False


def test_no_handle_means_no_button(tmp_path: Path) -> None:
    """무엇을 되돌릴지 모르면 되돌리기를 **안 내준다.**

    눌렀는데 아무 일도 안 일어나는 버튼이 제일 나쁘다 — 캘린더가 쓰는 규율과 같다.
    """
    recipes = _recipes(tmp_path)
    assert recipes._promote_handle({"action": "site_promote_draft"}) is None
    assert recipes._promote_handle({"site": "shopfoo"}) is None
