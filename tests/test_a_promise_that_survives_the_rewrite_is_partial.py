"""다시 써도 예고로 끝난 답은 완료가 아니다 (2026-10-02 공개 전 필수 ④, 운영 판 52017231).

답이 「Perplexity 개인용 요금제 페이지가 404입니다. 홈페이지에서 개인 요금제 링크를 찾아보겠습니다.」 한 줄이었는데
`wrapped_up:goal_met`·`complete` 로 찍혔다. 마지막 관문이 한 번 다시 쓰게 했지만 다시 쓴 답도 예고라 원래 예고가 그대로 나갔다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis import agent as agent_mod
from alture_jarvis.agent import _PROMISE_ONLY_NOTE, _only_a_promise

SAID = "Perplexity 개인용 요금제 페이지가 404입니다. 홈페이지에서 개인 요금제 링크를 찾아보겠습니다."
SOURCE = Path(agent_mod.__file__).read_text(encoding="utf-8")


def test_the_real_line_is_a_promise_and_the_note_is_not() -> None:
    assert _only_a_promise(SAID)
    assert "실행되지 않았습니다" in _PROMISE_ONLY_NOTE


def test_a_surviving_promise_is_marked_and_counted_partial() -> None:
    gate = SOURCE.index('"agent_final_promise_rewrite"')
    flag = SOURCE.index("ended_on_promise = bool(answer and steps and not forced_commits and _only_a_promise(answer))")
    assert gate < flag, "예고 판정은 마지막 다시 쓰기 **뒤**의 답을 봐야 한다"
    # 알림은 요청 언어를 따른다(2026-10-03 — 영어 답에 한국어 알림이 붙었다). 한국어·영어 알림 둘 다 답에 붙는 자리에 있어야 한다.
    assert "_PROMISE_ONLY_NOTE_EN if _english.english_dominant" in SOURCE and "else _PROMISE_ONLY_NOTE)" in SOURCE
    # 2026-10-08: 우리가 센 미달(`harness_shortfall`)이 같은 줄에 들어왔다 — 예고로 끝난 판이 일부라는 뜻은 그대로다.
    assert "if remaining_answer_conflict or reported_shortfall or harness_shortfall or ended_on_promise:" in SOURCE
