"""「찾을 거리가 없었다」는 칸은 채움이 아니다 (2026-11-04 트렌드 조사 판).

손자리 답의 「찾지 못한 것」 표 — 「팔 가림 | … 최근 2년 내 직접적 토론 없음」 — 을 채움(met=True)으로 셌다.
과거 맡긴 일 179건에 옛 · 새 판정을 대 보니 바뀐 칸은 그 판의 2칸뿐(채움 → 확인 못 함) · 반대로 바뀐 칸 0.
"""
from __future__ import annotations

from alture_jarvis.outbound import _unobtained, check_needs

ANSWER = """## 조사 결과

**찾은 것:**

| 항목 | 내용 |
|---|---|
| **프레임 배분** | wind-up · execution · recovery 3분할이 보편적 |
| **레퍼런스** | Hollow Knight · Monster Hunter |

**찾지 못한 것:**

| 항목 | 이유 |
|---|---|
| **팔 가림** | r/animation · r/gamedev 에서 최근 2년 내 직접적 토론 없음 |
"""


def test_nothing_to_find_is_not_filled() -> None:
    got = {n["label"]: n["met"] for n in check_needs(["프레임 배분", "레퍼런스", "팔 가림"], ANSWER)}
    assert got["프레임 배분"] is True and got["레퍼런스"] is True
    assert got["팔 가림"] is not True


def test_real_values_with_the_word_none_stay_values() -> None:
    for value in ("추가 요금 없음", "12,000원", "Hollow Knight 레퍼런스", "부작용 없음"):
        assert _unobtained(value) is None, value
    for value in ("직접적 토론 없음", "관련 언급은 없었다", "공식 자료가 거의 없습니다", "찾지 못함"):
        assert _unobtained(value), value
