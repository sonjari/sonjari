"""애니메이터 팩 — 현업 애니메이터 사용기 요청 6개(2026-11-18).

계기: 현업 애니메이터가 창고 88칸에 꼬리표를 달고 한 동작을 입혀 써 본 뒤 보낸 「이상하게 동작한 것」 표와 요청 6개.
시험 자료의 이름은 모두 지어낸 것이다(회사 · 캐릭터 · 클립 이름을 쓰지 않는다).

양방향:
- 해야 할 것: limit 를 읽음(상한 20) · 없는 무기면 빈 결과와 「없음」 · 지팡이 · 투사체 · 부유무기 = 마법 · 괄호 · 띄어쓰기 · 부분 말 ·
  바이페드 없는 .max 는 빈 칸을 지우고 알림 · 다시 넣어도 안 생김 · 키포즈만 남기는 스크립트 · 멈춤 프레임 후보 · 고정 번호 목록 · 번호로 달기
- 하면 안 되는 것: 다른 칸만 맞은 동작을 내밂 · 「떠 있는 대기」 · 「부유한 귀족」 · 「투사 캐릭터」가 마법으로 · 「양손」이 「양손검」에 ·
  무기 아닌 칸이 빠졌다고 결과를 비움 · 목록 없이 키를 지움 · 번호가 넣은 순서 · 지움으로 바뀜 · 없는 번호가 섞이면 일부만 달림
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from alture_jarvis.animator import library
from alture_jarvis.animator_tools import KEYPOSE_TABLE, AnimatorTools


class _Packs:
    def is_enabled(self, pack_id: str) -> bool:
        return pack_id == "animator"


class _Config:
    def __init__(self, root: Path) -> None:
        self.documents_dir = root / "docs"
        self.output_dir = root / "out"


def _tools(tmp_path: Path) -> AnimatorTools:
    return AnimatorTools(_Config(tmp_path), packs=_Packs())


def _ready(root: Path, name: str, facets=None, character: str = "", source: str = "", frames=(0, 26)) -> str:
    e = library.new_entry(root, name=name, origin="own", character=character, source=source)
    (e["folder"] / "motion.bip").write_bytes(b"BIP")
    (e["folder"] / "max.txt").write_text(f"start={frames[0]} end={frames[1]} fps=30 loop=false biped=Bip001", encoding="utf-8")
    if facets:
        library.tag(root, e["id"], facets)
    return e["id"]


def _names(found: list[dict]) -> list[str]:
    return [e["name"] for e in found]


# ── 5. 찾기 결과 개수(limit) ─────────────────────────────────────────────

def test_find_reads_limit_not_only_k(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    for i in range(25):
        _ready(t.root, f"Hero{i:02d}_Attack")
    assert len(t.library_find({"query": "공격"})["found"]) == 5                  # 기본 5
    assert len(t.library_find({"query": "공격", "limit": 12})["found"]) == 12      # 사용기: limit 20 을 줘도 5개였다
    assert len(t.library_find({"query": "공격", "limit": 50})["found"]) == 20      # 상한 20 그대로
    assert len(t.library_find({"query": "공격", "k": 7})["found"]) == 7            # 옛 이름도
    assert t.library_find({"query": "공격", "limit": "많이"})["limit"] == 5        # 숫자가 아니면 기본


# ── 3. 없는 무기면 「없음」 ───────────────────────────────────────────────

def _store(root: Path) -> dict[str, str]:
    return {
        "fast": _ready(root, "Rogue_Dash_fast", facets={"속도감": ["빠른"], "컨셉": ["스타일리쉬"]}),
        "mage": _ready(root, "Mage_Skill_orb", facets={"무기": ["마법"]}),
        "lancer": _ready(root, "Lancer_Attack_thrust", facets={"무기": ["창"], "속도감": ["빠른"]}),
    }


@pytest.mark.parametrize("query", ["한손검 스타일리쉬한 공격", "도끼로 빠르게 찍는 공격"])
def test_missing_weapon_returns_nothing_even_if_other_facets_match(tmp_path: Path, query: str) -> None:
    t = _tools(tmp_path)
    _store(t.root)
    got = t.library_find({"query": query})
    assert got["found"] == []                                     # 예전: 속도감 · 컨셉만 맞은 동작을 내밀었다
    assert "none_because" in got and "맞는 것이 없다" in got["note"]


def test_spear_query_without_spear_in_store_is_empty(tmp_path: Path) -> None:
    root = tmp_path
    _ready(root, "Rogue_Dash_fast", facets={"속도감": ["빠른"]})
    assert library.find(root, "창으로 빠르게 찌르는") == []
    assert library.query_report(root, "창으로 빠르게 찌르는")["missing_facets"] == ["무기:창"]


def test_present_weapon_still_found_and_missing_non_weapon_facet_does_not_empty(tmp_path: Path) -> None:
    ids = _store(tmp_path)
    assert library.find(tmp_path, "창으로 빠르게 찌르는")[0]["id"] == ids["lancer"]
    # 무게감(무거운)은 창고에 없지만 무기(마법)는 있다 — 결이 빠진 것뿐이라 결과를 낸다(빠진 것은 report 가 말함)
    got = library.find(tmp_path, "무거운 마법 공격")
    assert [e["id"] for e in got] == [ids["mage"]]
    assert "무게감:무거운" in library.query_report(tmp_path, "무거운 마법 공격")["missing_facets"]
    # 둘 중 하나라도 창고에 있으면 비우지 않는다
    assert ids["lancer"] in [e["id"] for e in library.find(tmp_path, "창이나 도끼 공격")]


# ── 2. 찾기 사전 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("query,expect", [
    ("마법(지팡이)", {"무기:마법"}),
    ("마법(투사체)", {"무기:마법"}),
    ("투사체 공격", {"무기:마법"}),
    ("투사체공격", {"무기:마법"}),
    ("지팡이공격", {"무기:마법"}),
    ("부유무기", {"무기:마법"}),
    ("부유 무기", {"무기:마법"}),
    ("부유하는 무기로 공격", {"무기:마법"}),
    ("떠다니는 무기", {"무기:마법"}),
    ("떠다니는무기", {"무기:마법"}),
    ("떠 있는 무기 공격", {"무기:마법"}),
    ("정직한 베기", {"컨셉:정직한"}),
    ("가감속이 확실한 공격", {"속도감:가감속"}),
])
def test_new_field_words_read_into_the_right_facet(query: str, expect: set) -> None:
    assert {f"{f}:{v}" for f, v in library.read_query(query)["facets"]} == expect


@pytest.mark.parametrize("query", [
    "공중에 떠 있는 대기",            # 떠 있음은 무기가 아니다
    "떠다니는 먼지 연출",
    "부유한 귀족 캐릭터 대기",        # 부유(富裕) = 돈 많은
    "공중에 부유하는 대기 동작",
    "투사 캐릭터 대기",              # 투사(鬪士) = 싸움꾼 — 「투사체」부터만
    "정직원 출근 대기",
])
def test_new_words_do_not_fire_on_lookalikes(query: str) -> None:
    assert library.read_query(query)["facets"] == []


def test_words_inside_brackets_are_split() -> None:
    assert "(투사체)" not in library._words("마법(투사체)")
    assert library.read_query("마법(구체)")["words"] == ["구체"]


def test_spacing_and_partial_words_meet_stored_tags(tmp_path: Path) -> None:
    root = tmp_path
    # 사용기 그대로: 꼬리표를 사전 밖 말 「투사체공격」으로 달았다
    proj = _ready(root, "Mage_Skill_bolt", facets={"무기": ["마법", "투사체공격"]})
    plain = _ready(root, "Mage_Skill_aura", facets={"무기": ["마법"]})
    _ready(root, "Knight_Attack_heavy", facets={"무기": ["양손검"]})
    got = [e["id"] for e in library.find(root, "투사체 공격")]           # 예전: 띄어쓰기라 0개
    assert got[0] == proj and plain in got and len(got) == 2
    assert [e["id"] for e in library.find(root, "마법(투사체 공격)")][0] == proj
    assert proj in [e["id"] for e in library.find(root, "투사체")]          # 부분 말
    # 사전 밖 말의 부분 말 · 다른 칸에 단 사전 말
    dreamy = _ready(root, "Fairy_Idle_float", facets={"컨셉": ["몽환적인"]})
    assert [e["id"] for e in library.find(root, "몽환 대기")] == [dreamy]
    eased = _ready(root, "Monk_Attack_palm", facets={"컨셉": ["가감속이 확실한"]})
    assert [e["id"] for e in library.find(root, "가감속 있는 공격")] == [eased]


def test_both_hands_still_does_not_hit_two_handed_sword_with_partial_rule(tmp_path: Path) -> None:
    """부분 말 규칙(「투사체」 → 「투사체공격」)이 11-13 반례(「양손」 → 「양손검」)를 되살리지 않는다."""
    _ready(tmp_path, "Knight_Attack_heavy", facets={"무기": ["양손검"]})
    mage = _ready(tmp_path, "Mage_Skill_orb", facets={"무기": ["마법"]})
    got = library.find(tmp_path, "마법 구체를 날려서 공격하는 모션. 양손 다 사용해도 됨.")
    assert [e["id"] for e in got] == [mage]
    assert library.find(tmp_path, "양손 대기") == []


# ── 6. 바이페드 없는 .max ────────────────────────────────────────────────

def test_batch_script_drops_the_empty_slot_and_logs_full_path(tmp_path: Path) -> None:
    src = tmp_path / "in" / "Hero_mesh_only.max"
    folder = tmp_path / "library" / "Hero_mesh_only_abc123"
    ms = library.add_folder_batch_script([(src, folder)], log_path=tmp_path / "library" / "_batch_x_log.txt")
    assert f'sjLog ("nobiped " + @"{src}")' in ms                  # 이름만이 아니라 전체 경로
    assert f'sjDropEmpty @"{folder}"' in ms
    assert "System.IO.Directory\").Delete folder true" in ms
    assert library.NOBIPED_MARK in ms                              # 못 지우면 표시 파일


def test_rerun_skips_nobiped_files_and_counts_match_folders(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    src = tmp_path / "company" / "HeroA" / "Animation"
    src.mkdir(parents=True)
    a, b = src / "HeroA_attack.max", src / "HeroA_rig_only.max"
    a.write_bytes(b"MAX")
    b.write_bytes(b"MAX")
    first = t.library_add({"source": "max_folder", "origin": "company", "path": str(src.parents[1])})
    assert first["files"] == 2
    # 맥스가 돈 것처럼: a 는 .bip, b 는 바이페드가 없어 빈 칸을 지우고 기록
    lib = library.lib_dir(t.root)
    by_src = {e["source"]: lib / e["id"] for e in library.entries(t.root, include_pending=True)}
    (by_src[str(a)] / "motion.bip").write_bytes(b"BIP")
    shutil.rmtree(by_src[str(b)])
    Path(first["log"]).write_text(f"start {a.name}\r\nok {a.name}\r\nstart {b.name}\r\nnobiped {b}\r\n", encoding="utf-8")
    again = t.library_add({"source": "max_folder", "origin": "company", "path": str(src.parents[1])})
    assert again["files"] == 0 and "HeroA_rig_only.max" in again["no_biped"]      # 예전: 다시 넣으면 같은 빈 칸이 또 생겼다
    folders = [p for p in lib.iterdir() if (p / "entry.json").is_file()]
    found = t.library_find({"query": ""})
    assert len(folders) == found["library_size"] == 1                              # 폴더 수 = 셈(88 대 86 어긋남이 증상)
    assert "바이페드 없음 1개(HeroA_rig_only.max)" in found["empty_slots"]["no_biped"]
    redo = t.library_add({"source": "max_folder", "origin": "company", "path": str(src.parents[1]), "include_nobiped": True})
    assert redo["files"] == 1                                                      # 바이페드를 넣었으면 다시 넣을 수 있다


def test_old_empty_slots_from_name_only_logs_are_reported_not_counted(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    _ready(t.root, "HeroB_idle")
    old = library.new_entry(t.root, name="HeroB_mesh_v2", origin="company", source=r"D:\work\HeroB\HeroB_mesh_v2.max")
    (library.lib_dir(t.root) / "_batch_20251111_000000_log.txt").write_text("start HeroB_mesh_v2.max\r\nnobiped HeroB_mesh_v2.max\r\n",
                                                                             encoding="utf-8")
    assert [e["no_biped"] for e in library.entries(t.root, include_pending=True) if e["id"] == old["id"]] == [True]
    got = t.library_find({"query": "대기"})
    assert got["library_size"] == 1 and got["empty_slots"]["empty_folders"] == 1
    assert "HeroB_mesh_v2.max" in got["empty_slots"]["no_biped"]
    # 바이페드 없음 기록이 없는 빈 칸은 「아직 .bip 없음」으로 따로
    library.new_entry(t.root, name="HeroB_run", origin="company", source=r"D:\work\HeroB\HeroB_run.max")
    assert "1개" in t.library_find({"query": "대기"})["empty_slots"]["pending"]


# ── 1. 메인 키포즈만 남기기 ──────────────────────────────────────────────

def test_keep_frames_sorts_dedupes_clamps_and_keeps_ends() -> None:
    got = library.keep_frames([26, 4, 0, 6, 13, 18, 23, 4, 30], 0, 26)
    assert got["keep"] == [0, 4, 6, 13, 18, 23, 26] and got["out_of_range"] == [30] and got["added_ends"] == []
    got = library.keep_frames([4, 13.0, "18"], 0, 26)
    assert got["keep"] == [0, 4, 13, 18, 26] and got["added_ends"] == [0, 26]
    assert library.keep_frames(["넷"], 0, 26)["not_numbers"] == ["넷"]
    assert library.keep_frames([5, 9])["keep"] == [5, 9]                 # 구간을 모르면 맥스가 첫끝을 더한다


def _script(**kw) -> str:
    return library.apply_script(Path("C:/lib/x/motion.bip"), "Bip001", "x", (0, 26), **kw)


def test_apply_with_keep_keys_trims_after_everything_else() -> None:
    ms = _script(keep_keys=[0, 4, 6, 13, 18, 23, 26])
    assert "sjTrimKeys com #(0, 4, 6, 13, 18, 23, 26)" in ms
    assert "deleteKey c i" in ms and "for i = c.keys.count to 1 by -1" in ms     # 엇박자 쓰기와 같은 꼴(뒤에서부터)
    # 지우기는 첫끝 덮기 · 발 고정 뒤(그 둘이 쓴 첫 · 끝 키 위에서 남긴다)
    assert ms.index("(sjBookend com cap") < ms.index("(sjFootLock com") < ms.index("(sjTrimKeys com")
    assert "키 수가 안 줄었다" in ms                                            # 지우기가 안 먹으면 스스로 말한다


def test_apply_without_list_never_deletes_but_writes_motion_table() -> None:
    ms = _script(amount_path=Path("C:/lib/x/keypose_amount.txt"))
    assert "(sjTrimKeys com" not in ms and "deleteKey" in ms                     # 함수는 실려도 부르지 않는다
    assert 'sjMotionAmount com (animationRange.start.frame as integer) (animationRange.end.frame as integer) @"C:' in ms
    plain = _script()
    assert "sjTrimKeys" not in plain and "sjMotionAmount" not in plain           # 옛 입히기는 그대로


def test_keypose_candidates_pick_pauses_and_ends() -> None:
    dips = {4, 6, 13, 18, 23}
    rows = [(f, 0.1 if f in dips else 1.0) for f in range(27)]
    assert library.keypose_candidates(rows)["candidates"] == [0, 4, 6, 13, 18, 23, 26]   # 사용기에서 사람이 고른 자리
    # 멈춤이 여러 프레임이면 처음 · 끝
    hold = [(f, 0.05 if 10 <= f <= 12 else 1.0 + 0.01 * f) for f in range(20)]
    assert library.keypose_candidates(hold)["candidates"] == [0, 10, 12, 19]
    # 반례: 멈춤 없이 빨라지기만 하면 첫 · 끝뿐 · 빠른 구간 속 작은 골짜기(중앙값 위)는 후보가 아니다
    assert library.keypose_candidates([(f, float(f)) for f in range(10)])["candidates"] == [0, 9]
    bump = [(f, 0.2) for f in range(10)] + [(10, 5.0), (11, 4.0), (12, 5.0)] + [(f, 0.2) for f in range(13, 20)]
    assert 11 not in library.keypose_candidates(bump)["candidates"]
    assert library.keypose_candidates([])["candidates"] == []


def test_read_motion_amount_skips_bad_lines(tmp_path: Path) -> None:
    p = tmp_path / "t.txt"
    p.write_text("1 0.5\n0 1.2e-05\nbad\n2 x\n", encoding="utf-8")
    assert library.read_motion_amount(p) == [(0, 1.2e-05), (1, 0.5)]


def test_apply_tool_keep_keys_and_keypose_check(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    eid = _ready(t.root, "Mage_Skill_special", frames=(0, 26))
    out = t.library_apply({"id": eid, "keep_keys": [4, 13, 18, 40]})
    assert out["keyposes"]["keep"] == [0, 4, 13, 18, 26] and out["keyposes"]["out_of_range"] == [40]
    assert "say" in out["keyposes"] and "keypose_hint" not in out
    ms = sorted((library.lib_dir(t.root) / eid).glob("apply_*.ms"))[-1].read_text(encoding="utf-8")
    assert "sjTrimKeys com #(0, 4, 13, 18, 26)" in ms
    with pytest.raises(ValueError):
        t.library_apply({"id": eid, "keep_keys": "4,13"})
    with pytest.raises(ValueError):
        t.library_apply({"id": eid, "keep_keys": [100, 200]})                      # 구간 안이 하나도 없음
    # 목록 없이 입히면 지우지 않고 표만 · 표가 없으면 후보를 지어내지 않는다
    plain = t.library_apply({"id": eid})
    assert "keypose_hint" in plain and "keyposes" not in plain
    with pytest.raises(FileNotFoundError):
        t.library_apply({"id": eid, "keypose_check": True})
    (library.lib_dir(t.root) / eid / KEYPOSE_TABLE).write_text(
        "".join(f"{f} {0.1 if f in (4, 6, 13, 18, 23) else 1.0}\n" for f in range(27)), encoding="utf-8")
    chk = t.library_apply({"id": eid, "keypose_check": True})
    assert chk["candidates"] == [0, 4, 6, 13, 18, 23, 26] and len(chk["table"]) == 27
    # 다음 입히기는 지난 표를 지운다(옛 표를 이번 것으로 읽지 않게)
    t.library_apply({"id": eid})
    assert not (library.lib_dir(t.root) / eid / KEYPOSE_TABLE).exists()


# ── 4. 창고 목록 · 고정 번호 ─────────────────────────────────────────────

def test_numbers_are_fixed_and_never_reused(tmp_path: Path) -> None:
    root = tmp_path
    z = _ready(root, "Zeta_run")
    a = _ready(root, "Alpha_idle")
    c = _ready(root, "Gamma_jump")
    rows = library.listing(root)["rows"]
    assert [(r["no"], r["name"]) for r in rows] == [(1, "Zeta_run"), (2, "Alpha_idle"), (3, "Gamma_jump")]   # 이름순이 아니라 넣은 차례
    shutil.rmtree(library.lib_dir(root) / c)
    d = _ready(root, "Beta_walk")
    got = {r["id"]: r["no"] for r in library.listing(root)["rows"]}
    assert got == {z: 1, a: 2, d: 4}                                               # 지운 3번은 다시 안 쓴다


def test_old_library_without_numbers_gets_stable_numbers(tmp_path: Path) -> None:
    root = tmp_path
    ids = [_ready(root, n) for n in ("Old_c", "Old_a", "Old_b")]
    for i, eid in enumerate(ids):                                                  # 11-18 전 창고처럼 번호 · 카운터를 지운다
        ej = library.lib_dir(root) / eid / "entry.json"
        e = json.loads(ej.read_text(encoding="utf-8"))
        e.pop("no")
        e["created"] = f"2026-11-0{i + 1} 10:00:00"
        ej.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    (library.lib_dir(root) / "_next_no.txt").unlink()
    first = [(r["no"], r["id"]) for r in library.listing(root)["rows"]]
    assert first == [(1, ids[0]), (2, ids[1]), (3, ids[2])]                        # 만든 차례
    assert [(r["no"], r["id"]) for r in library.listing(root)["rows"]] == first   # 두 번 봐도 같다
    assert library.new_entry(root, name="New_one", origin="own")["no"] == 4


def test_listing_row_has_frames_group_facets_and_state(tmp_path: Path) -> None:
    root = tmp_path
    _ready(root, "HeroC_attack", facets={"무기": ["마법"], "속도감": ["빠른"]}, source=r"D:\co\HeroC\Animation\HeroC_attack.max",
           frames=(0, 26))
    _ready(root, "Hero_D_idle", character="묶음D", frames=(0, 60))
    library.new_entry(root, name="HeroC_wip", origin="company", source=r"D:\co\HeroC\HeroC_wip.max")
    lst = library.listing(root)
    r1, r2, r3 = lst["rows"]
    assert (r1["frames"], r1["group"], r1["facets"]) == (26, "HeroC", "무기:마법 · 속도감:빠른") and "state" not in r1
    assert (r2["frames"], r2["group"]) == (60, "묶음D")
    assert r3["state"].startswith("빈 칸") and lst["counts"] == {"ready": 2, "no_biped": 0, "pending": 1, "model_files": 0}
    assert lst["folders"] == 3
    assert library._group({"source": r"D:\HeroE_run.max"}) == "" and library._group({"source": "D:/co/HeroE/anim/x.max"}) == "HeroE"


def test_tag_by_numbers_is_all_or_nothing(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    a = _ready(t.root, "Mage_A")
    b = _ready(t.root, "Mage_B")
    _ready(t.root, "Knight_C")
    lst = t.library_find({"list": True})
    assert [r["no"] for r in lst["rows"]] == [1, 2, 3] and "번호" in lst["next"]
    out = t.library_tag({"nos": [1, 2], "weapon": ["지팡이공격"]})
    assert out["count"] == 2 and all(x["facets"] == {"무기": ["지팡이공격"]} for x in out["tagged"])   # 사람 말 그대로 남긴다
    assert all("not_in_dictionary" not in x for x in out["tagged"])                                    # 마법으로 읽히니 「사전 밖」이 아니다
    assert {e["id"] for e in library.find(t.root, "지팡이")} == {a, b}
    assert {e["id"] for e in library.find(t.root, "마법 공격")} == {a, b}
    with pytest.raises(KeyError):
        t.library_tag({"nos": [3, 99], "speed": ["빠른"]})
    assert "facets" not in library.get(t.root, library.id_of_number(t.root, 3))   # 없는 번호가 섞이면 하나도 안 단다
    with pytest.raises(ValueError):
        t.library_tag({"id": a, "no": 1, "speed": ["빠른"]})
    assert t.library_tag({"no": 3, "speed": ["빠른"]})["tagged"][0]["no"] == 3
