"""절차는 **무엇으로 되돌리는지**를 스스로 적는다.

## 왜 이렇게 가나 (2026-08-15 설계)

"신청서를 냈다"를 범용으로 되돌리는 방법은 없다 — 취소 경로가 사이트마다 다르다.
그런데 그 사이트별 지식이 살 집은 이미 있다. **레시피**다. 그리고 자비스는 레시피를
스스로 초안 쓴다. 그러니 조사(L2)가 범용인 것과 같은 방식으로 쓰기도 범용이 된다 —
사이트가 느는 것이 곧 레시피가 느는 것이다.

    scrap    risk L2  undo: unscrap
    unscrap  risk L1

## 이 단계에서 **안** 하는 것

**등급을 안 내린다.** 레시피가 "나 되돌릴 수 있으니 승인 빼줘"라고 스스로 적을 수
있으면 자비스가 자기 승인 등급을 쓰는 것이고, `_approved` 인자로 뚫려 있던 구멍과
같은 모양이 된다. 강등은 **역동작이 실제로 성공한 기록**(레시피 파일이 아닌 곳)이
있을 때만 한다 — 다음 단계다. 여기서는 그 사실을 시험으로 못 박는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.models import RiskLevel
from alture_jarvis.site_recipes import RecipeError, SiteRecipe, SiteRecipeTools


def _recipe(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "demo",
        "hosts": ["example.test"],
        "urls": {"item": "https://example.test/job/{job_id}"},
        "targets": {"scrap_button": ["button.scrap"], "unscrap_button": ["button.unscrap"]},
        "actions": {
            "scrap": {
                "risk": "L2",
                "undo": "unscrap",
                "steps": [
                    {"do": "open", "url_key": "item"},
                    {"do": "click", "target": "scrap_button", "expect": {"value": "스크랩됨"}},
                ],
            },
            "unscrap": {
                "risk": "L1",
                "steps": [
                    {"do": "open", "url_key": "item"},
                    {"do": "click", "target": "unscrap_button", "expect": {"value": "스크랩"}},
                ],
            },
        },
    }
    data.update(overrides)
    return data


def test_an_action_can_name_what_undoes_it(tmp_path: Path) -> None:
    recipe = SiteRecipe(tmp_path / "demo.json", _recipe())
    assert recipe.undo_action_of("scrap") == "unscrap"
    assert recipe.undo_action_of("unscrap") == ""


def test_pointing_at_a_missing_action_is_refused_when_it_loads(tmp_path: Path) -> None:
    """적재할 때 걸러야 한다 — 실행 중에 알면 이미 스크랩은 되어 있다."""
    data = _recipe()
    data["actions"]["scrap"]["undo"] = "nope"
    with pytest.raises(RecipeError, match="nope"):
        SiteRecipe(tmp_path / "demo.json", data)


def test_undoing_itself_is_refused(tmp_path: Path) -> None:
    data = _recipe()
    data["actions"]["scrap"]["undo"] = "scrap"
    with pytest.raises(RecipeError, match="자기 자신"):
        SiteRecipe(tmp_path / "demo.json", data)


def test_a_chain_of_undos_is_refused(tmp_path: Path) -> None:
    """되돌리기의 되돌리기는 되돌리기가 아니라 **다시 하기**다."""
    data = _recipe()
    data["actions"]["unscrap"]["undo"] = "scrap"
    with pytest.raises(RecipeError, match="또 되돌리기"):
        SiteRecipe(tmp_path / "demo.json", data)


# ── 실행이 남기는 손잡이 ──────────────────────────────────────────────────────


class _Worker:
    """`site_run` 이 부르는 것만 흉내 낸다 — 기존 `test_site_recipes.FakeWorker` 와 같은 모양.

    화면은 늘 기대대로라고 답한다. 여기서 재는 것은 "무엇을 불렀나"이지
    "화면이 어땠나"가 아니다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, action: str, arguments: dict | None = None) -> dict:
        arguments = dict(arguments or {})
        self.calls.append((action, arguments))
        if action == "browser_open":
            return {"url": arguments.get("url", "")}
        if action == "browser_find_selector":
            return {"ref": "j901", "selector": arguments["selectors"][0], "frame": "main"}
        if action in {"browser_click", "browser_press"}:
            return {
                "verified": True,
                "verification": {"status": "verified", "evidence": "text:스크랩됨"},
            }
        return {}

    # 레시피는 **신뢰 문**으로 들어온다. 두 문이 하는 일이 달라지면 이 가짜가
    # 진짜를 대변하지 못하므로 같은 자리로 보낸다.
    def execute_trusted(self, action: str, arguments: dict | None = None) -> dict:
        return self.execute(action, arguments)


