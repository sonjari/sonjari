"""직접 넣는 스킬팩 — 문서 폴더의 `skillpacks` 에 폴더를 넣으면 손자리가 읽는다 (2026-10-11).

대표: 「스킬팩 폴더를 하나 만들어 주고 그걸 손자리에 넣는 방식 · 사용자는 우리가 준 폴더를 거기에 넣기만 하면 된다 ·
바꾸기도 쉽고 유지보수도 쉽다」.

지금까지 팩은 프로그램이 설치된 폴더 안에서만 읽었다 — 스토어 판은 그 폴더에 아무것도 못 넣는다. 그리고 어떤 말에 어떤
스킬이 붙는지가 코드 안 낱말표에 박혀 있어서, 새 스킬은 넣어도 영영 안 걸렸다.

지키는 것
- 직접 넣는 폴더에서는 **스킬 글만 든 팩**만 읽는다. 누가 준 폴더를 넣었다고 새 실행 능력이 생기면 안 된다.
- 우리가 싣는 팩 · 스킬의 이름을 가로채지 못한다. 못 읽은 것은 조용히 빠지지 않고 이유가 남는다.
- 기본은 꺼짐. 켠 팩의 스킬은 「스킬 붙이기」 설정이 꺼져 있어도, 분야를 골라 좁혀 놓았어도 붙는다 — 사람이 켠 것이다.
- 팩은 제 낱말을 들고 온다. 그 낱말은 그 팩의 스킬에만 붙고, 「해 줘」 같은 말끝이 없어도 걸린다(맞춤 팩은 짧게 시킨다).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.packs import PackRegistry
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.skill_domains import DOMAINS
from alture_jarvis.skills import SkillLibrary, match_skills

REPO = Path(__file__).resolve().parents[1]
MARK = "표식-가격조사-본문"
SKILL = f"""---
name: price-watch
description: 정해 둔 가게들에서 같은 상품의 가격을 모아 엑셀로 정리한다
---
# 가격 조사

1. 가게 목록의 주소를 차례로 연다.
2. 상품 이름 · 판매 가격 · 배송비를 읽는다.

