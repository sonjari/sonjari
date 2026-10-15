"""도구를 만들고 **분류표에 안 넣는** 일을 여기서 끝낸다.

## 왜 검사여야 하는가

이 저장소는 같은 구멍으로 **다섯 번** 샜다.

    2026-08-11  browser_pick_suggestion   71건이 성공률 분모에서 통째로 빠졌다
    2026-08-13  자사 데이터 조회 4건       "분류 안 된 도구"로 흘렀다
    2026-08-14  ui_click_target 등 12개
    2026-08-20  browser_click_confirmed 등 3개, watch_* 2개
    2026-08-21  schedule_create·schedule_cancel

그때마다 `measure_autonomy.py` 주석에 "★ 도구를 새로 만들면 **그날** 여기에 넣어라"
라고 적었다. **다섯 번 적었고 다섯 번 샜다.** 그러면 그건 사람이 게을러서가 아니라
안내문으로 될 일이 아니었던 것이다(사고 R — 결정론으로 박을 수 있으면 코드로).

## 라이브 눈금은 이걸 못 잡는다

`measure_autonomy.py` 끝의 "분류 안 된 도구" 줄은 **실제로 호출된 도구만** 보여준다.
장부를 훑어 만든 목록이기 때문이다. 그래서 만들어 놓고 아직 아무도 안 부른 도구는
분류가 비어 있어도 아무 데도 안 나온다.

실제로 그랬다 — 라이브에는 `schedule_*` 둘만 떴는데, 소스를 훑으니 **12개가 더**
있었다. "경고에 없다"가 「분류됐다」와 「한 번도 안 불렸다」를 동시에 뜻하고 있었다.
빈 값 하나가 두 사실을 뜻하면 조용히 고장난다.

이 검사는 **장부가 아니라 소스**를 본다. 그래서 한 번도 안 불린 도구도 잡는다.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from alture_jarvis.agent import _READ_TOOLS

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "alture_jarvis"


def _load_measure_autonomy():
    """`scripts/measure_autonomy.py` 는 패키지가 아니라 스크립트라 경로로 읽는다."""
    spec = importlib.util.spec_from_file_location(
        "_measure_autonomy", _ROOT / "scripts" / "measure_autonomy.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 라우터가 갈래를 고를 때 쓰는 **가짜 도구**들. 에이전트 루프의 도구가 아니라
# `runtime._general_route` 가 모델에게 "어느 길로 갈까"를 묻는 선택지다. 그래서
# 성공률 분류표의 대상이 아니다.
#
# ★ 이 면제 목록은 **runtime.py 에 정의된 것만** 받는다. 다른 파일에서 온 도구를
#   여기 적어 면제시키면 이 검사가 그 순간 무의미해진다.
_ROUTER_CHOICES = frozenset(
    {
        "use_browser",
        "use_camera_control",
        "use_google_workspace",
        "use_local_computer",
        "use_naver_blog",
        "use_scheduler",
        "look_at_camera",
    }
)


def _declared_tool_names() -> dict[str, str]:
    """소스에서 도구 이름을 전부 뽑는다. 이름 -> 정의된 파일.

    도구 정의가 세 가지 모양으로 쓰여 있어서 셋 다 본다:

        {"type": "function", "function": {"name": "x", ...}}   생 dict
        self._function("x", "설명", {...})                      헬퍼 호출
        _function("x", ...)                                     모듈 함수

    ★ 정규식이 아니라 AST 로 읽는다. `re.S` 로 파일을 통째로 훑으면 비탐욕
      매칭이 뭉개져 104개 중 15개만 잡혔다(실측).
    """
    found: dict[str, str] = {}
    for path in sorted(_SRC.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - 파싱 안 되면 다른 검사가 잡는다
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None) or ""
                if name.endswith("_function") and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        found.setdefault(first.value, path.name)
            if isinstance(node, ast.Dict):
                keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
                if "name" in keys and ("description" in keys or "parameters" in keys):
                    for key, value in zip(node.keys, node.values):
                        if (
                            isinstance(key, ast.Constant)
                            and key.value == "name"
                            and isinstance(value, ast.Constant)
                            and isinstance(value.value, str)
                        ):
                            found.setdefault(value.value, path.name)
    return found


def test_extractor_still_sees_the_tool_surface() -> None:
    """추출기 자체가 고장 나면 이 파일 전체가 조용히 통과한다.

    ★ 재는 자에도 같은 병이 있다 — 분모가 0 이면 어떤 검사든 초록불이다.
    그래서 **바닥선**을 박아 둔다. 도구가 줄어들 수는 있어도 절반이 되지는 않는다.
    """
    found = _declared_tool_names()
    assert len(found) >= 90, f"도구를 {len(found)}개밖에 못 찾았다 — 추출기가 고장 났다"
    # 모양이 다른 세 갈래에서 최소 하나씩은 잡혀야 한다.
    assert "browser_extract" in found  # 생 dict
    assert "schedule_create" in found  # self._function 헬퍼
    assert "skill_list" in found  # 새로 만든 것


def test_every_registered_tool_is_classified() -> None:
    """★ 이 파일에서 가장 중요한 검사.

    도구를 만들었는데 분류표에 안 넣으면 **여기서 걸린다.** 성공률이 아니라
    **분모**가 틀리는 종류의 고장이라, 성적표는 멀쩡해 보이고 실적만 사라진다.
    """
    ma = _load_measure_autonomy()
    known = set(_READ_TOOLS) | ma.WRITE_TOOLS | ma.PREPARE_TOOLS | ma.NEUTRAL_TOOLS
    declared = _declared_tool_names()

    unclassified = {
        name: where
        for name, where in declared.items()
        if name not in known and name not in _ROUTER_CHOICES
    }

    assert not unclassified, (
        "분류 안 된 도구가 있다 — 이대로면 실적이 성공률 분모에서 조용히 빠진다.\n"
        + "\n".join(f"  {name}  ({where})" for name, where in sorted(unclassified.items()))
        + "\n\n쓰기면 WRITE_TOOLS, 준비면 PREPARE_TOOLS, 목록·본문을 가져오면"
        " agent._READ_TOOLS, 나머지는 NEUTRAL_TOOLS 에 넣을 것."
    )


def test_router_choices_are_only_declared_in_runtime() -> None:
    """면제 목록이 뒷문이 되지 않게 한다.

    `_ROUTER_CHOICES` 는 라우터의 갈래라서 면제인 것이지, 이름이 거기 적혀서
    면제인 게 아니다. 다른 파일에서 같은 이름의 **진짜 도구**를 만들면 잡는다.
    """
    declared = _declared_tool_names()
    for name in _ROUTER_CHOICES:
        where = declared.get(name)
        if where is not None:
            assert where == "runtime.py", (
                f"{name} 이 {where} 에서 정의됐다 — 라우터 갈래가 아니라 진짜 도구라면"
                " 면제가 아니라 분류표에 들어가야 한다."
            )


@pytest.mark.parametrize(
    "name",
    ["schedule_create", "schedule_cancel", "google_calendar_update", "google_calendar_delete"],
)
def test_tools_that_make_future_work_or_change_others_are_writes(name: str) -> None:
    """예약을 만드는 것은 **앞으로 자비스가 스스로 도는 일을 만드는 것**이다.

    `watch_create` 를 WRITE 에 넣은 근거가 그대로 적용된다. 게다가 `schedule_create`
    는 `deliver_to` 가 붙으면 되돌릴 수 없는 메일까지 내보낸다.
    """
    ma = _load_measure_autonomy()
    assert name in ma.WRITE_TOOLS


def test_commit_tools_are_a_subset_of_writes() -> None:
    """되돌릴 수 없는 것은 전부 쓰기여야 한다. 아니면 두 표가 갈린다."""
    ma = _load_measure_autonomy()
    assert ma.COMMIT_TOOLS <= ma.WRITE_TOOLS


def test_no_tool_is_in_two_classes() -> None:
    """한 도구가 두 칸에 있으면 분모가 겹쳐 성공률이 조용히 뒤틀린다.

    (COMMIT_TOOLS 는 WRITE 의 부분집합으로 **의도된** 겹침이라 여기서 뺀다.)
    """
    ma = _load_measure_autonomy()
    buckets = {
        "read": set(_READ_TOOLS),
        "write": set(ma.WRITE_TOOLS),
        "prepare": set(ma.PREPARE_TOOLS),
        "neutral": set(ma.NEUTRAL_TOOLS),
    }
    names = list(buckets)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            overlap = buckets[left] & buckets[right]
            assert not overlap, f"{left} 와 {right} 에 동시에 있다: {sorted(overlap)}"
