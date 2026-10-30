"""「아직 안 했다」(I have not … yet)도 못 다 했다는 자백이다 (2026-10-30 · 판 eba156fb 가 answered 로 나감).

「yet」이 붙은 꼴만 — 「I have not logged in or paid」(시킨 대로 안 한 것)는 자백이 아니다.
운영 영어 답 3,543개에 대 봄: 새로 걸림 2 · 둘 다 실제로 못 한 판(하나는 이미 일부).
"""

from __future__ import annotations

import pytest

from alture_jarvis.answer_gate import _ADMITS_NOT_DONE_EN


@pytest.mark.parametrize("answer", [
    "I have not set the dates, guests, filter, or opened any listings yet.",
    "I haven't completed the core task yet.",
])
def test_not_yet_is_an_admission(answer: str) -> None:
    assert _ADMITS_NOT_DONE_EN.search(answer)


@pytest.mark.parametrize("answer", [
    "I have not logged in or paid, as requested.",
    "I did not log in, enter any personal details, or pay.",
    "I haven't changed anything on your account.",
])
def test_holding_back_as_asked_is_not(answer: str) -> None:
    assert not _ADMITS_NOT_DONE_EN.search(answer)
