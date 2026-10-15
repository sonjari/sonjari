"""밤 벤치의 판정 — 언제 알리고 언제 조용히 넘어가나 (2026-09-18)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _nightly():
    spec = importlib.util.spec_from_file_location("nightly_site_bench", ROOT / "scripts" / "nightly_site_bench.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _night(**tasks: bool | None) -> dict:
    base = {"ms_search": True, "ms_detail": True, "wa_search": True, "yes24_ctrl": True}
    return {"tasks": {**base, **tasks}}


def test_a_clean_night_is_quiet() -> None:
    assert _nightly().judge([_night(), _night()]) == []


def test_one_wobble_is_not_an_alarm() -> None:
    """판마다 편차는 이 저장소의 실측이다 — 한 번 틀린 것으로 사람을 깨우지 않는다."""
    assert _nightly().judge([_night(), _night(yes24_ctrl=False)]) == []


def test_the_same_task_failing_two_nights_in_a_row_alerts() -> None:
    reasons = _nightly().judge([_night(yes24_ctrl=False), _night(yes24_ctrl=False)])
    assert any("이틀 연속" in reason and "yes24_ctrl" in reason for reason in reasons)


def test_half_of_the_tasks_failing_in_one_night_alerts() -> None:
    reasons = _nightly().judge([_night(), _night(ms_search=False, wa_search=False)])
    assert any("2/4" in reason for reason in reasons)


def test_a_bench_that_measured_nothing_is_not_read_as_passing() -> None:
    """「못 쟀다」를 「통과」로 읽지 않는다."""
    reasons = _nightly().judge([_night(ms_search=None, ms_detail=None, wa_search=None, yes24_ctrl=None)])
    assert reasons and "못 쟀" in reasons[0]


def test_unmeasured_tasks_are_not_counted_as_failures() -> None:
    assert _nightly().judge([_night(), _night(wa_search=None)]) == []
