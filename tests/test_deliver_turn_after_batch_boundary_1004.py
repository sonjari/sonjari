"""한 번에 걸음 상한을 넘긴 판도 접기 전에 **파일 쓸 차례**를 받는다 (2026-10-04 레딧 판 5043f5bb).

글 다섯을 166초에 다 읽고, 마지막 응답이 도구 여섯 개를 한꺼번에 불러 상한(28)을 넘겼다. 그 자리의 연장 판정은 0 을
돌려줬고 루프는 `step_cap` 으로 닫혔다 — 접기 전 산출물 차례(09-13)는 루프 맨 위 경계에만 있어서 한 번도 안 돌았다.
모델은 도구 없는 정리에서 「엑셀로 정리합니다」만 말했다. 엑셀 0개.
"""
from __future__ import annotations

import inspect

from alture_jarvis import agent
from alture_jarvis.agent import BrowserAgent


def _post_batch_block() -> str:
    source = inspect.getsource(BrowserAgent.run)
    start = source.index("boundary_results = check_plan(")
    return source[start:source.index("if not stop_reason:", start)]


def test_the_post_batch_boundary_also_gives_the_deliver_turn() -> None:
    block = _post_batch_block()

    assert block.index("if extra > 0:") < block.index("elif (")  # 더 갈 수 있으면 그게 먼저다
    grant = block[block.index("elif ("):]
    assert "not deliver_turn_used" in grant
    assert "_artifact_still_owed(boundary_results, steps)" in grant
    assert "self._sources_read(steps)" in grant  # 읽은 것이 하나도 없으면 쓸 것도 없다
    assert "deliver_turn_used = True" in grant
    assert "step_limit = max(step_limit, len(steps) + 3)" in grant  # 루프가 다시 돈다
    assert '"agent_deliver_before_wrap_up"' in grant
    assert "_DELIVER_TURN_NOTE" in grant


def test_both_boundaries_say_the_same_thing_once() -> None:
    source = inspect.getsource(BrowserAgent.run)

    assert source.count('messages.append({"role": "user", "content": _DELIVER_TURN_NOTE})') == 2
    assert "local_write_document" in agent._DELIVER_TURN_NOTE and "새로 검색·열기를 하지 말고" in agent._DELIVER_TURN_NOTE