def _tools(tmp_path: Path) -> SiteRecipeTools:
    directory = tmp_path / "recipes"
    directory.mkdir(parents=True, exist_ok=True)
    import json

    (directory / "demo.json").write_text(
        json.dumps(_recipe(), ensure_ascii=False), encoding="utf-8"
    )
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "out",
        site_recipe_dir=directory,
    )
    return SiteRecipeTools(config, _Worker())


def test_the_handle_carries_only_what_the_undo_needs(tmp_path: Path) -> None:
    """★ 원래 params 를 통째로 실으면 **로그인 절차의 비밀번호까지 장부에 남는다.**

    되돌리기가 쓰는 것은 그 역동작의 자리표시자뿐이다.
    """
    tools = _tools(tmp_path)
    result = tools.run({"site": "demo", "action": "scrap", "params": {"job_id": "42", "password": "비밀"}})

    assert result["status"] == "done"
    handle = tools._run_handle(result)
    assert handle == {
        "site": "demo",
        "action": "unscrap",
        "params": {"job_id": "42"},
        # 실적은 **원래 절차**(scrap)에 쌓인다 — 되돌린 절차(unscrap)가 아니라.
        # 이게 뒤집히면 엉뚱한 쪽의 승인이 빠진다.
        "for_action": "scrap",
    }
    assert "password" not in handle["params"]


def test_an_unverified_run_leaves_no_handle(tmp_path: Path) -> None:
    """증거를 못 읽어 멈춘 실행은 **어디까지 갔는지 모른다.**

    모르는 것을 되돌리겠다고 나서면 그게 새로운 사고다.
    """
    tools = _tools(tmp_path)
    assert tools._run_handle({"site": "demo", "action": "scrap", "status": "unverified"}) is None


