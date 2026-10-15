"""예약을 만드는 **문이 둘**이다 — 도구와 HTTP. 둘이 같은 것을 받아야 한다.

## 왜 이 파일이 생겼는가

2026-08-21, 아침 자기점검 메일을 예약하려고 HTTP 로 만들려는데 안 됐다.

`Scheduler.create` 는 `repeat_every` 와 `deliver_to` 를 진작 받고 있었고,
`schedule_create` 도구 정의에도 있었다. 그런데 **`ScheduleRequest` 모델에만
없었다.** `model_dump()` 가 그 두 키를 안 실어 보내니 스케줄러는 늘 기본값
(`none` · 배달 없음)을 받았다. 기능은 다 있는데 문 하나가 잠겨 있었던 것이다.

이 저장소가 같은 모양으로 여러 번 샜다 — 도구를 만들었는데 카탈로그에 없고,
갈래가 없고, 분류표에 없고. **새 인자를 만들면 그것을 받는 문을 전부 세어라.**

이 검사는 그 둘이 갈리는 순간 걸린다.
"""

from __future__ import annotations

import inspect
import textwrap

import pytest

from alture_jarvis.api import ScheduleRequest
from alture_jarvis.scheduler import TaskScheduler


def _tool_argument_names() -> set[str]:
    """`schedule_create` 도구 정의가 받는 인자 이름."""
    # 메서드 소스는 4칸 들여쓰여 나온다 — `dedent` 없이는 파싱이 안 된다.
    source = textwrap.dedent(inspect.getsource(TaskScheduler._build_definitions))
    # 도구 정의는 `_function(이름, 설명, {속성들})` 모양이다. 속성 키만 뽑는다.
    import ast

    tree = ast.parse(source)
    names: set[str] = set()
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and first.value == "schedule_create":
                found = True
                for arg in node.args[1:]:
                    if isinstance(arg, ast.Dict):
                        names |= {
                            k.value
                            for k in arg.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)
                        }
    assert found, "schedule_create 정의를 못 찾았다 — 이 검사가 낡았다"
    return names


@pytest.mark.parametrize("field", ["repeat_every", "deliver_to"])
def test_http_accepts_what_the_tool_accepts(field: str) -> None:
    """★ 도구로 되는 것이 HTTP 로도 돼야 한다.

    이 둘이 빠져 있던 동안, HTTP 로 만든 예약은 **한 번만 돌고 아무에게도
    안 알렸다.** 그런데 만들기는 성공하므로 아무 데도 안 찍혔다.
    """
    assert field in _tool_argument_names(), f"도구 정의에 {field} 가 없다"
    assert field in ScheduleRequest.model_fields, f"ScheduleRequest 에 {field} 가 없다"


def test_payload_carries_the_fields_through() -> None:
    """모델에 있어도 `model_dump()` 로 안 실리면 소용없다 — 실제로 실어 본다."""
    payload = ScheduleRequest(
        prompt="자기 점검",
        delay_minutes=5,
        repeat_every="daily",
        deliver_to="owner@example.com",
    ).model_dump()

    assert payload["repeat_every"] == "daily"
    assert payload["deliver_to"] == "owner@example.com"


def test_defaults_are_the_quiet_ones() -> None:
    """아무 말 안 하면 **한 번만 돌고 아무에게도 안 보낸다.**

    반복과 메일은 명시해야 켜진다 — 되돌릴 수 없는 쪽이 기본이면 안 된다.
    """
    payload = ScheduleRequest(prompt="x", delay_minutes=1).model_dump()

    assert payload["repeat_every"] == "none"
    assert payload["deliver_to"] == ""
