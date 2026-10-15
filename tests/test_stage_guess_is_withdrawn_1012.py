"""되받기가 건 「파일을 만들 차례」를, 모델이 네 번 연달아 거스르면 거둔다 (2026-10-12 밤).

공식 9B · 창 32K 가격 조사 두 판이 같은 모양으로 죽었다. 첫 가게를 읽고 모델이 도구 없이 한마디 하자 되받기와 함께
「파일을 만들 차례」가 걸렸고(계획에 남은 요구가 「파일 만들기」 하나뿐이었다), 값을 못 읽은 모델은 그 화면을 더 보려 했다.
문은 파일이 생길 때까지 안 풀려서 같은 거절을 스무 번 했고, 판은 25걸음 · 가게 하나 · 파일 없음으로 끝났다.

이 시험이 **못** 지키는 것: 문이 풀린 뒤 작은 모델이 나머지 가게로 가는가. 실제 판으로만 본다.
"""
from __future__ import annotations

import inspect

from alture_jarvis import agent
from alture_jarvis.plan_nudges import STAGE_REFUSALS_BEFORE_WITHDRAWING, _stage_guess_failed
from alture_jarvis.stuck_hands import _STAGE_REFUSAL, _STAGE_REFUSALS_BEFORE_NARROWING, _trailing_stage_refusals


def _refused(tool: str) -> dict:
    return {"tool": tool, "ok": False, "error": _STAGE_REFUSAL}


def _ok(tool: str) -> dict:
    return {"tool": tool, "ok": True}


def test_four_refusals_in_a_row_withdraw_the_guess() -> None:
    steps = [_ok("browser_extract"), _refused("browser_page_data"), _refused("browser_read"),
             _refused("browser_extract"), _refused("browser_snapshot")]
    assert _trailing_stage_refusals(steps) == 4
    assert _stage_guess_failed(_trailing_stage_refusals(steps), deliver_turn=False)


def test_it_waits_until_the_narrowed_list_has_also_been_ignored() -> None:
    """거절 두 번 뒤에 목록을 좁히는 장치(09-28)가 먼저다 — 큰 모델은 거기서 따랐다. 그 뒤로도 두 번을 더 본다."""
    assert STAGE_REFUSALS_BEFORE_WITHDRAWING == _STAGE_REFUSALS_BEFORE_NARROWING + 2
    for count in range(STAGE_REFUSALS_BEFORE_WITHDRAWING):
        assert not _stage_guess_failed(count, deliver_turn=False)


def test_a_call_that_went_through_starts_the_count_over() -> None:
    steps = [_refused("browser_open"), _refused("browser_open"), _refused("browser_open"),
             _ok("local_write_document"), _refused("browser_open")]
    assert not _stage_guess_failed(_trailing_stage_refusals(steps), deliver_turn=False)


def test_the_last_turn_before_wrapping_up_is_never_withdrawn() -> None:
    """걸음이 바닥나기 전의 차례(10-02 · 글 여섯을 읽고 더 열기만 한 판)는 그대로다 — 거기서는 못 했다고 적어 내는 것이 맞다."""
    assert not _stage_guess_failed(20, deliver_turn=True)


def test_the_loop_reopens_the_gate_and_records_it() -> None:
    source = inspect.getsource(agent)
    block = source[source.index("_stage_guess_failed(_trailing_stage_refusals(steps), deliver_turn=bool(deliver_turn_used))"):]
    block = block[:block.index("artifact_focus = _artifact_turn_is_due(")]
    assert 'plan_pushbacks_by_stage["artifact"] = 0' in block, "되받은 횟수를 돌려 문을 푼다 — 다시 말만 하면 되받기가 또 건다"
    assert '"agent_stage_withdrawn"' in block and "self.store.add_audit(" in block
    # 문을 푸는 판정은 차례를 정하는 줄 **앞**에 있어야 그 걸음부터 풀린다.
    before = source[:source.index("artifact_focus = _artifact_turn_is_due(")]
    assert "_stage_guess_failed(" in before[-2_000:]
