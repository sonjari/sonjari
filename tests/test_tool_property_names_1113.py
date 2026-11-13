"""도구 칸 이름은 클로드 API 규칙(^[a-zA-Z0-9_.-]{1,64}$)을 지킨다 (2026-11-13).

`anim_library_tag` 가 칸 이름을 「무기 · 컨셉 · 무게감 · 속도감」으로 지어 클로드 앱에서 도구가 통째로 빠졌다
(「property key 무기 does not match /^[a-zA-Z0-9_.-]{1,64}$/」). 시험은 다 통과했었다 — 도구를 부르는 쪽(파이썬)은 한글 열쇠도 받기 때문.
그래서 도구 하나가 아니라 **소스 전체**를 훑는다: `"properties": {…}` 칸과 `_tool(이름, 설명, {칸…}, 필수)` 의 칸 묶음.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from alture_jarvis import animator_tools
from alture_jarvis.animator import library, specs

SRC = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"
KEY_RULE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def _property_dicts(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "properties" and isinstance(value, ast.Dict):
                    yield value
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_tool" and len(node.args) >= 3:
            if isinstance(node.args[2], ast.Dict):
                yield node.args[2]


def test_every_tool_property_name_is_one_claude_accepts() -> None:
    bad: list[str] = []
    seen = 0
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for props in _property_dicts(tree):
            for key in props.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    seen += 1
                    if not KEY_RULE.match(key.value):
                        bad.append(f"{path.relative_to(SRC)}:{key.lineno} {key.value!r}")
    assert seen > 200, f"훑은 칸이 너무 적다({seen}) — 정의 모양이 바뀌었으면 이 시험을 고쳐라"
    assert not bad, "클로드가 받지 않는 칸 이름:\n" + "\n".join(bad)


def test_anim_library_tag_uses_english_fields_that_map_to_the_library_facets() -> None:
    props = specs.LIBRARY_TAG["function"]["parameters"]["properties"]
    assert {"weapon", "concept", "weight", "speed"} <= set(props)
    assert set(animator_tools.FACET_ARGS.values()) == set(library.FACETS)
