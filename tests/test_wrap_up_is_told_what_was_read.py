"""정리할 때는 **무엇을 읽었는지**를 다시 알려 준다 — 목표를 다 채운 판만이 아니라 모든 정리에 (2026-09-30 조사 판 9fcbdd0b).

「진전 없음」으로 접힌 조사 판은 앞부분 본문이 창에서 접힌 채(64K · 21번 부름 · 누적 60만 토큰) 정리해
「두 번의 검색에서 2개 확인」이라 답했다 — 실제로는 검색 7번 · 13곳을 읽었다. 장부는 목표를 채운 판에만 붙고 있었다.
시킨 파일이 없으면 「만들었다」고 쓰지 말고 확인한 것을 표로 담게 한다(그 판은 「엑셀로 정리합니다」에서 멈췄다).
"""

from __future__ import annotations

import inspect

from alture_jarvis.agent import BrowserAgent


def test_the_ledger_goes_to_every_wrap_up() -> None:
    source = inspect.getsource(BrowserAgent.run)
    synthesis = source[source.index("확인한 자료를 최종 답변으로 정리하고 있습니다"):]
    synthesis = synthesis[: synthesis.index("final_message, used_thinking = self._text_only_message(")]

    assert "ledger = self._read_ledger_note(steps)" in synthesis
    assert 'if stop_reason == "wrapped_up:goal_met":\n                messages.append(' not in synthesis, "목표를 채운 판에만 주면 안 된다"
    assert "파일은 만들지 못했다" in synthesis
