# -*- coding: utf-8 -*-
"""입힌 뒤 균형 점검 · 키 정렬 · 원본 그대로 입히기 (2026-11-19 · lab 스크립트를 팩으로).

- 점검 · 키 정렬 스크립트는 lab 원본을 그대로 쓰고 인자(바이페드 · 기준 숫자 · 구간)만 바꿔 끼운다.
- 키 정렬 적용은 복사본 저장 → Hold 순서이고, 매 프레임 키 경고가 붙는다. 제안(기본)은 장면을 안 바꾼다.
- raw 입히기는 무게중심 맞춤 · 첫끝 덮기 · 발 고정을 부르지 않는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.animator import balance, library
from alture_jarvis.animator_tools import AnimatorTools


class _Packs:
    def is_enabled(self, pack_id: str) -> bool:
        return pack_id == "animator"


class _Config:
    def __init__(self, root: Path) -> None:
        self.documents_dir = root / "docs"
        self.output_dir = root / "out"


def _balanced(t: str) -> bool:
    return t.count("(") == t.count(")")


def test_the_check_script_keeps_all_five_checks_and_reads_only() -> None:
    t = balance.check_script()
    for mark in ("== ① COM 앞뒤", "== ② 홀딩", "== ③ 애매하게 뜬 발", "== ④ 좌우 균형", "== ⑤ 키 정렬", "== 요약"):
        assert mark in t
    # 읽기 전용: 장면을 바꾸는 호출이 없다
    for writer in ("setTransform", "holdMaxFile", "saveMaxFile", "addNewKey", "deleteKey"):
        assert writer not in t
    assert _balanced(t)


def test_the_check_script_takes_biped_thresholds_and_range() -> None:
    t = balance.check_script("Bip002", 10, 40, {"fwdTol": 20, "slideMinFrames": 4, "slideRatio": 0.15})
    assert 'local bipName = "Bip002"' in t
    assert "local fwdTol = 20" in t and "local slideMinFrames = 4" in t and "local slideRatio = 0.15" in t
    assert "local fS = 10; local fE = 40" in t
    assert "animationRange.start.frame as integer; local fE" not in t
    # 안 준 기준은 lab 기본값 그대로
    assert "local latTol = 15.0" in t


def test_the_check_script_refuses_unknown_thresholds_and_bad_ranges() -> None:
    with pytest.raises(ValueError, match="모르는 기준"):
        balance.check_script(thresholds={"latTolerance": 3})
    with pytest.raises(ValueError, match="end"):
        balance.check_script(start=40, end=10)


def test_a_quote_in_the_biped_name_cannot_break_the_script() -> None:
    t = balance.check_script('Bip001" ; deleteFile "x')
    assert 'deleteFile "x' not in t and 'local bipName = "Bip001 ; deleteFile x"' in t


def test_key_align_proposes_by_default_and_never_saves() -> None:
    t = balance.align_script()
    assert "local doApply = false" in t
    assert "saveMaxFile" not in t and "★ 경고" not in t
    assert _balanced(t)


def test_key_align_apply_saves_a_copy_before_hold_and_warns_on_every_frame_keys() -> None:
    t = balance.align_script("Bip001", apply=True, backup=Path(r"C:\work\before.max"))
    assert "local doApply = true" in t
    assert t.index("saveMaxFile bkPath") < t.index("    holdMaxFile()" + chr(10))
    assert 'local bkPath = "C:/work/before.max"' in t
    assert "★ 경고" in t and "복사본: " in t
    assert _balanced(t)
    with pytest.raises(ValueError, match="복사본"):
        balance.align_script(apply=True)


def test_the_lab_scripts_carry_no_personal_names() -> None:
    for p in balance.HERE.glob("*.ms"):
        text = p.read_text(encoding="utf-8")
        for name in ("사용자", "사용자", "지인 개발자", "사용자님"):
            assert name not in text, (p.name, name)


def test_the_tools_write_a_script_and_hand_back_one_line(tmp_path: Path) -> None:
    tools = AnimatorTools(_Config(tmp_path), packs=_Packs())
    out = tools.balance_check({"start": 0, "end": 30, "thresholds": {"fwdTol": 22}})
    assert out["changes_scene"] is False and out["thresholds_used"]["fwdTol"] == 22
    script = Path(out["run_line"].split('@"', 1)[1].rstrip('")'))
    assert script.is_file() and "local fwdTol = 22" in script.read_text(encoding="utf-8-sig")
    plan = tools.key_align({})
    assert plan["apply"] is False and "backup" not in plan
    done = tools.key_align({"apply": True})
    assert done["changes_scene"] is True and done["backup"].endswith(".max")
    text = Path(done["run_line"].split('@"', 1)[1].rstrip('")')).read_text(encoding="utf-8-sig")
    assert Path(done["backup"]).as_posix() in text


def test_raw_apply_skips_com_match_bookend_and_foot_lock(tmp_path: Path) -> None:
    raw = library.apply_script(tmp_path / "m.bip", label="x", frames=(0, 30), raw=True, stride=0.5, arm_spread=30)
    assert "local comNote = sjComMatch" not in raw
    calls = ("(sjBookend com cap (animationRange", "(sjFootLock com footSpans", "sjBodyFit com (animationRange", "sjFootSpans com (animationRange")
    assert not any(c in raw for c in calls)
    assert "원본 그대로" in raw and "#retargetHeight" in raw and "holdMaxFile()" in raw
    plain = library.apply_script(tmp_path / "m.bip", label="x", frames=(0, 30))
    assert "local comNote = sjComMatch" in plain and "(sjBookend com cap (animationRange" in plain and "(sjFootLock com footSpans" in plain


def test_apply_saves_a_copy_before_hold_when_given_a_path(tmp_path: Path) -> None:
    t = library.apply_script(tmp_path / "m.bip", label="x", frames=(0, 30), backup=Path(r"C:\work\before_apply.max"))
    assert t.index("saveMaxFile bkPath") < t.index("  holdMaxFile()" + chr(10))
    assert 'local bkPath = "C:/work/before_apply.max"' in t and "bkNote" in t
    assert _balanced(t)
    assert "saveMaxFile" not in library.apply_script(tmp_path / "m.bip", label="x", frames=(0, 30))
