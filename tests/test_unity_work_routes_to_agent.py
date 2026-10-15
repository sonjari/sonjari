"""유니티 일은 모델 라우터에게 묻지 않고 에이전트로 간다 (2026-10-01 테스터 시험).

같은 「OntelicPlayground 유니티 프로젝트에서 너무 큰 텍스처랑 빠진 참조 있는지 점검해 줘」가 한 판은 레시피를 돌렸고,
다음 판은 라우터가 대화로 보내 도구 0번에 「실제 경로를 알려주시면 바로 점검하겠습니다」로 끝났다. 계획 층은 이 문장에
「유니티 레시피로 실제 점검하기」를 이미 세우는데, 대화 갈래에는 그 요구를 볼 자리가 없다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from alture_jarvis.plan import unity_work_asked
from alture_jarvis.runtime import JarvisRuntime

TESTER = "OntelicPlayground 유니티 프로젝트에서 너무 큰 텍스처랑 빠진 참조 있는지 점검해 줘"


@pytest.mark.parametrize("text,tool", [
    (TESTER, "unity_run_recipe"),
    ("유니티 에디터에서 아까 만든 큐브 지워 줘", "unity_editor_change"),
    ("에디터 콘솔에 에러 있나 확인해 줘", "unity_editor_look"),
    ("유니티 에디터에서 방금 한 거 되돌려 줘", "unity_editor_undo"),
])
def test_unity_work_is_named_by_the_same_table_as_the_plan(text: str, tool: str) -> None:
    assert unity_work_asked(text) == tool


@pytest.mark.parametrize("text", [
    "유니티가 뭐야",
    "유니티 설치 링크 알려줘",
    "텍스처 점검 방법 알려줘",
    "오늘 날씨 어때",
])
def test_talk_about_unity_is_not_unity_work(text: str) -> None:
    assert unity_work_asked(text) == ""


class _Packs:
    def __init__(self, on: bool) -> None:
        self.on = on

    def is_enabled(self, pack_id: str) -> bool:
        return self.on and pack_id == "game"


def test_only_when_the_game_pack_is_on() -> None:
    # 팩이 꺼져 있으면 유니티 도구가 목록에 없다 — 에이전트로 보내도 부를 수 없는 요구만 남는다.
    on = SimpleNamespace(packs=_Packs(True))
    off = SimpleNamespace(packs=_Packs(False))
    assert JarvisRuntime._requires_unity_work(on, TESTER) is True
    assert JarvisRuntime._requires_unity_work(off, TESTER) is False
    assert JarvisRuntime._requires_unity_work(on, "유니티가 뭐야") is False
