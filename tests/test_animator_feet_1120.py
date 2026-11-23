"""애니메이터 팩 — 현업 사용기 11-20 덧붙임 ①②③: 발 구간 고정 · 몸만 옮기기 · COM 앞섬 표(2026-11-23).

계기: 입힌 26프레임 동작의 4프레임에서 COM 이 두 발 중간보다 약 24 앞. COM 키만 밀면 발이 끌려와 그대로였고,
「두 발을 0프레임 위치 · 회전 그대로 0~4프레임에 유지」로 약 1 이 되어 사람이 맞다고 했다.
시험 자료 이름은 지어낸 것이다.

양방향:
- 해야 할 것: hold_feet 구간마다 sjHoldFeet · com_shift 마다 sjComShift(뒤로 · 월드 이동) · 발 고정 뒤 · 키 남기기 전 ·
  COM 앞섬 표는 맨 끝 · 도구는 앞섬 표가 기본으로 켜짐 · 결과에 feet_fix
- 하면 안 되는 것: 아무것도 안 주면 옛 스크립트 그대로 · 구간 밖 · 뒤집힌 구간 · 숫자 아님 · 옮길 거리 0 이면 만들지 않음(일부만 하지 않음)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.animator import library
from alture_jarvis.animator.specs import LIBRARY_APPLY
from alture_jarvis.animator_tools import AnimatorTools


class _Packs:
    def is_enabled(self, pack_id: str) -> bool:
        return pack_id == "animator"


class _Config:
    def __init__(self, root: Path) -> None:
        self.documents_dir = root / "docs"
        self.output_dir = root / "out"


def _script(**kw) -> str:
    return library.apply_script(Path("C:/lib/x/motion.bip"), "Bip001", "x", (0, 26), **kw)


def _ready(root: Path, name: str, frames=(0, 26)) -> str:
    e = library.new_entry(root, name=name, origin="own")
    (e["folder"] / "motion.bip").write_bytes(b"BIP")
    (e["folder"] / "max.txt").write_text(f"start={frames[0]} end={frames[1]} fps=30 loop=false loopgap=0.1 biped=Bip001", encoding="utf-8")
    return e["id"]


def _last_ms(root: Path, eid: str) -> str:
    return sorted((library.lib_dir(root) / eid).glob("apply_*.ms"))[-1].read_text(encoding="utf-8")


def test_hold_feet_and_com_shift_run_after_foot_lock_and_before_trim() -> None:
    ms = _script(keep_keys=[0, 4, 26], hold_feet=[(0, 4)],
                 com_shift=[{"from": 4, "to": 4, "back": 16.0, "move": [0, 0, 0]}], com_report=True)
    assert "(sjHoldFeet com 0 4)" in ms
    assert "(sjComShift com 4 4 [0.000, 0.000, 0.000] 16.000)" in ms
    # 차례: 발 고정 → 몸 옮기기 → 발 구간 고정 → 키 남기기 → 앞섬 표(지운 뒤 모양)
    order = ["(sjFootLock com", "(sjComShift com", "(sjHoldFeet com", "(sjTrimKeys com", "(sjComLead com"]
    idx = [ms.index(o) for o in order]
    assert idx == sorted(idx)
    assert ms.count("(") == ms.count(")")
    # 발은 시작 프레임의 월드 변환으로 · 회전까지
    assert "local ref = for n in feet collect (at time a n.transform)" in ms
    assert "biped.setTransform n #rotation tm.rotation true" in ms
    # 11-23 맥스 실측: 원래 키 자리에만 박으면 키 사이로 샐 수 있어 구간 모든 프레임에 · 다리가 안 닿으면 그 까닭을 말한다
    assert ms.count("local ts = for f = a to b collect f") == 2              # 발 구간 고정 · 몸 옮기기 둘 다
    assert "다리가 발 자리에 안 닿음" in ms and '" Thigh"' in ms


def test_nothing_given_keeps_the_old_script() -> None:
    plain = _script()
    for name in ("sjHoldFeet", "sjComShift", "sjComLead", "sjFootDir"):
        assert name not in plain


def test_raw_still_does_what_the_person_pointed_at() -> None:
    ms = _script(raw=True, hold_feet=[(0, 4)])
    assert "(sjHoldFeet com 0 4)" in ms and "(sjFootLock com" not in ms


def test_back_direction_is_heel_to_toe_like_the_balance_check() -> None:
    ms = _script(com_shift=[{"from": 2, "to": 5, "back": 10.0, "move": [1, 0, 0]}])
    assert '" Toe0"' in ms and "d = d + ax * (0.0 - back)" in ms
    assert "(sjComShift com 2 5 [1.000, 0.000, 0.000] 10.000)" in ms
    assert "발 어긋남 최대" in ms                                          # 되돌린 뒤 발이 얼마나 어긋났나를 스스로 잰다


def test_frame_spans_accept_and_reject() -> None:
    assert library.frame_spans([[0, 4]], 0, 26) == [(0, 4)]
    assert library.frame_spans([0, 4], 0, 26) == [(0, 4)]                # 한 구간만 준 것
    assert library.frame_spans([[3, 3], [10.4, 12]], 0, 26) == [(3, 3), (10, 12)]
    assert library.frame_spans(None) == []
    for bad in ([[4, 0]], [[0, 30]], [[-1, 2]], [["a", 2]], [[1, 2, 3]], "0~4", [[True, 4]]):
        with pytest.raises(ValueError):
            library.frame_spans(bad, 0, 26)


def test_com_shifts_accept_and_reject() -> None:
    got = library.com_shifts({"from": 4, "back": 16}, 0, 26)
    assert got == [{"from": 4, "to": 4, "back": 16.0, "move": [0.0, 0.0, 0.0]}]
    assert library.com_shifts([{"from": 1, "to": 3, "move": [0, 2, 0]}])[0]["move"] == [0.0, 2.0, 0.0]
    for bad in ([{"from": 4}], [{"from": 4, "back": 0}], [{"from": 4, "back": "뒤"}], [{"from": 40, "back": 5}],
                [{"from": 4, "move": [1, 2]}], ["4 back 16"], 5):
        with pytest.raises(ValueError):
            library.com_shifts(bad, 0, 26)


def test_tool_passes_everything_and_reports_by_default(tmp_path: Path) -> None:
    t = AnimatorTools(_Config(tmp_path), packs=_Packs())
    eid = _ready(t.root, "Mage_Skill_special")
    out = t.library_apply({"id": eid, "hold_feet": [[0, 4]], "com_shift": [{"from": 4, "to": 4, "back": 16}]})
    assert out["feet_fix"]["hold_feet"] == [[0, 4]] and out["feet_fix"]["com_shift"][0]["back"] == 16.0
    ms = _last_ms(t.root, eid)
    assert "(sjHoldFeet com 0 4)" in ms and "(sjComShift com 4 4" in ms and "(sjComLead com" in ms
    # 앞섬 표는 기본 켜짐 · 끌 수 있다 · 발 손질 없이 입히면 feet_fix 없음
    plain = t.library_apply({"id": eid})
    assert "feet_fix" not in plain and "(sjComLead com" in _last_ms(t.root, eid)
    t.library_apply({"id": eid, "com_report": False})
    assert "sjComLead" not in _last_ms(t.root, eid)


def test_tool_makes_nothing_when_one_span_is_wrong(tmp_path: Path) -> None:
    t = AnimatorTools(_Config(tmp_path), packs=_Packs())
    eid = _ready(t.root, "Mage_Skill_special")
    before = list((library.lib_dir(t.root) / eid).glob("apply_*.ms"))
    with pytest.raises(ValueError):
        t.library_apply({"id": eid, "hold_feet": [[0, 4], [20, 40]]})
    with pytest.raises(ValueError):
        t.library_apply({"id": eid, "com_shift": [{"from": 4, "to": 2, "back": 5}]})
    assert list((library.lib_dir(t.root) / eid).glob("apply_*.ms")) == before


def test_schema_has_the_three_new_arguments() -> None:
    props = LIBRARY_APPLY["function"]["parameters"]["properties"]
    for k in ("hold_feet", "com_shift", "com_report"):
        assert k in props
