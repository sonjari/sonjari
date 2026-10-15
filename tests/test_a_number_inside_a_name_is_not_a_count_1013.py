"""이름 속의 숫자는 횟수가 아니다 — 「11번가」의 「11번」.

★ 2026-10-13 영상 촬영 판: 「다나와, 11번가, G마켓에서 … 엑셀로 정리해 줘」의 요청 풀이에
  `quote: '11번' · role: action_cardinality · unit: '번' · value: 11` 이 들어 있었다. 가게 이름의 일부를 「열한 번 하라」로 읽었다.

넓게 잡지 않는다. 운영 요청 1,997개에 대 보니 「N번/회/차례」 41곳 가운데 이름은 다섯 곳(전부 같은 가게)이었고,
「뒤에 글자가 붙으면 이름」으로 넓히면 띄어쓰기 없이 쓴 진짜 횟수(「3번먹었는데」)까지 빠졌다.
「번」은 받침이 있어 뒤에 조사 「가」가 올 수 없다 — 「번가」 · 「번지」에서 낱말이 끝나거나 자리 조사가 오면 이름이다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.quantities import unit_is_part_of_a_name
from alture_jarvis.task_contract import _quantities


def _counts(text: str) -> list[tuple[int, str]]:
    return [(q.value, q.unit) for q in _quantities(text, 0) if q.unit in {"번", "회", "차례"}]


@pytest.mark.parametrize("text", [
    "다나와, 11번가, G마켓에서 이 마우스를 찾아 가격을 엑셀로 정리해 줘",
    "그거 11번가에서는 얼마야",
    "아까 그거 11번가 값도 같이 알려줘",
    "가온로 3번지 근처 식당 세 곳 찾아줘",
    "5번가의 가게 목록을 표로 만들어줘",
])
def test_a_number_that_is_part_of_a_name_is_not_a_count(text: str) -> None:
    assert _counts(text) == []


@pytest.mark.parametrize("text,expected", [
    ("이 검사를 3번 반복해서 돌려줘", [(3, "번")]),
    ("두 번 더 해줘", [(2, "번")]),
    ("두번가봤는데 한 번 더 알려줘", [(2, "번"), (1, "번")]),      # 「가봤는데」는 이름이 아니라 움직씨다
    ("3번지켜봤는데 그대로야", [(3, "번")]),                        # 「지켜봤는데」도 마찬가지
    ("3회 실행해줘", [(3, "회")]),
])
def test_a_real_count_is_still_a_count(text: str, expected: list[tuple[int, str]]) -> None:
    assert _counts(text) == expected


def test_only_the_unit_beon_can_be_a_name_this_way() -> None:
    assert unit_is_part_of_a_name("번", "가, G마켓에서")
    assert unit_is_part_of_a_name("번", "지 근처")
    assert not unit_is_part_of_a_name("번", "가봤는데")
    assert not unit_is_part_of_a_name("번", " 반복해")
    assert not unit_is_part_of_a_name("개", "가 필요해")
