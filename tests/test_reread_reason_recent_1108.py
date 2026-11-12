"""첫 글자 기다림의 「까닭」을 직전 하나가 아니라 최근 몇 개와 견준다 (2026-11-08 · 맥 첫 걸음 25초).

양방향: 같은 앞부분이 최근에 있었으면 「도구 목록이 달라」가 아니라 「사이에 다른 일이 끼어」 /
처음 보는 모양이면 예전처럼 직전과 견준 까닭 / 직전과 같으면 까닭 없음.
"""

from alture_jarvis.first_token_wait import wait_message
from alture_jarvis.ollama import reread_reason_recent

WORK = ("m", "tools103", "sysA")
SIDE = ("m", "tools4", "sysB")


def test_same_front_seen_recently_is_interleaved_not_tools_changed() -> None:
    assert reread_reason_recent([WORK, SIDE], WORK) == "interleaved"
    assert "끼어들어" in wait_message(24_000, 20, reason="interleaved")


def test_new_shape_still_compares_with_the_previous_call() -> None:
    assert reread_reason_recent([WORK], SIDE) == "both"
    assert reread_reason_recent([WORK], ("m", "tools103", "sysC")) == "system"
    assert reread_reason_recent([WORK], ("other", "tools103", "sysA")) == "model"


def test_same_as_last_has_no_reason_and_empty_is_first() -> None:
    assert reread_reason_recent([SIDE, WORK], WORK) == ""
    assert reread_reason_recent([], WORK) == "first"
