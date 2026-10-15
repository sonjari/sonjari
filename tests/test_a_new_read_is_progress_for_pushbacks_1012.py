"""되받기의 「진전 없음」은 그 사이에 새로 읽은 곳도 본다 (2026-10-12).

공식 9B · 창 32K 가격 조사 여섯 판 중 넷이 10~12걸음에서 `model_stopped_early`(되받기 1번)로 끝났다. 9B 는 걸음 사이에
「이제 ○○를 확인하겠습니다」처럼 말만 한다. 한 번 되받자 다음 가게를 읽었는데, 「남은 것」을 계획의 요구로만 봐서 —
그 판의 요구는 「파일 만들기」 하나뿐이다 — 두 번째에는 「진전 없음」으로 판정돼 되받지 않고 판이 닫혔다.
같은 조건의 4B 는 말없이 손을 움직여 여섯 판 모두 끝까지 갔다.
"""
from __future__ import annotations

import inspect

from alture_jarvis import agent
from alture_jarvis.plan_nudges import _pushback_stalled, _read_more_since

UNMET = (("실제 산출물 파일 만들기", "열 수 있는 산출물 없음"),)


def test_reading_one_more_shop_since_the_last_pushback_is_progress() -> None:
    # 처음 되받을 때 — 지난 되받기가 없다.
    assert not _read_more_since(1, None)
    assert not _pushback_stalled(UNMET, None, read_more=False)
    # 되받은 뒤 가게를 하나 더 읽고 또 말만 했다 — 남은 요구는 같지만 진전이다.
    assert _read_more_since(2, 1)
    assert not _pushback_stalled(UNMET, UNMET, read_more=True)


def test_the_rule_still_stops_the_job_that_reads_nothing_new() -> None:
    """09-30 의 그 판 — 채울 수 없는 요구를 두고 자기 파일만 다시 읽었다. 새로 읽은 곳이 없으면 예전 그대로 「진전 없음」."""
    assert not _read_more_since(2, 2) and not _read_more_since(1, 2)
    assert _pushback_stalled(UNMET, UNMET, read_more=False)
    # 남은 요구가 바뀌었으면 읽은 것이 없어도 진전이다(예전 그대로).
    other = (("근거가 되는 대상 실제로 읽기", "0개"),)
    assert not _pushback_stalled(UNMET, other, read_more=False)
    # 남은 것이 없으면 판정할 것이 없다.
    assert not _pushback_stalled((), (), read_more=False)


def test_the_loop_counts_reads_and_does_not_charge_a_pushback_that_followed_a_new_read() -> None:
    source = inspect.getsource(agent)
    block = source[source.index("reads_now = len(self._sources_actually_read(steps))"):]
    block = block[:block.index('"agent_plan_pushback",')]
    assert "read_more = _read_more_since(reads_now, pushback_reads_seen.get(pushback_stage))" in block
    assert "stalled = _pushback_stalled(unmet_now, pushback_unmet_seen.get(pushback_stage), read_more=read_more)" in block
    assert "(plan_pushbacks_by_stage.get(pushback_stage, 0) < _PLAN_PUSHBACK_LIMIT or read_more)" in block
    assert "pushback_reads_seen[pushback_stage] = reads_now" in block
    assert "if not read_more:" in block, "새로 읽고 온 판의 되받기는 횟수에 넣지 않는다"
    # 끝을 내는 것은 그대로다 — 걸음 한도와 시간.
    assert "and len(steps) + 2 <= step_limit" in block and "and time.monotonic() < deadline" in block
