"""첫 글자 기다림의 「까닭」을 직전 하나가 아니라 최근 몇 개와 견준다 (2026-11-08 · 맥 첫 걸음 25초).

양방향: 같은 앞부분이 최근에 있었으면 「도구 목록이 달라」가 아니라 사이에 낀 것을 말한다 /
처음 보는 모양이면 예전처럼 직전과 견준 까닭 / 직전과 같으면 까닭 없음.

★ 2026-11-13 대표 「왜 계속 사이에 일이 끼어든다는 말이 나오노」 — 맥 Strata 부르기 160번 중 146번은 다른 일이 아니라
  손자리 자신의 짧은 확인 · 도구 목록 바꿈이었다. 「다른 기기의 일이 끼어」는 다른 기기의 부르기가 **실제로 들어왔을 때만**.
"""

from alture_jarvis.first_token_wait import wait_message
from alture_jarvis.ollama import reread_reason_recent

WORK = ("m", "tools103", "sysA")
SIDE = ("m", "tools4", "sysB")
NARROW = ("m", "tools49", "sysA")


def test_after_our_own_short_check_says_so_not_another_job() -> None:
    reason = reread_reason_recent([WORK, SIDE], WORK, last_small=True)
    assert reason == "side_call"
    text = wait_message(24_000, 20, reason=reason)
    assert "짧게 확인한 뒤라" in text and "끼어" not in text


def test_returning_after_another_work_call_names_what_really_differs() -> None:
    reason = reread_reason_recent([WORK, NARROW], WORK)
    assert reason == "tools"
    assert "끼어" not in wait_message(24_000, 20, reason=reason)
    # 도구는 같고 지침만 달랐으면 「지침」이라고 한다(PC 기록 57번)
    assert reread_reason_recent([WORK, ("m", "tools103", "sysOld")], WORK) == "system"


def test_another_device_only_when_its_call_really_came_in() -> None:
    assert reread_reason_recent([WORK], WORK, outside=True) == "interleaved"
    assert reread_reason_recent([WORK, SIDE], WORK, last_small=True, outside=True) == "interleaved"
    assert "다른 기기의 일이 사이에 끼어들어" in wait_message(24_000, 20, reason="interleaved")
    # 다른 기기 표시가 없으면 어떤 모양이어도 「끼어」라고 하지 않는다
    for recent, current in (([WORK, SIDE], WORK), ([WORK, NARROW], WORK), ([WORK], WORK), ([SIDE], WORK)):
        for small in (False, True):
            assert reread_reason_recent(recent, current, last_small=small) != "interleaved"


def test_folded_has_its_own_words() -> None:
    assert "지난 기록을 접어서" in wait_message(24_000, 20, reason="folded")
    assert "folded" in wait_message(24_000, 20, english=True, reason="folded")


def test_new_shape_still_compares_with_the_previous_call() -> None:
    assert reread_reason_recent([WORK], SIDE) == "both"
    assert reread_reason_recent([WORK], ("m", "tools103", "sysC")) == "system"
    assert reread_reason_recent([WORK], ("other", "tools103", "sysA")) == "model"


def test_same_as_last_has_no_reason_and_empty_is_first() -> None:
    assert reread_reason_recent([SIDE, WORK], WORK) == ""
    assert reread_reason_recent([], WORK) == "first"


def test_the_short_check_itself_gets_no_wrong_reason() -> None:
    # 일하던 부르기 뒤에 짧은 확인이 예전 모양으로 돌아와도 「도구 목록이 바뀌었다 돌아와」라고 하지 않는다(맥 기록 46번)
    assert reread_reason_recent([SIDE, WORK], SIDE, current_small=True) == ""
    assert reread_reason_recent([SIDE, WORK], SIDE) == "both"
