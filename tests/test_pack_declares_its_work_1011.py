"""스킬팩은 그 일이 **어떤 일인지** 적어 올 수 있다 — 「웹을 보고 와서 정리하는 일」 (2026-10-11).

16GB 조건(창 49,152)에서 가격 조사 스킬팩이 흔들린 까닭 가운데 하나: 이 일이 조사 일로 안 잡혔다. 「조사 일인가」는 사람의
말에서 뽑은 요구로 가리는데(`tool_roster._is_web_research_job`), 「○○ 가격 조사 + 엑셀로 정리해 줘」에서는 「파일 만들기」
하나만 뽑힌다. 그래서

  - 도구 목록이 조사 일의 79개가 아니라 123개로 갔다 — 첫 호출의 프롬프트 28,205토큰(조사 일로 잡히면 21,476토큰).
  - **파일을 쓰기 전에 숫자를 대조하는 문**도 꺼져 있었다(그 문은 조사 일에만 선다).

시키는 말에 「3개를 직접 열어 읽고」를 넣어 조사 일로 잡히게 해 봤다(판 092a5347). 목록은 줄었지만, 「3개 읽기」는 어느 페이지든
3개면 채워져서 엉뚱한 페이지까지 세었고, 그 뒤 하네스가 「읽기는 끝났다」로 넘어가며 세 번째 가게를 여는 것을 막았다.

그래서 요구를 보태지 않고 **일의 갈래만** 적게 한다. 낱말(`triggers`) · 시키는 말(`asks`)에 이은 셋째 칸 `work` 다.
팩을 쓴 사람이 적는 것이라 미리 맞히는 것이 아니다. 받는 값은 지금 `web` 하나다.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.packs import PackRegistry
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.skills import SkillLibrary
from alture_jarvis.tool_roster import _is_web_research_job, _route_scoped_tool_definitions

REPO = Path(__file__).resolve().parents[1]
SKILL = """---
name: price-watch
description: 정해 둔 가게들에서 같은 상품의 가격을 모아 엑셀로 정리한다
---
# 가격 조사

