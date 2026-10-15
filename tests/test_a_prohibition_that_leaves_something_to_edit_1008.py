"""「○○ 밖의 파일은 건드리지 마라」는 ○○ 을 고치라는 판이다 (2026-10-08).

우리 숙제 하나를 손자리에게 처음 맡긴 판에서 나왔다. 「SEED 에 여섯을 넣어라 … 걸린 시험을 고쳐라 … 위 세 가지 밖의 파일은
건드리지 마라」를 판 전체 쓰기 금지로 읽어, 손자리가 「이 판은 읽기 전용이라 파일은 수정하지 않고 조사만 하겠습니다」로 갔다.
고치라고 맡긴 일이 읽기 전용이 됐다.

「밖의 · 외의 · 이외의」는 조사로 끝나지만 배경이 아니라 **건드려도 되는 것을 남겨 두는 한정**이다.
운영 요청 1,802개에 옛·새 판정을 대 보니 달라진 것은 그 과제 글 둘뿐이었다.
"""
from __future__ import annotations

import pytest

from alture_jarvis.plan import forbids_writes, write_prohibition_scope


@pytest.mark.parametrize("prompt", [
    "설정 표에 항목 둘을 넣고 걸린 시험을 고쳐라. 위 세 가지 밖의 파일은 건드리지 마라.",
    "app.py 의 버그를 고쳐줘. 그 외의 파일은 수정하지 마.",
    "README 를 다듬어 줘. 이 문서 이외의 파일은 바꾸지 말고.",
])
def test_a_prohibition_on_everything_else_still_lets_the_job_edit(prompt: str) -> None:
    assert write_prohibition_scope(prompt) == "clause"
    assert not forbids_writes(prompt)


@pytest.mark.parametrize("prompt", [
    "이 폴더를 살펴보고 구조를 설명해줘. 파일은 건드리지 마라.",
    "이 판에서는 파일을 수정하지 마. 분석만 해줘.",
    "조사만 해줘. 읽기 전용이다.",
])
def test_a_job_wide_prohibition_is_still_job_wide(prompt: str) -> None:
    assert forbids_writes(prompt)


def test_a_named_target_is_still_a_clause() -> None:
    assert write_prohibition_scope("테스트 파일은 절대 수정하지 마 — 구현을 고쳐야 한다.") == "clause"
