"""자비스가 레시피를 **쓴다**. 단, 지금 화면에 실제로 있는 것만.

레시피는 자율이 저절로 늘어나는 유일한 축이다 — 사람이 한 번 뚫으면 다음부터
안 막힌다. 그런데 도구가 `site_list`(보기)와 `site_run`(실행) 둘뿐이라, 자비스가
크몽에서 세 번 막혀 "레시피 만들자고 말씀해 주세요"라고 해 놓고 **정작 자기가 만들
손이 없었다.**

막힌 그 순간의 자비스는 이미 진짜 화면을 보고 있다(`browser_probe_frames`,
`browser_snapshot`). 셀렉터를 지어낼 필요가 없는 자리다. 없던 것은 관찰한 것을
JSON 으로 옮겨 적는 마지막 한 걸음뿐이었다.

## 그래서 무엇을 열고 무엇을 안 여는가

    쓴다        자비스가. 단 **지금 화면에서 걸리는 셀렉터만**
    확정한다    사람이. L2 화면 승인으로 recipes/ 에 올라간다

확정을 사람에게 남기는 이유는 레시피가 **실행될 때 감시를 덜 받기** 때문이다 —
`site_run` 한 번에 절차가 통째로 돈다. 그럴듯한데 엉뚱한 것을 누르는 레시피는
레시피가 없는 것보다 나쁘다.

아래 시험의 절반은 **거부되는 쪽**을 지킨다. 라이브 확인이 무력해지면 이 기능은
"자비스가 셀렉터를 지어낸다"와 같은 말이 된다.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.site_recipes import DRAFTS_DIRNAME, RecipeError, SiteRecipeTools
from alture_jarvis.tool_gateway import ToolGateway


class FakePage:
    """화면에 '실제로 있는' 셀렉터 목록. 그 밖의 것은 못 찾는다."""

    def __init__(self, present: set[str]) -> None:
        self.present = present
        self.asked: list[str] = []

    def execute(self, action: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if action != "browser_find_selector":
            return {}
        selectors = list((arguments or {}).get("selectors") or [])
        self.asked.extend(selectors)
        for selector in selectors:
            if selector in self.present:
                return {"ref": f"ref_{selector}"}
        # 실제 브라우저도 못 찾으면 예외를 던지고, 시도한 셀렉터를 전부 알려준다.
        raise RuntimeError(f"selector_not_found: {selectors}")


def _tools(present: set[str]) -> tuple[SiteRecipeTools, FakePage, Path]:
    root = Path(tempfile.mkdtemp())
    config = JarvisConfig(
        runtime_root=root,
        data_dir=root / "data",
        output_dir=root / "outputs",
        site_recipe_dir=root / "recipes",
    )
    config.site_recipe_dir.mkdir(parents=True, exist_ok=True)
    page = FakePage(present)
    return SiteRecipeTools(config, page), page, config.site_recipe_dir


_LIVE = {".gig-title", ".gig-body", ".btn-apply"}


def _draft_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "site": "kmong",
        "hosts": ["kmong.com"],
        "action": "read_posting",
        "urls": {"posting": "https://kmong.com/gig/{gig_id}"},
        "targets": {"title": [".gig-title"], "body": [".gig-body"]},
        "steps": [
            {"do": "open", "url_key": "posting"},
            {"do": "find", "target": "title"},
            {"do": "find", "target": "body"},
        ],
    }
    args.update(overrides)
    return args


# ── 쓴다 ─────────────────────────────────────────────────────────────────────
def test_it_writes_a_draft_from_what_is_actually_on_screen() -> None:
    tools, page, recipes = _tools(_LIVE)

    result = tools.draft(_draft_args())

    assert result["status"] == "draft"
    assert result["confirmed_live"] == {"title": ".gig-title", "body": ".gig-body"}
    assert page.asked, "화면에 물어보지도 않고 썼다면 라이브 확인이 없는 것이다"
    path = recipes / DRAFTS_DIRNAME / "kmong.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["_drafted_by"] == "jarvis"


def test_a_draft_does_not_become_runnable_on_its_own() -> None:
    """★ 초안과 확정을 가르는 것은 폴더 하나다. site_run 이 집으면 안 된다."""
    tools, _, _ = _tools(_LIVE)
    tools.draft(_draft_args())

    assert "kmong" not in tools.recipes
    with pytest.raises(RecipeError, match="모르는 사이트"):
        tools.run({"site": "kmong", "action": "read_posting"})


def test_the_confirmed_selector_goes_first() -> None:
    """지금 걸리는 것이 제일 정확하다. 나머지는 구조가 바뀌었을 때의 대비책."""
    tools, _, recipes = _tools(_LIVE)
    tools.draft(
        _draft_args(targets={"title": [".se-title-does-not-exist", ".gig-title"], "body": [".gig-body"]})
    )
    data = json.loads((recipes / DRAFTS_DIRNAME / "kmong.json").read_text(encoding="utf-8"))
    assert data["targets"]["title"][0] == ".gig-title"
    assert ".se-title-does-not-exist" in data["targets"]["title"], "대비책은 버리지 않는다"


# ── 거부한다 (여기가 절반이다) ───────────────────────────────────────────────
def test_an_invented_selector_is_refused() -> None:
    """★ 이 검사가 없으면 '자비스가 레시피를 쓴다'는 곧 '셀렉터를 지어낸다'가 된다.

    추측한 셀렉터가 이틀을 태웠고, 그래서 프롬프트에 지어내지 말라고 못을 박아 뒀다.
    그 못을 도구로 뽑아 주면 안 된다.
    """
    tools, _, recipes = _tools(_LIVE)

    with pytest.raises(RecipeError, match="지금 화면에서 확인되지 않는"):
        tools.draft(_draft_args(targets={"title": [".se-main-container .se-text"], "body": [".gig-body"]}))

    assert not (recipes / DRAFTS_DIRNAME).exists() or not list(
        (recipes / DRAFTS_DIRNAME).glob("*.json")
    ), "거부했으면 파일도 남으면 안 된다"


def test_a_mutating_click_without_evidence_is_refused() -> None:
    """확정본과 **똑같은 규칙**으로 먼저 통과시킨다. 승인 화면까지 가서 걸리면 늦다."""
    tools, _, _ = _tools(_LIVE)

    with pytest.raises(RecipeError, match="expect가 필요하다"):
        tools.draft(
            _draft_args(
                targets={"apply": [".btn-apply"]},
                steps=[{"do": "click", "target": "apply"}],
            )
        )


def test_a_step_pointing_at_an_unknown_target_is_refused() -> None:
    tools, _, _ = _tools(_LIVE)
    with pytest.raises(RecipeError, match="targets 에 없다"):
        tools.draft(_draft_args(steps=[{"do": "find", "target": "nowhere"}]))


def test_a_recipe_with_no_hosts_is_refused() -> None:
    """어디로 갈 수 있는지가 곧 안전선이다."""
    tools, _, _ = _tools(_LIVE)
    with pytest.raises(RecipeError, match="hosts"):
        tools.draft(_draft_args(hosts=[]))


# ── 확정은 사람이 ────────────────────────────────────────────────────────────
def test_promoting_makes_it_runnable() -> None:
    tools, _, recipes = _tools(_LIVE)
    tools.draft(_draft_args())

    result = tools.promote_draft({"site": "kmong"})

    assert (recipes / "kmong.json").exists()
    assert not (recipes / DRAFTS_DIRNAME / "kmong.json").exists(), "확정됐으면 초안은 없어져야 한다"
    assert "kmong" in tools.recipes, "재기동 없이 바로 쓸 수 있어야 한다"
    assert result["actions"] == ["read_posting"]


def test_replacing_an_existing_recipe_keeps_the_old_one() -> None:
    """되돌릴 수 없는 일을 만들지 않는다 — 이 저장소의 규칙 그대로."""
    tools, _, recipes = _tools(_LIVE)
    (recipes / "kmong.json").write_text(
        json.dumps(
            {
                "name": "kmong",
                "hosts": ["kmong.com"],
                "targets": {"old": [".old"]},
                "actions": {"old_action": {"steps": [{"do": "find", "target": "old"}]}},
            }
        ),
        encoding="utf-8",
    )
    tools.recipes = {}
    tools.draft(_draft_args())

    result = tools.promote_draft({"site": "kmong"})

    assert result["replaced_backup"], "덮어썼는데 예전 것이 안 남았다"
    kept = json.loads(Path(result["replaced_backup"]).read_text(encoding="utf-8"))
    assert "old_action" in kept["actions"]


def test_promoting_something_that_was_never_drafted_fails() -> None:
    tools, _, _ = _tools(_LIVE)
    with pytest.raises(RecipeError, match="초안이 없다"):
        tools.promote_draft({"site": "kmong"})


# ── 등급 ─────────────────────────────────────────────────────────────────────
def test_writing_is_cheap_and_confirming_is_not() -> None:
    """초안 쓰기가 L1 인 것이 이 설계의 핵심이다.

    파일 하나 쓰는 일이고 그 파일은 아직 아무것도 실행하지 않는다. 실제로 쓰이게
    만드는 것만 사람 앞에 세운다 — 매번 물어보면 레시피는 영영 안 쌓인다.
    """
    tools, _, _ = _tools(_LIVE)
    store = JobStore(Path(tempfile.mkdtemp()) / "jobs.db")
    gateway = ToolGateway(store, EventBus())
    tools.register(gateway)

    levels = {
        str(spec["name"]): spec["risk_level"]
        for spec in gateway.list_tools()
        if spec["name"] in tools.names
    }
    assert levels["site_review_draft"] == RiskLevel.L0.label()
    assert levels["site_draft_recipe"] == RiskLevel.L1.label()
    # 확정의 바닥은 L1 이고, 바꾸는 초안이면 `_promote_risk` 가 L2 로 올린다.
    # 바닥이 곧 최소 보장이라 아래 시험들이 그 위를 지킨다.
    assert levels["site_promote_draft"] == RiskLevel.L1.label()


def test_review_shows_what_would_be_replaced() -> None:
    """사람이 승인하기 전에 무엇이 바뀌는지 봐야 한다."""
    tools, _, _ = _tools(_LIVE)
    tools.draft(_draft_args())

    review = tools.review_draft({"site": "kmong"})

    assert review["confirmed_live"]["title"] == ".gig-title"
    assert review["replaces_existing"] is False
    assert review["recipe"]["actions"]["read_posting"]["steps"]


# ── 읽기만 하는 레시피는 사람을 안 부른다 (2026-08-10) ───────────────────────
#
# 확정을 사람에게 맡긴 이유는 레시피가 **실행될 때 감시를 덜 받기** 때문이다.
# 그런데 `open`·`find`·`verify` 뿐인 절차는 아무것도 바꾸지 않는다 — 되돌릴 것이
# 없으면 물어볼 이유도 없다. 조사 레시피는 자비스가 혼자 쌓고, 사람 승인은
# **누르고 채우는 것**에만 남긴다.
#
# 아래 시험의 대부분은 이번에도 **거부되는 쪽**이다. 자동 확정이 새는 순간
# "레시피는 사람이 확정한다"는 문장은 장식이 된다.
def _gateway(tools: SiteRecipeTools) -> ToolGateway:
    gateway = ToolGateway(JobStore(Path(tempfile.mkdtemp()) / "jobs.db"), EventBus())
    tools.register(gateway)
    return gateway


_CLICKS = {
    "targets": {"apply": [".btn-apply"]},
    "steps": [{"do": "click", "target": "apply", "expect": {"text": "지원 완료"}}],
}


def test_a_read_only_draft_is_confirmed_without_asking() -> None:
    """열려야 할 것이 열린다 — 이것 때문에 레시피가 1개에서 안 늘고 있었다."""
    tools, _, recipes = _tools(_LIVE)
    tools.draft(_draft_args())

    result = _gateway(tools).execute("site_promote_draft", {"site": "kmong"})

    assert result.ok, f"읽기만 하는 절차인데 막혔다: {result.status}"
    assert (recipes / "kmong.json").exists()
    assert "kmong" in tools.recipes


def test_a_draft_that_clicks_still_stops_for_approval() -> None:
    """★ 막혀야 할 것은 그대로 막힌다."""
    tools, _, recipes = _tools(_LIVE)
    tools.draft(_draft_args(**_CLICKS))

    result = _gateway(tools).execute("site_promote_draft", {"site": "kmong"})

    assert result.status == "approval_required"
    assert result.risk_level == RiskLevel.L2.label()
    assert not (recipes / "kmong.json").exists(), "승인 전에 올라가면 안 된다"


def test_a_draft_that_calls_itself_harmless_is_not_believed() -> None:
    """모델이 스스로 등급을 적는다. 그 말이 아니라 **걸음**을 본다.

    인자로 오는 주장을 믿으면 그게 곧 승인 우회로다 — `_approved` 가 그렇게 뚫렸다.
    """
    tools, _, _ = _tools(_LIVE)
    tools.draft(_draft_args(risk="L0", **_CLICKS))

    result = _gateway(tools).execute("site_promote_draft", {"site": "kmong"})

    assert result.status == "approval_required"


def test_declaring_l2_raises_a_read_only_draft() -> None:
    """반대 방향도 지킨다 — 스스로 L2 라 적었으면 걸음이 얌전해도 사람이 본다."""
    tools, _, _ = _tools(_LIVE)
    tools.draft(_draft_args(risk="L2"))

    assert _gateway(tools).execute("site_promote_draft", {"site": "kmong"}).status == (
        "approval_required"
    )


def test_dismiss_does_not_count_as_reading() -> None:
    """대화상자를 거절하는 것도 화면에 대고 하는 선택이다("저장하시겠습니까?"에 아니오)."""
    tools, _, _ = _tools(_LIVE)
    tools.draft(
        _draft_args(steps=[{"do": "open", "url_key": "posting"}, {"do": "dismiss", "rounds": 2}])
    )

    assert _gateway(tools).execute("site_promote_draft", {"site": "kmong"}).status == (
        "approval_required"
    )


def test_an_unreadable_draft_asks_a_human() -> None:
    """판단이 안 서면 사람이 본다. 모르는 것을 안전하다고 읽지 않는다."""
    tools, _, recipes = _tools(_LIVE)
    tools.draft(_draft_args())
    (recipes / DRAFTS_DIRNAME / "kmong.json").write_text("{망가진 JSON", encoding="utf-8")

    assert _gateway(tools).execute("site_promote_draft", {"site": "kmong"}).status == (
        "approval_required"
    )


def test_the_draft_says_up_front_whether_it_will_need_approval() -> None:
    """모델이 "승인 받아야 하나"를 짐작하지 않도록 초안 쓸 때 미리 알려 준다."""
    tools, _, _ = _tools(_LIVE)

    read_only = tools.draft(_draft_args())
    assert read_only["read_only"] is True
    assert not read_only["needs_approval_because"]
    assert "승인이 필요 없다" in read_only["instruction"]

    tools2, _, _ = _tools(_LIVE)
    mutating = tools2.draft(_draft_args(**_CLICKS))
    assert mutating["read_only"] is False
    assert "click" in mutating["needs_approval_because"]


# ── 레시피가 스스로 적어 둔 등급을 아무도 안 읽고 있었다 (2026-08-10) ─────────
def test_a_recipe_action_declared_l2_actually_stops() -> None:
    """`SiteRecipe.risk_of` 는 정의만 돼 있고 **부르는 곳이 한 군데도 없었다.**

    그래서 `"risk": "L2"` 라고 적어 둔 절차가 승인 없이 그냥 돌았다(naver_blog 의
    임시저장이 실제로 그 상태였다). 오늘 고친 넷과 같은 병이다 — 만들어 놓고
    부르지 않는 것.
    """
    tools, _, recipes = _tools(_LIVE)
    (recipes / "kmong.json").write_text(
        json.dumps(
            {
                "name": "kmong",
                "hosts": ["kmong.com"],
                "targets": {"apply": [".btn-apply"]},
                "actions": {
                    "apply": {
                        "risk": "L2",
                        "steps": [
                            {"do": "click", "target": "apply", "expect": {"text": "지원 완료"}}
                        ],
                    },
                    "read": {"risk": "L1", "steps": [{"do": "find", "target": "apply"}]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tools.recipes = {}
    tools.recipes.update(__import__("alture_jarvis.site_recipes", fromlist=["x"]).load_recipes(recipes))
    gateway = _gateway(tools)

    stopped = gateway.execute("site_run", {"site": "kmong", "action": "apply"})
    assert stopped.status == "approval_required", "L2 라고 적힌 절차가 그냥 돌았다"

    ran = gateway.execute("site_run", {"site": "kmong", "action": "read"})
    assert ran.ok, "L1 절차까지 막으면 레시피를 쓸 이유가 없어진다"


def test_dynamic_risk_can_only_raise() -> None:
    """★ 게이트웨이의 불변식. 내릴 수 있게 만드는 순간 이것이 승인 우회로가 된다."""
    from alture_jarvis.tool_gateway import ToolSpec

    gateway = ToolGateway(JobStore(Path(tempfile.mkdtemp()) / "jobs.db"), EventBus())
    gateway.register(
        ToolSpec(
            name="pretend_safe",
            description="",
            risk_level=RiskLevel.L2,
            handler=lambda _a: {"ok": True},
            dynamic_risk=lambda _a: RiskLevel.L0,
        )
    )

    assert gateway.execute("pretend_safe", {}).status == "approval_required"


def test_a_broken_risk_judgment_fails_closed() -> None:
    from alture_jarvis.tool_gateway import ToolSpec

    def explodes(_arguments: dict[str, Any]) -> RiskLevel:
        raise RuntimeError("판단 실패")

    gateway = ToolGateway(JobStore(Path(tempfile.mkdtemp()) / "jobs.db"), EventBus())
    gateway.register(
        ToolSpec(
            name="unsure",
            description="",
            risk_level=RiskLevel.L0,
            handler=lambda _a: {"ok": True},
            dynamic_risk=explodes,
        )
    )

    assert gateway.execute("unsure", {}).status == "approval_required"