1. 가게 목록의 주소를 차례로 연다.
"""
WORDS = {"price-watch": ["가격 조사", "가격조사"]}
ASK = "말한 상품을 스킬에 적힌 가게마다 찾아 판매 가격과 배송비를 엑셀 파일로 정리해 줘"
WORK = {"price-watch": "web"}
SHORT = "로지텍 MX Master 3S 가격 조사"


def _drop(user_dir: Path, **overrides: Any) -> None:
    folder = user_dir / "price-watch-demo"
    folder.mkdir(parents=True)
    data: dict[str, Any] = {
        "id": "price-watch-demo", "name": "가격 조사 스킬팩", "version": "1.0.0", "kind": "content", "summary": "가게 가격 모으기",
        "skills": ["price-watch"], "triggers": WORDS, "asks": {"price-watch": ASK},
        "permissions": {"reads": [], "writes": [], "runs": [], "network": "손자리가 여는 페이지만"},
    }
    data.update(overrides)
    (folder / "pack.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (folder / "skills" / "price-watch").mkdir(parents=True)
    (folder / "skills" / "price-watch" / "SKILL.md").write_text(SKILL, encoding="utf-8")


def _registry(tmp_path: Path) -> PackRegistry:
    return PackRegistry(REPO / "packs", tmp_path / "data", user_dir=tmp_path / "skillpacks")


class _Silent:
    def publish(self, *args: Any, **kwargs: Any) -> None: ...
    def add_audit(self, *args: Any, **kwargs: Any) -> None: ...


def _runtime(tmp_path: Path, *, enabled: bool = True, **overrides: Any) -> JarvisRuntime:
    _drop(tmp_path / "skillpacks", **overrides)
    registry = _registry(tmp_path)
    config = type("_S", (), {
        "skills_dir": REPO / "skills", "skills_max_chars": 12_000, "skills_body_max_chars": 12_000,
        "skills_fold_sections": False, "skills_route_enabled": False, "skills_guess_enabled": False, "skills_domains": (),
    })()
    holder = JarvisRuntime.__new__(JarvisRuntime)
    holder.config = config
    holder.packs = registry
    holder.skills = SkillLibrary(config, extra_dirs=registry.skill_dirs, pack_dirs=registry.user_skill_dirs)
    registry.on_change(holder.skills.reload)
    holder.events = _Silent()
    holder.store = _Silent()
    if enabled:
        registry.set_enabled("price-watch-demo", True)
    return holder


# --- 팩이 적어 온다 ---------------------------------------------------------------

def test_the_pack_says_what_kind_of_work_its_skill_is(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks", work=WORK)
    registry = _registry(tmp_path)
    assert registry.works() == {}, "꺼진 팩은 아무것도 정하지 않는다"

    registry.set_enabled("price-watch-demo", True)

    assert registry.works() == WORK
    assert registry.describe("price-watch-demo")["work"] == WORK, "화면이 켜기 전에 보여 줄 수 있어야 한다"


def test_a_pack_without_the_line_says_nothing(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks")
    registry = _registry(tmp_path)
    registry.set_enabled("price-watch-demo", True)

    assert registry.problems == [] and registry.works() == {}
    assert registry.describe("price-watch-demo")["work"] == {}


@pytest.mark.parametrize("work, why", [
    ({"someone-elses-skill": "web"}, "제 스킬이 아닌 것의 일을 정할 수 없다"),
    ({"price-watch": "code"}, "받는 갈래는 web 하나다 — 손을 넓히는 갈래는 받지 않는다"),
    ({"price-watch": ["web"]}, "글 한 낱말이어야 한다"),
    ("web", "「스킬 이름: 갈래」 꼴이어야 한다"),
])
def test_a_bad_line_keeps_the_pack_out_and_says_why(tmp_path: Path, work: Any, why: str) -> None:
    _drop(tmp_path / "skillpacks", work=work)
    registry = _registry(tmp_path)

    assert "price-watch-demo" not in registry.packs, why
    assert any("work" in problem for problem in registry.problems), why


def test_the_example_pack_we_hand_out_declares_it(tmp_path: Path) -> None:
    packs = PackRegistry(REPO / "packs", tmp_path / "data", user_dir=REPO / "docs" / "skillpacks").packs

    assert packs["price-watch-demo"].work == WORK


# --- 그 말에 붙을 때만 ------------------------------------------------------------

def test_the_declaration_follows_the_same_words_as_the_skill(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, work=WORK)

    assert runtime._pack_work(SHORT) == "web"
    assert runtime._pack_work(f"{SHORT}\n{ASK}") == "web", "시키는 말이 이미 붙은 글이어도 같다"
    assert runtime._pack_work("아무 말", asked="price-watch") == "web", "스킬을 짚어서 맡긴 판도 같다"
    assert runtime._pack_work("오늘 날씨 어때") == ""
    assert runtime._pack_work("랜딩 페이지 만들어줘") == "", "그 팩의 말이 아니면 아무것도 정하지 않는다"


def test_a_switched_off_pack_and_a_pack_without_the_line_declare_nothing(tmp_path: Path) -> None:
    assert _runtime(tmp_path / "a", enabled=False, work=WORK)._pack_work(SHORT) == ""
    assert _runtime(tmp_path / "b")._pack_work(SHORT) == ""
    assert JarvisRuntime.__new__(JarvisRuntime)._pack_work(SHORT) == ""


# --- 적어 온 것이 하는 일 ----------------------------------------------------------

def test_a_declared_job_is_a_go_and_see_job_even_when_the_request_only_asks_for_a_file() -> None:
    """이 고침의 까닭 그 자체 — 사람의 말에서는 「파일 만들기」만 뽑힌다."""
    text = f"{SHORT}\n{ASK}"
    found = plan.extract(text)
    assert {req.kind for req in found} == {"artifact"}

    assert _is_web_research_job(found, text) is False
    assert _is_web_research_job(found, text, declared=True) is True
    assert {req.kind for req in found} == {"artifact"}, "요구를 보태지 않는다 — 「3개 읽기」 같은 것이 생기면 다른 문이 닫힌다"


def test_a_job_that_has_to_run_or_verify_keeps_all_its_hands_whatever_the_pack_says() -> None:
    for kind in ("verify", "action"):
        assert _is_web_research_job([SimpleNamespace(kind=kind), SimpleNamespace(kind="artifact")], "", declared=True) is False


def test_without_a_declaration_nothing_changes() -> None:
    assert _is_web_research_job([SimpleNamespace(kind="site")], "") is True
    assert _is_web_research_job([SimpleNamespace(kind="artifact")], "") is False
    assert _is_web_research_job([], "", declared=False) is False


def test_the_go_and_see_list_keeps_the_hands_this_work_uses() -> None:
    def tool(name: str) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}

    every = [tool(name) for name in (
        "browser_open", "browser_site_search", "browser_extract", "site_list", "local_write_document", "local_edit_spreadsheet",
        "local_read_document", "camera_capture", "schedule_create", "career_strategy_lookup",
    )]
    kept = {item["function"]["name"] for item in _route_scoped_tool_definitions(every, web_only=True)}

    assert {"browser_open", "browser_site_search", "browser_extract", "site_list", "local_write_document",
            "local_edit_spreadsheet", "local_read_document"} <= kept
    assert not kept & {"camera_capture", "schedule_create", "career_strategy_lookup"}


# --- 길이 이어져 있는가 -----------------------------------------------------------

def test_the_job_reads_the_declaration_from_what_the_person_typed_and_hands_it_to_the_agent() -> None:
    source = inspect.getsource(JarvisRuntime._chat_job_inner)

    assert "self._pack_work(steer_plan or prompt" in source, "시키는 말과 같은 글로 가린다"
    assert source.index("pack_work = ") < source.index("pack_ask = "), "문장을 붙이기 전의 글로 가린다"
    assert "declared_work=pack_work" in source, "에이전트에게 넘긴다"
    assert '"skill_pack_work_declared"' in source, "적용했으면 기록에 남긴다"
    assert "if handoff" in source[source.index("pack_work = "):source.index("pack_work = ") + 120], "이어받은 인계 판은 건드리지 않는다"


def test_the_agent_uses_it_where_it_decides_the_kind_of_job() -> None:
    source = inspect.getsource(BrowserAgent.run)

    assert 'declared_work: str = ""' in source
    assert '_is_web_research_job(plan, plan_text, declared=declared_work == "web")' in source
