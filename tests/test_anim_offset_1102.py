"""엇박자 루프 참조 구현 시험 (2026-11-02 · 게임 애니메이션 팩 설계 §3-2).

맥스 스크립트는 이 계산과 1:1 로 대조한다 — 여기서 틀리면 맥스에서도 틀린다.
"""
from __future__ import annotations

import pytest

from alture_jarvis.animator import offset as ao

# 0~24 프레임 루프 · 0, 6, 12, 18 에 키 · 24 는 이음매(0 과 같은 값)
BASE = [(0.0, 0.0), (6.0, 10.0), (12.0, 0.0), (18.0, -10.0), (24.0, 0.0)]


def test_no_offset_keeps_the_curve() -> None:
    r = ao.offset_chain([BASE], 0, 24, per_link=2)
    assert r.keys[0] == BASE                     # 뿌리(마디 0)는 늦춤 0
    assert r.reports[0].wrapped == 0


def test_each_link_is_delayed_and_wrapped() -> None:
    r = ao.offset_chain([BASE, BASE, BASE], 0, 24, per_link=4)
    times = [[t for t, _ in k] for k in r.keys]
    assert times[1] == [0.0, 4.0, 10.0, 16.0, 22.0, 24.0]     # 18+4=22 · 이음매 0/24 새로
    assert times[2] == [0.0, 2.0, 8.0, 14.0, 20.0, 24.0]      # 18+8=26 → 2 로 감김
    assert r.reports[2].wrapped == 1


def test_seam_value_comes_from_the_original_curve() -> None:
    r = ao.offset_chain([BASE, BASE], 0, 24, per_link=3)
    # 마디 1 의 0 프레임 값 = 원래 곡선의 -3(=21) 프레임 값 = -10→0 사이 반 = -5
    assert r.reports[1].seam_value == pytest.approx(-5.0)
    assert ao.seam_ok(r.keys[1], 0, 24)


def test_every_link_closes_the_loop() -> None:
    r = ao.offset_chain([BASE] * 6, 0, 24, per_link=1.5)
    assert all(ao.seam_ok(k, 0, 24) for k in r.keys)


def test_a_full_loop_of_delay_is_the_same_curve() -> None:
    r = ao.offset_chain([BASE, BASE], 0, 24, per_link=24)
    assert [round(v, 6) for _, v in r.keys[1]] == [round(v, 6) for _, v in BASE]


def test_keys_outside_the_loop_are_left_alone() -> None:
    keys = [(-5.0, 3.0)] + BASE + [(30.0, 7.0)]
    r = ao.offset_chain([keys, keys], 0, 24, per_link=4)
    assert (-5.0, 3.0) in r.keys[1] and (30.0, 7.0) in r.keys[1]
    assert r.reports[1].outside == 2


def test_a_pure_shift_never_collides() -> None:
    # 구간 안 키를 같은 만큼 밀고 감는 건 일대일이라 겹칠 수 없다 — 겹침 칸은 맥스 쪽 서브프레임 반올림 대비로만 남긴다
    keys = [(0.0, 0.0), (10.0, 5.0), (22.0, 9.0), (24.0, 0.0)]
    r = ao.offset_chain([keys, keys], 0, 24, per_link=12)   # 10+12=22 · 22+12=34→10 — 겹침 없음
    assert r.reports[1].collisions == 0
    keys2 = [(0.0, 0.0), (2.0, 1.0), (14.0, 2.0), (24.0, 0.0)]
    r2 = ao.offset_chain([keys2, keys2], 0, 24, per_link=12)  # 2+12=14 · 14+12=26→2 · 0+12=12 — 겹침 없음
    assert r2.reports[1].collisions == 0


def test_whole_frames_rounds_the_delay() -> None:
    r = ao.offset_chain([BASE, BASE, BASE], 0, 24, per_link=1.4, whole_frames=True)
    assert [x.shift for x in r.reports] == [0.0, 1.0, 3.0]


def test_empty_link_and_bad_range() -> None:
    r = ao.offset_chain([BASE, []], 0, 24, per_link=2)
    assert r.keys[1] == []
    with pytest.raises(ValueError):
        ao.offset_chain([BASE], 10, 10, per_link=2)


def test_preview_rows_say_what_changes() -> None:
    rows = ao.preview_rows(ao.offset_chain([BASE, BASE], 0, 24, per_link=8))
    # 0·6·12·18 에 8 늦춤 → 8·14·20·26(→2) — 감기는 건 18 하나(24 이음매 키는 늦추기 전에 뺀다)
    assert rows[1]["늦춤(프레임)"] == 8 and rows[1]["감긴 키"] == 1
