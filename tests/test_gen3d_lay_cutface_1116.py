"""나눈 부품은 자른 면을 판에 대는 쪽을 먼저 본다 (2026-11-16 리락쿠마 머리).

머리가 받침이 조금 적다고(옆 444 대 자른 면 532mm²) 옆으로 눕혀져 얼굴이 옆을 봤다(대표 「얼굴이 왜 돌아가 있노 · 꼭 고쳐야」).
자른 면은 평평하고 조립하면 가려지는 면이다 — 받침이 크게 늘지 않으면 자른 면을 판에 댄다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alture_jarvis.gen3d import assembly  # noqa: E402


def _opt(score: float, kind: int, name: str) -> tuple:
    return (score, kind, name, None, score)


def test_head_case_prefers_the_cut_face_when_overhang_is_close() -> None:
    options = [_opt(532.0, 0, "자른 면 1 을 판에"), _opt(444.0, 1, "왼쪽으로 눕힘"), _opt(531.9, 1, "지금 그대로")]
    assert assembly.pick_lay(options)[2] == "자른 면 1 을 판에"


def test_far_worse_cut_face_still_loses() -> None:
    """반례: 자른 면 쪽 받침이 훨씬 크면(쓰러질 벌점 등) 예전처럼 가장 좋은 방향."""
    options = [_opt(2000.0, 0, "자른 면 1 을 판에"), _opt(400.0, 1, "앞으로 눕힘")]
    assert assembly.pick_lay(options)[2] == "앞으로 눕힘"


def test_cut_face_already_best_and_no_cut_face_are_unchanged() -> None:
    assert assembly.pick_lay([_opt(210.0, 0, "자른 면 1 을 판에"), _opt(400.0, 1, "지금 그대로")])[2] == "자른 면 1 을 판에"
    assert assembly.pick_lay([_opt(300.0, 1, "거꾸로"), _opt(250.0, 1, "지금 그대로")])[2] == "지금 그대로"