{MARK}
"""
WORDS = {"price-watch": ["가격 조사", "가격조사"]}


def _drop(user_dir: Path, pack_id: str = "price-watch-demo", *, skills: tuple[str, ...] = ("price-watch",),
          body: str = SKILL, **overrides: Any) -> Path:
    """손님이 받은 폴더를 스킬팩 폴더에 끌어다 놓은 것."""
    folder = user_dir / pack_id
    folder.mkdir(parents=True)
    data: dict[str, Any] = {
        "id": pack_id, "name": "가격 조사 스킬팩", "version": "1.0.0", "kind": "content", "summary": "가게 가격 모으기",
        "skills": list(skills),
        "permissions": {"reads": [], "writes": [], "runs": [], "network": "손자리가 여는 페이지만"},
    }
    data.update(overrides)
    (folder / "pack.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for name in skills:
        (folder / "skills" / name).mkdir(parents=True)
        (folder / "skills" / name / "SKILL.md").write_text(body, encoding="utf-8")
    return folder


def _registry(tmp_path: Path) -> PackRegistry:
    return PackRegistry(REPO / "packs", tmp_path / "data", user_dir=tmp_path / "skillpacks")


def _library(registry: PackRegistry) -> SkillLibrary:
    library = SkillLibrary(JarvisConfig(runtime_root=REPO, skills_dir=REPO / "skills"),
                           extra_dirs=registry.skill_dirs, pack_dirs=registry.user_skill_dirs)
    registry.on_change(library.reload)
    return library


# --- 폴더를 넣으면 보인다 ------------------------------------------------------------

def test_a_dropped_folder_shows_up_switched_off_and_marked_as_the_users(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks")
    registry = _registry(tmp_path)

    listing = registry.listing()
    rows = {row["id"]: row for row in listing["packs"]}

    assert rows["price-watch-demo"]["origin"] == "user" and rows["price-watch-demo"]["enabled"] is False
    assert rows["game"]["origin"] == "builtin"
    assert listing["user_dir"] == str(tmp_path / "skillpacks"), "화면이 「여기에 넣으세요」를 보여 줄 자리"
    assert listing["problems"] == []


def test_no_user_folder_is_the_same_as_before(tmp_path: Path) -> None:
    registry = PackRegistry(REPO / "packs", tmp_path / "data")

    assert set(registry.packs) == {"game"} and registry.listing()["user_dir"] == ""
    assert registry.user_skill_dirs() == [] and registry.triggers() == {}


def test_a_dropped_pack_cannot_bring_code(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks", "sneaky", kind="code", tools=["local_run_shell"])
    registry = _registry(tmp_path)

    assert "sneaky" not in registry.packs
    assert any("sneaky" in problem and "content" in problem for problem in registry.problems), "조용히 빠지지 않고 이유를 남긴다"


def test_a_dropped_pack_cannot_take_the_name_of_one_we_ship(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks", "game")
    registry = _registry(tmp_path)

    assert registry.packs["game"].origin == "builtin" and registry.packs["game"].kind == "code"
    assert any("game" in problem for problem in registry.problems)


def test_a_folder_dropped_after_start_is_found_by_reading_again(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    called: list[bool] = []
    registry.on_change(lambda: called.append(True))
    assert "price-watch-demo" not in registry.packs

    _drop(tmp_path / "skillpacks")
    listing = registry.rescan()

    assert "price-watch-demo" in {row["id"] for row in listing["packs"]} and called, "다시 읽으면 스킬도 다시 읽는다"
    registry.set_enabled("price-watch-demo", True)
    assert registry.rescan() and registry.is_enabled("price-watch-demo"), "다시 읽어도 켠 것은 켜진 채다"
    assert registry.is_enabled("game") is False


# --- 켜면 스킬이 들어온다 -----------------------------------------------------------

def test_turning_it_on_brings_the_skill_and_off_takes_it_away(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks")
    registry = _registry(tmp_path)
    library = _library(registry)
    assert "price-watch" not in library.skills and library.pack_skill_names == set()

    registry.set_enabled("price-watch-demo", True)

    doc = library.skills["price-watch"]
    assert doc.served, "직접 넣은 폴더에는 LICENSE 파일을 요구하지 않는다 — 넣은 사람이 제 것을 넣은 것이다"
    assert doc.collection == "price-watch-demo" and MARK in doc.body
    assert library.pack_skill_names == {"price-watch"}
    assert tmp_path / "skillpacks" / "price-watch-demo" / "skills" not in registry.skill_dirs(), "우리 팩과 폴더 짜임이 다르다"

    registry.set_enabled("price-watch-demo", False)
    assert "price-watch" not in library.skills and library.pack_skill_names == set()


def test_a_skill_that_does_not_say_what_it_is_for_is_not_handed_out(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks", body="# 설명 없는 글\n\n본문만 있다.\n")
    registry = _registry(tmp_path)
    library = _library(registry)
    registry.set_enabled("price-watch-demo", True)

    doc = library.skills["price-watch"]
    assert doc.served is False and "description" in doc.reason
    assert library.pack_skill_names == set()


def test_a_dropped_skill_cannot_replace_one_we_ship(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks", skills=("frontend-design",))
    registry = _registry(tmp_path)
    library = _library(registry)
    registry.set_enabled("price-watch-demo", True)

    assert library.skills["frontend-design"].collection == "anthropic"
    assert any("frontend-design" in problem for problem in library.pack_problems)
    assert "frontend-design" not in library.pack_skill_names


# --- 팩은 제 낱말을 들고 온다 --------------------------------------------------------

def test_the_pack_brings_its_own_words(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks", triggers=WORDS)
    registry = _registry(tmp_path)
    assert registry.triggers() == {}, "꺼진 팩의 낱말은 없는 것이다"

    registry.set_enabled("price-watch-demo", True)

    assert registry.triggers() == {"price-watch": ("가격 조사", "가격조사")}


def test_pack_words_match_without_a_task_verb_but_only_for_the_packs_skill() -> None:
    extra = {"price-watch": ("가격 조사", "가격조사")}
    available = {"price-watch", "frontend-design"}

    assert match_skills("이번 주 가격 조사", available=available, extra_triggers=extra) == [("price-watch", 1)]
    assert match_skills("이번 주 가격 조사", available=available) == [], "낱말을 안 들고 왔으면 붙을 까닭이 없다"
    assert match_skills("랜딩 페이지", available=available, extra_triggers=extra) == [], "우리 스킬은 여전히 시키는 말이 있어야 붙는다"
    assert match_skills("랜딩 페이지 만들어줘", available=available, extra_triggers=extra)[0][0] == "frontend-design"
    assert match_skills("블로그에 가격 조사 결과 올려줘", available=available, extra_triggers=extra) == [], "다른 갈래의 일은 그대로 비킨다"
    assert match_skills("Run the Price Check for this week", available=available,
                        extra_triggers={"price-watch": ("price check",)}) == [("price-watch", 1)], "영어로 시켜도 같은 낱말표"


@pytest.mark.parametrize("triggers, why", [
    ({"someone-elses-skill": ["가격 조사"]}, "제 스킬이 아닌 것에 낱말을 달 수 없다"),
    ({"price-watch": ["가"]}, "한 글자 낱말은 아무 말에나 걸린다"),
    ({"price-watch": "가격 조사"}, "목록이어야 한다"),
])
def test_bad_words_keep_the_pack_out_and_say_why(tmp_path: Path, triggers: Any, why: str) -> None:
    _drop(tmp_path / "skillpacks", triggers=triggers)
    registry = _registry(tmp_path)

    assert "price-watch-demo" not in registry.packs, why
    assert any("triggers" in problem for problem in registry.problems), why


# --- 붙는 자리: 설정이 꺼져 있어도, 분야로 좁혀 놓았어도 --------------------------------

class _Silent:
    def publish(self, *args: Any, **kwargs: Any) -> None: ...
    def add_audit(self, *args: Any, **kwargs: Any) -> None: ...


def _runtime(tmp_path: Path, *, route: bool, domains: tuple[str, ...] = (), enabled: bool = True) -> JarvisRuntime:
    _drop(tmp_path / "skillpacks", triggers=WORDS)
    registry = _registry(tmp_path)
    config = type("_S", (), {
        "skills_dir": REPO / "skills", "skills_max_chars": 12_000, "skills_body_max_chars": 12_000,
        "skills_fold_sections": False, "skills_route_enabled": route, "skills_guess_enabled": False,
        "skills_domains": domains,
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


def test_a_pack_the_person_switched_on_attaches_even_with_skill_routing_off(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, route=False)

    assert MARK in runtime._skill_instruction("이번 주 가격 조사 해줘", job_id="j1", for_agent=True)
    assert runtime._skill_instruction("랜딩 페이지 만들어줘", job_id="j2", for_agent=True) == "", (
        "설정이 꺼져 있으면 우리 스킬은 여전히 안 붙는다 — 켠 것은 그 팩뿐이다"
    )
    assert runtime._skill_instruction("오늘 날씨 어때", job_id="j3", for_agent=True) == ""


def test_a_switched_off_pack_attaches_nothing(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, route=False, enabled=False)

    assert runtime._skill_instruction("이번 주 가격 조사 해줘", job_id="j1", for_agent=True) == ""


def test_narrowing_by_field_does_not_push_the_pack_out(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, route=True, domains=(DOMAINS[0].id,))

    assert "price-watch" not in set(DOMAINS[0].skills), "이 시험은 팩의 스킬이 그 분야 목록에 없을 때를 본다"
    assert MARK in runtime._skill_instruction("이번 주 가격 조사 해줘", job_id="j1", for_agent=True)


def test_which_skill_attached_records_that_it_came_from_a_pack(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, route=False)
    seen: list[dict[str, Any]] = []
    runtime.store.add_audit = lambda kind, job_id, record: seen.append(record)  # type: ignore[method-assign]

    runtime._skill_instruction("이번 주 가격 조사 해줘", job_id="j9", for_agent=True)

    assert seen and seen[0]["skill"] == "price-watch" and seen[0]["from_pack"] is True and seen[0]["picked_by"] == "triggers"


# --- 자리와 문 ----------------------------------------------------------------------

def test_the_folder_lives_in_the_documents_folder_not_in_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """앱 자료 폴더에 두면 스토어 판에서는 「앱 전용 칸」으로 가서, 탐색기로 넣은 것을 손자리가 못 본다(2026-09-18)."""
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", documents_dir=tmp_path / "문서" / "Sonjari")
    assert config.skillpacks_dir == tmp_path / "문서" / "Sonjari" / "skillpacks"

    monkeypatch.setenv("JARVIS_USER_PACKS_DIR", str(tmp_path / "elsewhere"))
    assert JarvisConfig.from_env().skillpacks_dir == tmp_path / "elsewhere"
    monkeypatch.delenv("JARVIS_USER_PACKS_DIR")
    monkeypatch.setenv("JARVIS_DOCUMENTS_DIR", str(tmp_path / "docs"))
    assert JarvisConfig.from_env().skillpacks_dir == tmp_path / "docs" / "skillpacks"


def test_the_runtime_and_the_api_are_wired_to_it() -> None:
    runtime = (REPO / "src" / "alture_jarvis" / "runtime.py").read_text(encoding="utf-8")
    api = (REPO / "src" / "alture_jarvis" / "api.py").read_text(encoding="utf-8")

    assert "user_dir=self.config.skillpacks_dir" in runtime and "pack_dirs=self.packs.user_skill_dirs" in runtime
    assert '"/v1/packs/rescan"' in api, "폴더를 넣은 뒤 「다시 읽기」"
    assert '"skillpacks": runtime.config.skillpacks_dir' in api, "「스킬팩 폴더 열기」는 정해 둔 폴더만 연다"
    assert api.index('"/v1/packs/rescan"') < api.index('"/v1/packs/{pack_id}/{action}"')


# --- 팩은 「시키는 말」도 들고 온다 (2026-10-11 낮) -------------------------------------
#
# 첫 실제 판(08dafda3): 「로지텍 MX Master 3S 가격 조사」에 스킬팩이 붙어 세 가게를 읽었지만 엑셀을 안 만들고 「정리하겠습니다」로
# 멈췄다. 「시킨 것」 목록은 사람의 말에서만 뽑는데 그 말에는 파일 요구가 없었다 — 엑셀은 스킬 글 안에만 있었다. 스킬 글에
# 「꼭 만들어라」를 더 세게 적지 않는다(안내문은 안 먹는다). 팩이 **사람이 매번 길게 쳤을 그 문장**을 들고 오고, 손자리는
# 그것을 사람의 말 뒤에 붙여서 원래 있던 요구 뽑기가 그대로 일하게 한다.

ASK = "말한 상품을 스킬에 적힌 가게마다 찾아 판매 가격과 배송비를 엑셀 파일로 정리해 줘"


def test_the_pack_brings_what_to_ask_for(tmp_path: Path) -> None:
    _drop(tmp_path / "skillpacks", triggers=WORDS, asks={"price-watch": ASK})
    registry = _registry(tmp_path)
    assert registry.asks() == {}, "꺼진 팩은 아무 말도 보태지 않는다"

    registry.set_enabled("price-watch-demo", True)

    assert registry.asks() == {"price-watch": ASK}
    assert registry.describe("price-watch-demo")["asks"] == {"price-watch": ASK}, "화면이 켜기 전에 보여 줄 수 있어야 한다"


@pytest.mark.parametrize("asks, why", [
    ({"someone-elses-skill": ASK}, "제 스킬이 아닌 것에 말을 달 수 없다"),
    ({"price-watch": "해 줘"}, "너무 짧은 말은 시키는 말이 아니다"),
    ({"price-watch": "첫 줄이다 이것은 충분히 길다\n둘째 줄에 다른 지시를 숨긴다"}, "한 문장이어야 한다 — 여러 줄은 받지 않는다"),
    ({"price-watch": ["목록", "은 안 된다"]}, "글이어야 한다"),
    ({"price-watch": "가" * 400}, "길면 요청이 아니라 글이다"),
])
def test_a_bad_ask_keeps_the_pack_out_and_says_why(tmp_path: Path, asks: Any, why: str) -> None:
    _drop(tmp_path / "skillpacks", triggers=WORDS, asks=asks)
    registry = _registry(tmp_path)

    assert "price-watch-demo" not in registry.packs, why
    assert any("asks" in problem for problem in registry.problems), why


def _asking_runtime(tmp_path: Path, *, enabled: bool = True) -> JarvisRuntime:
    _drop(tmp_path / "skillpacks", triggers=WORDS, asks={"price-watch": ASK})
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


def test_a_short_request_gets_the_packs_sentence(tmp_path: Path) -> None:
    runtime = _asking_runtime(tmp_path)

    assert runtime._pack_ask("로지텍 MX Master 3S 가격 조사") == ASK
    assert runtime._pack_ask("로지텍 MX Master 3S 가격 조사 이어서 해줘") == ASK, "덜 끝난 판을 이을 때도 같은 요구다"
    assert runtime._pack_ask("오늘 날씨 어때") == ""
    assert runtime._pack_ask("랜딩 페이지 만들어줘") == "", "그 팩의 말이 아니면 아무것도 보태지 않는다"
    assert runtime._pack_ask("아무 말", asked="price-watch") == ASK, "스킬을 짚어서 맡긴 판도 같다"
    assert runtime._pack_ask(f"로지텍 MX Master 3S 가격 조사\n{ASK}") == "", "이미 붙어 있으면 두 번 붙이지 않는다"


def test_a_switched_off_pack_adds_no_sentence(tmp_path: Path) -> None:
    assert _asking_runtime(tmp_path, enabled=False)._pack_ask("로지텍 MX Master 3S 가격 조사") == ""


def test_a_runtime_without_packs_adds_nothing() -> None:
    holder = JarvisRuntime.__new__(JarvisRuntime)

    assert holder._pack_ask("로지텍 MX Master 3S 가격 조사") == ""


def test_the_sentence_is_what_makes_the_file_a_requirement() -> None:
    """이 고침의 까닭 그 자체 — 붙이기 전에는 파일 요구가 없고, 붙이면 생긴다."""
    from alture_jarvis import plan

    short = "로지텍 MX Master 3S 가격 조사"
    kinds_before = {(req.kind, tuple(req.target)) for req in plan.extract(short)}
    kinds_after = {(req.kind, tuple(req.target)) for req in plan.extract(f"{short}\n{ASK}")}

    assert ("artifact", (".xlsx",)) not in kinds_before
    assert ("artifact", (".xlsx",)) in kinds_after


def test_the_job_joins_the_sentence_before_anything_reads_the_request() -> None:
    """갈래 고르기 · 요구 뽑기 · 스킬 붙이기가 모두 붙인 뒤의 글을 본다. 사람에게 보이는 말은 친 그대로 남는다."""
    import inspect

    source = inspect.getsource(JarvisRuntime._chat_job_inner)
    joined = source.index("pack_ask = ")

    assert "self._pack_ask(steer_plan or prompt" in source, "이어서 해줘는 앞 판의 요청과 합친 글로 본다"
    assert source.index("display_prompt = ") < joined, "보이는 말은 붙이기 전에 정해 둔다"
    assert source.index("unfinished_base = ") < joined, "「이어서 해줘」인지는 사람이 친 말로 가린다"
    assert joined < source.index("asked_text = ") < source.index("self.agent.should_handle(")
    for name in ("prompt", "model_prompt", "steer_plan"):
        assert f'{name} = f"{{{name}}}\\n{{pack_ask}}"' in source, name
    assert '"skill_pack_ask_joined"' in source, "붙였으면 기록에 남긴다 — 안 남기면 나중에 못 센다"

def test_the_packs_own_skill_leads_when_one_of_ours_also_matches(tmp_path: Path) -> None:
    """실제 판 36c14123: 붙인 문장의 「엑셀 파일로 정리」에 우리 문서 스킬도 걸렸고, 점수가 같아 이름순으로 그쪽이 앞에 섰다.

    사람이 그 일을 위해 넣고 켠 팩이다 — 팩의 낱말로 걸린 스킬이 앞자리(본문을 가장 길게 싣는 자리)에 선다.
    """
    runtime = _runtime(tmp_path, route=True)
    seen: list[dict[str, Any]] = []
    runtime.store.add_audit = lambda kind, job_id, record: seen.append(record)  # type: ignore[method-assign]

    note = runtime._skill_instruction(f"로지텍 MX Master 3S 가격 조사\n{ASK}", job_id="j1", for_agent=True)

    assert seen[0]["skill"] == "price-watch" and seen[0]["from_pack"] is True
    assert "document-craft" in seen[0]["also"], "우리 스킬은 빠지지 않고 뒤에 선다"
    assert MARK in note


def test_a_skill_the_caller_named_still_comes_first(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, route=True)
    seen: list[dict[str, Any]] = []
    runtime.store.add_audit = lambda kind, job_id, record: seen.append(record)  # type: ignore[method-assign]

    runtime._skill_instruction(f"로지텍 MX Master 3S 가격 조사\n{ASK}", job_id="j2", for_agent=True, asked="document-craft")

    assert seen[0]["skill"] == "document-craft" and seen[0]["picked_by"] == "asked", "짚어서 맡긴 것이 먼저다"
