"""조건 숫자는 읽을 개수가 아니다 — 부정 · 조사가 끼어도 (2026-10-21 새벽 HN 세기 판).

「글이 30개 안 되는 칸은 「표본 적음」으로 표시해 줘」가 「30개 이상 직접 열어 읽기」가 됐다. 운영 요청 2,479개에
옛 · 새 판정을 나란히 돌려 바뀐 것은 그 판 하나뿐이었다(진짜 요구를 잃은 판 0).
"""

from __future__ import annotations

import pytest

from alture_jarvis.answer_gate import named_sources
from alture_jarvis.plan import extract


def _kinds(text: str) -> list[tuple[str, object]]:
    compact = " ".join(text.split())
    return [(item.kind, item.target) for item in extract(text, has_named_source=bool(named_sources(compact)))]


@pytest.mark.parametrize("text", [
    "Show HN 글을 요일별로 세어서 엑셀로 정리해 줘. 글이 30개 안 되는 칸은 「표본 적음」으로 표시해 줘.",
    "가격을 표로 정리해 줘. 리뷰가 5개가 안 되는 상품은 회색으로 칠해 줘.",
    "목록을 엑셀로 만들어 줘. 댓글이 10개 못 되는 글은 빼 줘.",
    "사람인 공고를 표로 정리해 줘. 지원자가 20개가 넘는 공고는 따로 표시해 줘.",
])
def test_a_threshold_with_a_negation_or_particle_is_not_a_read_count(text: str) -> None:
    assert not [kind for kind, _ in _kinds(text) if kind == "count"]


@pytest.mark.parametrize(("text", "target"), [
    ("사람인 공고 30개 이상 찾아서 표로 줘.", 30),
    ("쿠팡에서 무선 마우스 5개 찾아서 엑셀로 정리해 줘.", 5),
    ("쿠팡에서 무선 마우스 30개 직접 열어 읽고 엑셀로 정리해 줘.", 30),
])
def test_a_real_count_request_still_counts(text: str, target: int) -> None:
    assert ("count", target) in _kinds(text)
