"""애니메이터 창고 꼬리표 칸(무기 · 컨셉 · 무게감 · 속도감) — 2026-11-13 · 시험 중.

계기: 현업 애니메이터가 검색 문장 12개를 창고 86개에 넣었더니 5개는 결과 없음 · 7개는 내용과 상관없이 거의 같은 5개(11-12 작업장 PR #9).
코드로 확인한 뿌리: 「공격」 하나가 공격 칸 전부에 2점 → 나머지 낱말이 안 맞으면 공격 칸끼리 이름순 5개.
설계: docs/설계_애니메이터_블렌더중심_2026-11-13.ko.md §5.

양방향:
- 해야 할 것: 12문장의 칸 낱말을 조사 · 붙여 쓰기와 상관없이 읽음 · 꼬리표 달린 동작은 찾음 · 무엇이 맞았는지 보임 ·
  창고에 없는 꼬리표는 「없다」고 말함 · 윗값(검 → 한손검 · 양손검) · 옛 꼬리표(punch → 주먹 → 맨손)도 셈
- 하면 안 되는 것: 「공격」 하나로 아무 공격 5개를 채움 · 「창고」 · 「검색」 · 「활동」의 한 글자가 무기로 잡힘 ·
  「양손 다 사용」이 양손검에 걸림 · 칸 이름 아닌 것으로 달기 · 옛 찾기(「돌진 공격」 · 「대기」 · 빈 말)가 나빠짐
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.animator import library
from alture_jarvis.animator_tools import AnimatorTools

# 작업장 PR #9 의 검색 문장 12개(그대로) — 개수를 직접 센다(쉼표를 삼켜 표본 둘이 합쳐진 적이 있다)
SENTENCES = [
    "무거운 양손검 평타",
    "공중에 떠서 마법공격",
    "스타일리쉬한 느낌의 한손 검 모션",
    "엄청 귀여운 느낌의 도끼 공격 모션",
    "오른손으로 부드럽게 휘두르는 마법",
    "돌진하면서 한 번 베는 공격",
    "창으로 빠르게 찌르는 공격하는 모션",
    "마법 구체를 날려서 공격하는 모션. 양손 다 사용해도 됨.",
    "늘어나는 무기로 빠르게 공격하는 모션",
    "근엄한 아저씨 캐릭터의 맨손 주먹 공격 모션. 스타일리쉬하면 좋음",
    "도도한 아가씨 캐릭터의 표창 공격 모션.",
    "총으로 연타하는 공격 모션.",
]
# 각 문장에서 읽혀야 하는 칸 낱말(사람이 정한 정답)
EXPECT = [
    {"무기:양손검", "무게감:무거운"},
    {"무기:마법"},
    {"컨셉:스타일리쉬", "무기:한손검"},
    {"컨셉:귀여운", "무기:도끼"},
    {"속도감:부드러운", "무기:마법"},
    set(),
    {"무기:창", "속도감:빠른"},
    {"무기:마법"},
    {"무기:늘어나는 무기", "속도감:빠른"},
    {"컨셉:근엄", "무기:맨손", "컨셉:스타일리쉬"},
    {"컨셉:도도", "무기:표창"},
    {"무기:총", "속도감:연타"},
]


class _Packs:
    def is_enabled(self, pack_id: str) -> bool:
        return pack_id == "animator"


class _Config:
    def __init__(self, root: Path) -> None:
        self.documents_dir = root / "docs"
        self.output_dir = root / "out"


def _ready(root: Path, name: str, tags=(), facets=None) -> str:
    e = library.new_entry(root, name=name, origin="own", tags=tags)
    (e["folder"] / "motion.bip").write_bytes(b"BIP")
    if facets:
        library.tag(root, e["id"], facets)
    return e["id"]


def _store(root: Path) -> dict[str, str]:
    """공격 동작 8개(꼬리표 칸 없음) + 칸 달린 셋 + 돌진 · 대기."""
    for i in range(8):
        _ready(root, f"Hero{i}_Attack_hit{i}")
    return {
        "knight": _ready(root, "Knight_Attack_heavy", facets={"무기": ["양손검"], "무게감": ["무거운"]}),
        "lancer": _ready(root, "Lancer_Attack_thrust", facets={"무기": ["창"], "속도감": ["빠른"]}),
        "mage": _ready(root, "Mage_Skill_orb", facets={"무기": ["마법"]}),
        "rogue": _ready(root, "Rogue_Dash_attack"),
        "idle": _ready(root, "Idle_stand"),
    }


def _names(found: list[dict]) -> list[str]:
    return [e["name"] for e in found]


# ── 읽기 ──────────────────────────────────────────────────────────────

def test_twelve_sentences_are_twelve() -> None:
    assert len(SENTENCES) == 12 and len(EXPECT) == 12


@pytest.mark.parametrize("sentence,expect", list(zip(SENTENCES, EXPECT)))
def test_each_sentence_reads_its_facet_words_regardless_of_particles(sentence: str, expect: set) -> None:
    got = {f"{f}:{v}" for f, v in library.read_query(sentence)["facets"]}
    assert got == expect


@pytest.mark.parametrize("query", ["창고에서 공격 찾아 줘", "검색해서 대기 동작", "활동적인 대기", "검은 옷 캐릭터 대기", "총괄 정리"])
def test_one_letter_weapons_do_not_fire_inside_other_words(query: str) -> None:
    assert library.read_query(query)["facets"] == []


def test_two_handed_sword_is_read_before_plain_sword() -> None:
    got = library.read_query("한손 검")["facets"]
    assert got == [("무기", "한손검")]          # 「검」이 따로 한 번 더 잡히지 않는다


# ── 찾기 ──────────────────────────────────────────────────────────────

def test_tagged_motions_are_found_and_say_what_matched(tmp_path: Path) -> None:
    _store(tmp_path)
    got = library.find(tmp_path, "무거운 양손검 평타")
    assert _names(got) == ["Knight_Attack_heavy"]
    assert got[0]["matched"] == ["무기:양손검", "무게감:무거운"]
    assert _names(library.find(tmp_path, "창으로 빠르게 찌르는 공격하는 모션"))[0] == "Lancer_Attack_thrust"


def test_attack_alone_no_longer_fills_five_unrelated_motions(tmp_path: Path) -> None:
    """뿌리: 예전엔 「도끼」가 안 맞아도 「공격」 2점으로 공격 칸 5개가 나왔다."""
    _store(tmp_path)
    for q in ["엄청 귀여운 느낌의 도끼 공격 모션", "도도한 아가씨 캐릭터의 표창 공격 모션.", "총으로 연타하는 공격 모션."]:
        assert library.find(tmp_path, q) == [], q
        rep = library.query_report(tmp_path, q)
        assert rep["missing_facets"], q                     # 무엇이 창고에 없는지 말한다
        assert rep["generic_only_matches"] >= 8             # 원하면 「공격」만으로 다시 찾을 수 있다는 수


def test_both_hands_does_not_hit_the_two_handed_sword(tmp_path: Path) -> None:
    ids = _store(tmp_path)
    got = library.find(tmp_path, "마법 구체를 날려서 공격하는 모션. 양손 다 사용해도 됨.")
    assert [e["id"] for e in got] == [ids["mage"]]


def test_parent_value_and_old_name_tags_count(tmp_path: Path) -> None:
    _store(tmp_path)
    assert _names(library.find(tmp_path, "검 공격")) == ["Knight_Attack_heavy"]           # 검 → 양손검
    _ready(tmp_path, "Brawler_punch_01")                                                # 파일 이름 punch → 꼬리표 「주먹」
    assert _names(library.find(tmp_path, "맨손 공격")) == ["Brawler_punch_01"]


def test_old_queries_still_work(tmp_path: Path) -> None:
    ids = _store(tmp_path)
    assert library.find(tmp_path, "돌진 공격")[0]["id"] == ids["rogue"]
    assert library.find(tmp_path, "돌진하면서 한 번 베는 공격")[0]["id"] == ids["rogue"]   # 「돌진하면서」도 꼬리표 「돌진」으로
    assert [e["id"] for e in library.find(tmp_path, "대기")] == [ids["idle"]]
    assert len(library.find(tmp_path, "공격", k=20)) == 12                                 # 뭉뚱그린 말만이면 예전처럼 다 나온다
    assert len(library.find(tmp_path, "", k=20)) == 13


# ── 달기 ──────────────────────────────────────────────────────────────

def test_tag_replaces_a_facet_keeps_a_log_and_flags_words_outside_the_dictionary(tmp_path: Path) -> None:
    eid = _ready(tmp_path, "Hero_Attack")
    out = library.tag(tmp_path, eid, {"무기": ["외손검"], "컨셉": ["몽환적"]}, who="애니메이터")
    assert out["facets"] == {"무기": ["한손검"], "컨셉": ["몽환적"]}                     # 같은 뜻 말은 사전 값으로
    assert out["not_in_dictionary"] == ["컨셉:몽환적"]
    assert _names(library.find(tmp_path, "몽환적")) == ["Hero_Attack"]                    # 사전 밖 값도 낱말 그대로면 걸린다
    library.tag(tmp_path, eid, {"컨셉": []})                                                # 빈 목록 = 그 칸 지움
    e = json.loads((tmp_path / "library" / eid / "entry.json").read_text(encoding="utf-8"))
    assert e["facets"] == {"무기": ["한손검"]} and len(e["facets_log"]) == 2 and e["facets_log"][0]["by"] == "애니메이터"


def test_tag_refuses_unknown_facets_and_unknown_ids(tmp_path: Path) -> None:
    eid = _ready(tmp_path, "Hero_Attack")
    with pytest.raises(ValueError):
        library.tag(tmp_path, eid, {"성별": ["여자"]})
    with pytest.raises(KeyError):
        library.tag(tmp_path, "없는칸", {"무기": ["창"]})


# ── 도구 ──────────────────────────────────────────────────────────────

def test_tool_says_what_is_missing_instead_of_guessing(tmp_path: Path) -> None:
    t = AnimatorTools(_Config(tmp_path), packs=_Packs())
    _store(t.root)
    got = t.library_find({"query": "엄청 귀여운 느낌의 도끼 공격 모션"})
    assert got["found"] == []
    assert "무기:도끼" in got["note"] and "anim_library_tag" in got["note"]
    hit = t.library_find({"query": "무거운 양손검"})
    assert hit["found"][0]["matched"] == ["무기:양손검", "무게감:무거운"] and hit["found"][0]["facets"]


def test_tag_tool_then_find(tmp_path: Path) -> None:
    t = AnimatorTools(_Config(tmp_path), packs=_Packs())
    ids = _store(t.root)
    assert t.library_find({"query": "도끼"})["found"] == []
    out = t.library_tag({"id": ids["rogue"], "무기": ["도끼"], "컨셉": ["귀여운"]})
    assert out["ok"] and out["facets"] == {"무기": ["도끼"], "컨셉": ["귀여운"]}
    assert [e["id"] for e in t.library_find({"query": "엄청 귀여운 느낌의 도끼 공격 모션"})["found"]] == [ids["rogue"]]
    # 클로드가 실제로 보내는 영문 칸(11-13 · 한글 칸 이름은 클로드 API 가 거절해 도구가 빠졌다) — 위 한글 칸은 옛 이름 호환
    out = t.library_tag({"id": ids["rogue"], "weapon": ["양손검"], "weight": ["무거운"]})
    assert out["facets"] == {"무기": ["양손검"], "컨셉": ["귀여운"], "무게감": ["무거운"]}
    with pytest.raises(ValueError):
        t.library_tag({"id": ids["rogue"]})                                                 # 달 것이 없으면 거절
