"""애니메이터 팩 — 엇박자 루프 두 걸음 시험 (2026-11-02).

맥스 없이 잰다: 맥스가 쓸 키 파일(keys.json)을 시험이 직접 만들고, 계획 · 쓰기 스크립트가 계산과 같은지 본다.
양방향: 해야 할 것(팩 켜면 돔 · 계산 그대로 씀 · 탄젠트 따라감 · 바이페드 알림 · 이음매 닫힘) /
하면 안 되는 것(팩 꺼지면 거절 · 늦춤 없이 계산 · 폴더 밖 파일 읽기 · 뿌리 트랙 다시 쓰기 · 손자리 모델 목록에 낌).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from alture_jarvis.animator import offset
from alture_jarvis.animator.maxscript import apply_script, read_script, run_line
from alture_jarvis.animator.plan import build_plan
from alture_jarvis.animator_tools import AnimatorTools
from alture_jarvis.packs import PackRegistry

PACKS_DIR = Path(__file__).resolve().parents[1] / "packs"
BASE = [(0.0, 0.0), (6.0, 10.0), (12.0, 0.0), (18.0, -10.0), (24.0, 0.0)]


class _Packs:
    def __init__(self, on: bool) -> None:
        self.on = on

    def is_enabled(self, pack_id: str) -> bool:
        return self.on and pack_id == "animator"


class _Config:
    def __init__(self, root: Path) -> None:
        self.documents_dir = root / "docs"
        self.output_dir = root / "out"


def _track(keys, tangent="smooth", samples=None):
    return {"class": "bezier_float", "scale": 1.0,
            "keys": [[t, v, tangent, tangent, 0.0, 0.0, 0.0, 0.0] for t, v in keys],
            "samples": samples if samples is not None else [offset.linear(keys, f) for f in range(0, 25)]}


def _dump(nodes=3, skipped=()):
    return {"version": 1, "start": 0, "end": 24, "fps": 30,
            "nodes": [{"name": f"Tail{i:02d}", "handle": 100 + i, "tracks": {"rx": _track(BASE), "ry": None}}
                      for i in range(nodes)],
            "skipped": [list(s) for s in skipped]}


# ── 팩 ────────────────────────────────────────────────────────────────────

def test_the_animator_pack_loads_with_its_two_tools(tmp_path: Path) -> None:
    registry = PackRegistry(PACKS_DIR, tmp_path / "data")
    assert "animator" in registry.packs, registry.problems
    pack = registry.packs["animator"]
    assert pack.kind == "code" and list(pack.tools)[:2] == ["anim_offset_read", "anim_offset_plan"]
    assert (pack.root / pack.guide).is_file()


def test_sonjari_own_model_never_sees_the_max_tools(tmp_path: Path) -> None:
    tools = AnimatorTools(_Config(tmp_path), packs=_Packs(True))
    assert tools.active_ollama_tools == []            # 맥스를 부를 손은 클로드 쪽에만 있다
    assert {"anim_offset_read", "anim_offset_plan"} <= {t["function"]["name"] for t in tools.ollama_tools}


def test_a_disabled_pack_refuses(tmp_path: Path) -> None:
    tools = AnimatorTools(_Config(tmp_path), packs=_Packs(False))
    with pytest.raises(PermissionError, match="pack_disabled"):
        tools.offset_read({"start": 0, "end": 24})


# ── 계획: 계산 그대로 ──────────────────────────────────────────────────────

def test_the_plan_writes_exactly_what_offset_chain_computes() -> None:
    plan = build_plan(_dump(3), per_link=4)
    expected = offset.offset_chain([BASE] * 3, 0, 24, per_link=4, whole_frames=True)
    by_node = {tp.node: tp for tp in plan.tracks}
    assert set(by_node) == {"Tail01", "Tail02"}        # 뿌리(늦춤 0)는 다시 쓰지 않는다
    assert plan.unchanged == ["Tail00 rx"]
    for i in (1, 2):
        got = [(k["t"], k["v"]) for k in by_node[f"Tail{i:02d}"].keys]
        assert got == [(t, v) for t, v in expected.keys[i]]
        assert offset.seam_ok(got, 0, 24)


def test_tangent_types_follow_their_keys() -> None:
    dump = _dump(2)
    dump["nodes"][1]["tracks"]["rx"]["keys"][1][2:4] = ["linear", "step"]     # 6프레임 키만 다르게
    plan = build_plan(dump, per_link=3)
    moved = {k["t"]: k for k in plan.tracks[0].keys}
    assert moved[9.0]["in"] == "linear" and moved[9.0]["out"] == "step"        # 6 + 3 = 9 로 옮겨 가도 따라간다
    assert moved[0.0]["in"] == "smooth" and moved[24.0]["in"] == "smooth"       # 이음매는 원래 S 키의 것


def test_the_seam_is_read_from_the_max_samples_not_a_straight_line() -> None:
    # 맥스 곡선은 베지어 — 21 프레임 값이 직선(-5)이 아니라 -7 이라고 맥스가 쟀다
    samples = [offset.linear(BASE, f) for f in range(0, 25)]
    samples[21] = -7.0
    dump = _dump(2)
    dump["nodes"][1]["tracks"]["rx"] = _track(BASE, samples=samples)
    plan = build_plan(dump, per_link=3)
    keys = {k["t"]: k["v"] for k in plan.tracks[0].keys}
    assert keys[0.0] == pytest.approx(-7.0) and keys[24.0] == pytest.approx(-7.0)


def test_shifts_per_link_win_over_per_link() -> None:
    plan = build_plan(_dump(3), per_link=4, shifts=[0, 2, 5])
    assert [tp.shift for tp in plan.tracks] == [2.0, 5.0]


def test_skipped_biped_and_missing_tracks_are_reported() -> None:
    plan = build_plan(_dump(2, skipped=[("Bip001 Spine", "biped")]), per_link=2)
    assert plan.skipped == [("Bip001 Spine", "biped")]
    assert "Tail01 ry" in plan.no_track


def test_keys_outside_the_loop_are_not_rewritten() -> None:
    dump = _dump(2)
    dump["nodes"][1]["tracks"]["rx"]["keys"].append([40.0, 3.0, "smooth", "smooth", 0, 0, 0, 0])
    plan = build_plan(dump, per_link=2)
    assert all(0 <= k["t"] <= 24 for k in plan.tracks[0].keys)
    assert plan.tracks[0].before == 5                 # 쓰기 직전 다시 세는 수 — 구간 안 키만


# ── 맥스 스크립트 ──────────────────────────────────────────────────────────

def _balanced(text: str) -> bool:
    body = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)            # 문자열 안 괄호는 빼고 센다
    body = re.sub(r"--[^\n]*", "", body)
    return body.count("(") == body.count(")")


def test_scripts_have_no_placeholders_and_balanced_parens(tmp_path: Path) -> None:
    read = read_script(tmp_path / "keys.json", 0, 24, ['Tail "01"', "꼬리\\02"])
    plan = build_plan(_dump(2), per_link=2)
    write = apply_script(0, 24, [{"handle": tp.handle, "track": tp.track, "before": tp.before, "keys": tp.keys}
                                 for tp in plan.tracks])
    for text in (read, write):
        assert "__" not in text.replace("__COMMON__", "")
        assert _balanced(text)
    assert '"Tail \\"01\\""' in read and '"꼬리\\\\02"' in read          # 이름의 따옴표 · 역슬래시를 깨지 않는다
    assert 'undo "Sonjari offset loop" on' in write
    assert "#(101, \"rx\", 5, #(" in write


def test_unknown_track_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        read_script(tmp_path / "k.json", 0, 24, [], ["rw"])


# ── 두 걸음 이어서 ─────────────────────────────────────────────────────────

def test_read_then_plan_round_trip(tmp_path: Path) -> None:
    tools = AnimatorTools(_Config(tmp_path), packs=_Packs(True))
    first = tools.offset_read({"start": 0, "end": 24, "nodes": ["Tail00", "Tail01"]})
    read_file = Path(first["read_file"])
    assert (read_file.parent / "read.ms").is_file()
    assert first["run_line"] == run_line(read_file.parent / "read.ms")
    # 맥스가 하는 일을 시험이 대신 한다(BOM 없는 UTF-8)
    read_file.write_text(json.dumps(_dump(2), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="per_link"):
        tools.offset_plan({})                          # 늦춤을 지어내지 않는다
    second = tools.offset_plan({"per_link": 2})       # read_file 을 안 주면 가장 최근 것
    assert second["ok"] and second["tracks_to_write"] == 1
    assert second["preview"][0]["마디"] == "Tail01" and second["preview"][0]["늦춤(프레임)"] == 2.0
    assert (read_file.parent / "apply.ms").is_file() and "apply.ms" in second["run_line"]


def test_plan_will_not_read_outside_its_folder(tmp_path: Path) -> None:
    tools = AnimatorTools(_Config(tmp_path), packs=_Packs(True))
    stray = tmp_path / "elsewhere" / "keys.json"
    stray.parent.mkdir()
    stray.write_text(json.dumps(_dump(2)), encoding="utf-8")
    with pytest.raises(PermissionError):
        tools.offset_plan({"per_link": 2, "read_file": str(stray)})


def test_plan_before_any_read_says_so(tmp_path: Path) -> None:
    tools = AnimatorTools(_Config(tmp_path), packs=_Packs(True))
    with pytest.raises(FileNotFoundError, match="anim_offset_read"):
        tools.offset_plan({"per_link": 2})


def test_first_time_test_scene_is_offered_from_the_real_pack(tmp_path: Path) -> None:
    registry = PackRegistry(PACKS_DIR, tmp_path / "data")
    registry.is_enabled = lambda pack_id: pack_id == "animator"          # type: ignore[method-assign]
    tools = AnimatorTools(_Config(tmp_path), packs=registry)
    first = tools.offset_read({"start": 0, "end": 24})
    line = first["first_time_test"]["run_line"]
    assert "test_chain.ms" in line
    scene = (PACKS_DIR / "animator" / "maxscript" / "test_chain.ms").read_text(encoding="utf-8-sig")
    assert _balanced(scene) and "rotation.controller[3].controller" in scene   # 자식 마디는 곡선에 직접(11-02 맥스 2027 실측)
