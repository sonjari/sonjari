"""다듬은 것 기억하기 · 블렌더 튐 표 — 2026-11-13 · 시험 중.

계기: 현업 애니메이터 11-12 「이건 내가 대화하며 디벨롭할 수밖에」. 설계 docs/설계_애니메이터_블렌더중심_2026-11-13.ko.md §4.

양방향:
- 해야 할 것: 같은 상황 · 같은 손질 두 번째에 한 번 묻기 · 「응」 뒤엔 그 인자를 안 줘도 습관 값으로 · 쓴 습관은 결과에 보임 ·
  엇박자 늦춤도 같은 길 · 블렌더 점검에도 튐 표
- 하면 안 되는 것: 첫 번째에 묻기 · 다른 상황(다른 캐릭터 · 다른 목록)의 같은 값으로 묻기 · 값이 다르면 묻기 · 「아니」 뒤 다시 묻기 ·
  기본값 · 습관으로 채운 값을 손질로 세기 · 사람이 준 인자를 습관이 덮기 · 섞기 없이 섞는 비율 채우기 · 콜드 스타트 습관 파일을 건드리기
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from alture_jarvis.animator import habits, library
from alture_jarvis.animator.fitcheck import BONES
from alture_jarvis.animator_tools import AnimatorTools


class _Packs:
    def is_enabled(self, pack_id: str) -> bool:
        return pack_id == "animator"


class _Config:
    def __init__(self, root: Path) -> None:
        self.documents_dir = root / "docs"
        self.output_dir = root / "out"


def _tools(tmp_path: Path) -> AnimatorTools:
    return AnimatorTools(_Config(tmp_path), packs=_Packs())


def _ready(root: Path, name: str, 목록: str = "공격 모션") -> str:
    e = library.new_entry(root, name=name, origin="own")
    (e["folder"] / "motion.bip").write_bytes(b"BIP")
    (e["folder"] / "max.txt").write_text("start=0 end=30 fps=30 loop=false biped=Bip001", encoding="utf-8")
    ej = e["folder"] / "entry.json"
    data = json.loads(ej.read_text(encoding="utf-8"))
    data["template"] = {"목록": 목록, "상태": "기본 공격", "by": "사람"}
    ej.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return e["id"]


# ── 묻기 ──────────────────────────────────────────────────────────────

def test_asks_only_on_the_second_same_edit(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    a = _ready(t.root, "Hero_Attack_hit")
    first = t.library_apply({"id": a, "character": "시험궁수", "arm_spread": 20})
    assert "habit_ask" not in first
    second = t.library_apply({"id": a, "character": "시험궁수", "arm_spread": 22})          # 폭 ±5° 안 = 같은 손질
    ask = second["habit_ask"]
    assert ask["where"] == "시험궁수 · 공격 모션" and ask["items"][0]["param"] == "arm_spread" and ask["items"][0]["times"] == 2
    assert "남길까요" in ask["ask"] and ask["save_args"] == {"action": "save", "where": "시험궁수 · 공격 모션", "values": {"arm_spread": 22}}


@pytest.mark.parametrize("second", [
    {"character": "다른캐릭", "arm_spread": 20},          # 다른 캐릭터
    {"character": "시험궁수", "arm_spread": 35},          # 값이 다름(폭 밖)
    {"character": "시험궁수"},                            # 손질 안 함(기본값)
])
def test_does_not_ask_for_a_different_situation_value_or_no_edit(tmp_path: Path, second: dict) -> None:
    t = _tools(tmp_path)
    a = _ready(t.root, "Hero_Attack_hit")
    t.library_apply({"id": a, "character": "시험궁수", "arm_spread": 20})
    assert "habit_ask" not in t.library_apply({"id": a, **second})


def test_a_different_template_list_is_a_different_situation(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    atk, idle = _ready(t.root, "A_hit", "공격 모션"), _ready(t.root, "A_idle", "대기 모션")
    t.library_apply({"id": atk, "character": "시험인형", "stride": 0.5})
    assert "habit_ask" not in t.library_apply({"id": idle, "character": "시험인형", "stride": 0.5})


# ── 응 / 아니 ─────────────────────────────────────────────────────────

def test_saved_habit_fills_only_missing_args_and_is_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t = _tools(tmp_path)
    seen: list[dict] = []
    real = library.apply_script
    monkeypatch.setattr(library, "apply_script", lambda *a, **kw: (seen.append(kw), real(*a, **kw))[1])
    a = _ready(t.root, "Hero_Attack_hit")
    t.library_apply({"id": a, "character": "시험인형", "arm_spread": 20, "foot_lock": False})
    ask = t.library_apply({"id": a, "character": "시험인형", "arm_spread": 20, "foot_lock": False})["habit_ask"]
    assert {i["param"] for i in ask["items"]} == {"arm_spread", "foot_lock"}                 # 여럿이면 한 줄로 묶음
    t.habit(ask["save_args"])
    got = t.library_apply({"id": a, "character": "시험인형"})
    assert got["habits_applied"]["arm_spread"] == 20 and got["habits_applied"]["foot_lock"] is False
    assert "habit_ask" not in got                                                             # 습관으로 채운 값은 손질로 안 센다
    assert seen[-1]["arm_spread"] == 20.0 and seen[-1]["foot_lock"] is False                # 값이 실제로 맥스 스크립트까지 간다
    over = t.library_apply({"id": a, "character": "시험인형", "arm_spread": 0})                    # 사람이 준 인자가 이긴다
    assert "arm_spread" not in over["habits_applied"] and over["habits_applied"]["foot_lock"] is False
    assert seen[-1]["arm_spread"] == 0.0


def test_decline_stops_asking_for_that_value(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    a = _ready(t.root, "Hero_Attack_hit")
    t.library_apply({"id": a, "character": "시험인형", "stride": 0.5})
    ask = t.library_apply({"id": a, "character": "시험인형", "stride": 0.5})["habit_ask"]
    t.habit({"action": "decline", "where": ask["where"], "values": {"stride": 0.5}})
    assert "habit_ask" not in t.library_apply({"id": a, "character": "시험인형", "stride": 0.5})
    assert "habits_applied" not in t.library_apply({"id": a, "character": "시험인형"})


def test_blend_habit_is_not_used_without_a_second_motion(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    a, b = _ready(t.root, "A_hit"), _ready(t.root, "B_hit")
    habits.save(t.root, "시험인형 · 공격 모션", {"blend": 0.3})
    assert "habits_applied" not in t.library_apply({"id": a, "character": "시험인형"})
    mixed = t.library_apply({"id": a, "character": "시험인형", "blend_with": b})
    assert mixed["habits_applied"]["blend"] == 0.3 and mixed["blend"]["ratio"] == 0.3


def test_forget_and_list(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    habits.save(t.root, "시험인형 · 공격 모션", {"arm_spread": 20, "stride": 0.5})
    t.habit({"action": "forget", "where": "시험인형 · 공격 모션", "values": {"stride": None}})
    assert t.habit({"action": "list"})["habits"] == {"시험인형 · 공격 모션": {"arm_spread": 20}}
    with pytest.raises(ValueError):
        t.habit({"action": "save", "where": "시험인형 · 공격 모션", "values": {"아무거나": 1}})


def test_cold_start_prefs_file_is_untouched(tmp_path: Path) -> None:
    """콜드 스타트 습관 파일은 「있으면 확인됨」으로 읽힌다 — 이 기능이 그 파일을 만들면 첫 확인 질문이 사라진다."""
    t = _tools(tmp_path)
    a = _ready(t.root, "Hero_Attack_hit")
    for _ in range(2):
        t.library_apply({"id": a, "character": "시험인형", "arm_spread": 20})
    t.habit({"action": "save", "where": "시험인형 · 공격 모션", "values": {"arm_spread": 20}})
    assert not library.prefs_path(t.root).exists()
    assert "habits_unconfirmed" in t.library_apply({"id": a, "character": "시험인형"})


# ── 엇박자 ───────────────────────────────────────────────────────────

def test_offset_per_link_same_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t = _tools(tmp_path)
    where = habits.situation("시험인형", "엇박자")
    assert habits.record(t.root, "anim_offset_plan", where, {"per_link": 2}) is None
    ask = habits.record(t.root, "anim_offset_plan", where, {"per_link": 2})
    assert ask and ask["items"][0]["param"] == "per_link"
    assert habits.record(t.root, "anim_offset_plan", where, {"per_link": 3}) is None        # 늦춤은 값이 똑같아야
    habits.save(t.root, where, {"per_link": 2})
    assert habits.lookup(t.root, where) == {"per_link": 2}


# ── 블렌더 튐 표 ─────────────────────────────────────────────────────

def _rz(deg: float) -> np.ndarray:
    r = math.radians(deg)
    return np.array([[math.cos(r), math.sin(r), 0], [-math.sin(r), math.cos(r), 0], [0, 0, 1.0]])


def _dump(kink: int | None) -> dict:
    frames = []
    for f in range(60):
        row = [f]
        for b in BONES:
            z = {"Head": 160.0, "L Foot": 5.0, "R Foot": 5.0}.get(b, 100.0)
            pos = np.array([2.0 * f, 0.0, z])
            if b == "Pelvis" and f == kink:
                pos = pos + np.array([0, 8.0, 0])
            rot = _rz(3.0 * f)
            row.append([*rot[0], *rot[1], *rot[2], *pos])
        frames.append(row)
    return {"bones": BONES, "frames": frames, "map": {}, "app": "blender"}


@pytest.mark.parametrize("kink,expect", [(30, True), (None, False)])
def test_blender_check_carries_the_jitter_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kink, expect) -> None:
    t = _tools(tmp_path)
    blend = tmp_path / "a.blend"
    blend.write_bytes(b"x")
    monkeypatch.setattr(AnimatorTools, "_blender_read",
                        lambda self, b, a, w: {"info": {"armature": "rig"}, "dump": _dump(kink), "check": {"table": []}})
    out = t.blender_check({"blend": str(blend)})
    where = {r["where"] for r in out["jitter"]["table"]}
    assert ("몸통(골반) 위치" in where) is expect
    assert "시험 중" in out["jitter"]["note"]
    assert "jitter" not in t.blender_check({"blend": str(blend), "jitter": False})