def test_an_action_without_an_undo_leaves_no_handle(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    result = tools.run({"site": "demo", "action": "unscrap", "params": {"job_id": "42"}})
    assert "undo_action" not in result
    assert tools._run_handle(result) is None


def test_the_undo_runs_the_named_action(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    result = tools.run({"site": "demo", "action": "scrap", "params": {"job_id": "42"}})
    tools.worker.calls.clear()

    undone = tools._undo_run(tools._run_handle(result))

    assert undone["action"] == "undo_site_run"
    assert undone["status"] == "done"
    opened = [args.get("url") for name, args in tools.worker.calls if name == "browser_open"]
    assert "https://example.test/job/42" in opened, tools.worker.calls


def test_declaring_an_undo_does_not_lower_the_risk(tmp_path: Path) -> None:
    """★ 이 단계의 핵심 안전선.

    레시피가 스스로 승인을 뺄 수 있으면 자비스가 자기 등급을 쓰는 것이다.
    강등은 **실적**으로만 한다(다음 단계).
    """
    tools = _tools(tmp_path)
    assert tools._run_risk({"site": "demo", "action": "scrap"}) == RiskLevel.L2


# ── 2단계: 강등은 **주장이 아니라 실적**으로만 ────────────────────────────────


def _wired(tmp_path: Path):
    """게이트웨이에 실제로 등록해서 실적 장부까지 붙인 상태."""
    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.tool_gateway import ToolGateway

    tools = _tools(tmp_path)
    gateway = ToolGateway(JobStore(tmp_path / "j.db"), EventBus())
    tools.register(gateway)
    return tools, gateway


def test_it_stays_L2_until_the_undo_has_actually_run(tmp_path: Path) -> None:
    """★ 이 시험이 이 단계의 전부다.

    레시피가 `undo` 를 적었다는 것만으로는 아무것도 안 바뀐다. 자비스가 레시피를
    스스로 쓰므로, 적은 말로 등급이 내려가면 자기 승인을 자기가 쓰는 것이다.
    """
    tools, _ = _wired(tmp_path)
    assert tools._run_risk({"site": "demo", "action": "scrap"}) == RiskLevel.L2


def test_once_the_undo_really_ran_the_approval_falls_away(tmp_path: Path) -> None:
    tools, _ = _wired(tmp_path)
    result = tools.run({"site": "demo", "action": "scrap", "params": {"job_id": "42"}})

    tools._undo_run(tools._run_handle(result))

    assert tools._run_risk({"site": "demo", "action": "scrap"}) == RiskLevel.L1


def test_it_never_falls_below_L1(tmp_path: Path) -> None:
    """실적이 있어도 바닥은 등록 등급이다 — `effective_risk` 가 max 를 쓴다."""
    tools, gateway = _wired(tmp_path)
    result = tools.run({"site": "demo", "action": "scrap", "params": {"job_id": "42"}})
    tools._undo_run(tools._run_handle(result))

    spec = gateway._tools["site_run"]
    assert spec.effective_risk({"site": "demo", "action": "scrap"}) == RiskLevel.L1


def test_changing_the_recipe_throws_the_proof_away(tmp_path: Path) -> None:
    """같은 이름으로 다른 것을 누르게 만드는 것이 제일 쉬운 우회로다."""
    import json as _json

    tools, _ = _wired(tmp_path)
    result = tools.run({"site": "demo", "action": "scrap", "params": {"job_id": "42"}})
    tools._undo_run(tools._run_handle(result))
    assert tools._run_risk({"site": "demo", "action": "scrap"}) == RiskLevel.L1

    # 단계는 그대로 두고 **셀렉터만** 바꾼다.
    data = _recipe()
    data["targets"]["scrap_button"] = ["button.pay-now"]
    (tools.config.site_recipe_dir / "demo.json").write_text(
        _json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    tools.recipes = __import__(
        "alture_jarvis.site_recipes", fromlist=["load_recipes"]
    ).load_recipes(tools.config.site_recipe_dir)

    assert tools._run_risk({"site": "demo", "action": "scrap"}) == RiskLevel.L2


def test_a_failed_undo_takes_the_trust_back(tmp_path: Path) -> None:
    """되돌아갈 줄 알았는데 안 되는 것이, 못 되돌린다고 알고 있는 것보다 나쁘다."""
    tools, _ = _wired(tmp_path)
    result = tools.run({"site": "demo", "action": "scrap", "params": {"job_id": "42"}})
    tools._undo_run(tools._run_handle(result))
    assert tools._run_risk({"site": "demo", "action": "scrap"}) == RiskLevel.L1

    # 다음 되돌리기가 증거를 못 읽는다.
    def _blind(action, arguments=None):
        out = _Worker.execute(tools.worker, action, arguments)
        if action in {"browser_click", "browser_press"}:
            return {"verified": False, "verification": {"status": "unknown", "evidence": ""}}
        return out

    tools.worker.execute = _blind  # type: ignore[method-assign]
    tools.worker.execute_trusted = _blind  # type: ignore[method-assign]

    with pytest.raises(RecipeError):
        tools._undo_run(tools._run_handle(result))

    assert tools._run_risk({"site": "demo", "action": "scrap"}) == RiskLevel.L2
