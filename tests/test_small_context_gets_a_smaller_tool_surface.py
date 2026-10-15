"""작은 컨텍스트에서는 도구 정의를 줄인다 (2026-09-22).

## 무엇을 쟀나 (`bench/coding/count_tool_tokens.py`, 모델이 직접 센 토큰)

    일반 Cowork   도구 128개   18,411 토큰   = 32K 컨텍스트의 56%   (Claude Code 가 도구 검색을 켜는 기준은 10%)
    웹 조사 갈래   도구  68개    9,663 토큰   = 29%

8GB 노트북의 4B 는 32K 컨텍스트라 도구 정의만으로 절반이 찬다. 설명문은 크기의 27% 뿐(중앙값 78자)이고 64% 는 이름·타입 같은
구조라, 설명문만 줄여서는 안 된다 — **이야기가 안 나온 도구 가족을 빼는 것**이 큰 지렛대다(입시·진로·문제은행 8개 10%, 카메라 6%, 한글 3%).

    적용 후  일반 Cowork 128 → 105개, 18,411 → 12,705 토큰(−31%, 32K 의 39%) · 웹 조사 9,663 → 8,261(−15%)

## 지킬 것

1. **컨텍스트가 큰 경로(35B)는 그대로다.** 회귀 위험을 질 이유가 없다.
2. 그 이야기를 꺼낸 요청에는 도구가 그대로 남는다(낱말은 넉넉히). `_ALWAYS_ON_TOOLS` 는 안 빠진다.
3. 설명문만 줄인다 — **이름·인자·타입·필수 여부는 바이트 그대로**다(호출 계약을 안 건드린다). 짧은 것은 손대지 않는다.
4. 기준은 설정이고 0 이면 꺼진다.
"""

from __future__ import annotations

import copy
import inspect
import json

from alture_jarvis.agent import (
    _ALWAYS_ON_TOOLS,
    BrowserAgent,
    _compact_tool_descriptions,
    _platform_scoped_tool_definitions,
)
from alture_jarvis.config import JarvisConfig


def _tool(name: str, description: str = "짧은 설명", **properties) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {"x": {"type": "string"}}, "required": ["x"]},
    }}


def _names(tools: list[dict]) -> set[str]:
    return {t["function"]["name"] for t in tools}


_CATALOG = [
    _tool("browser_open"), _tool("local_read_text_file"), _tool("shell_probe"), _tool("skill_list"),
    _tool("admission_quant_lookup"), _tool("admission_candidates_by_grade"), _tool("career_strategy_lookup"),
    _tool("question_bank_same_type"), _tool("official_exam_items_lookup"),
    _tool("camera_look"), _tool("camera_find_person"),
    _tool("hwp_read"), _tool("hwp_apply_edit"),
]


def test_families_nobody_asked_about_are_dropped_on_a_small_context() -> None:
    kept = _names(_platform_scoped_tool_definitions(_CATALOG, "이 PC 상태를 진단해줘", compact=True))

    assert kept == {"browser_open", "local_read_text_file", "shell_probe", "skill_list"}


def test_the_big_context_path_is_untouched() -> None:
    """35B(131,072) 경로 — `compact=False` 가 기본이라 예전과 똑같다."""
    assert _names(_platform_scoped_tool_definitions(_CATALOG, "이 PC 상태를 진단해줘")) == _names(_CATALOG)


def test_asking_about_a_family_brings_it_back() -> None:
    admission = _names(_platform_scoped_tool_definitions(_CATALOG, "이 학생 수능 등급으로 갈 수 있는 대학 찾아줘", compact=True))
    camera = _names(_platform_scoped_tool_definitions(_CATALOG, "카메라로 지금 누가 있는지 봐줘", compact=True))
    hwp = _names(_platform_scoped_tool_definitions(_CATALOG, "이 한글 문서 고쳐줘", compact=True))

    assert {"admission_quant_lookup", "career_strategy_lookup", "question_bank_same_type", "official_exam_items_lookup"} <= admission
    assert "camera_look" not in admission and "hwp_read" not in admission  # 딴 가족은 여전히 빠진다
    assert {"camera_look", "camera_find_person"} <= camera and "admission_quant_lookup" not in camera
    assert {"hwp_read", "hwp_apply_edit"} <= hwp


def test_always_on_tools_survive() -> None:
    kept = _names(_platform_scoped_tool_definitions(_CATALOG, "아무 말", compact=True))

    assert {"shell_probe", "skill_list"} <= kept
    assert set(_ALWAYS_ON_TOOLS) & _names(_CATALOG) <= kept


# --- 설명문 줄이기 ----------------------------------------------------------------

def test_a_long_description_is_clipped_at_a_sentence_boundary() -> None:
    long_text = "첫 문장은 핵심이다. " + "둘째 문장은 부연이다. " * 30
    tool = _tool("t", long_text)

    clipped = _compact_tool_descriptions([tool])[0]["function"]["description"]

    assert len(clipped) <= 140 and clipped.startswith("첫 문장은 핵심이다.")
    assert clipped.endswith(("다.", "이다.")), clipped  # 문장 중간에서 안 끊는다


def test_only_descriptions_change_never_the_call_contract() -> None:
    """이름·인자 이름·타입·enum·required 는 바이트 그대로여야 한다 — 모델이 부르는 계약이다."""
    tool = _tool(
        "browser_click", "긴 설명. " * 60,
        ref={"type": "string"},
        expect={"type": "object", "description": "확인 방법. " * 40,
                "properties": {"kind": {"type": "string", "enum": ["a", "b"]}}},
    )
    before = copy.deepcopy(tool)

    after = _compact_tool_descriptions([tool])[0]

    def strip_text(node):
        if isinstance(node, dict):
            return {k: strip_text(v) for k, v in node.items() if k != "description"}
        return node

    assert strip_text(after) == strip_text(before)
    assert tool == before, "입력을 바꾸면 안 된다(다음 판에 줄어든 채 남는다)"
    assert len(after["function"]["parameters"]["properties"]["expect"]["description"]) <= 71


def test_short_descriptions_are_left_alone_and_identical() -> None:
    tool = _tool("t", "짧다", x={"type": "string", "description": "예: **/*.py"})

    assert _compact_tool_descriptions([tool])[0] is tool


def test_compaction_actually_shrinks_a_realistic_surface() -> None:
    tools = [_tool(f"tool_{i}", "이 도구는 꽤 긴 설명을 갖고 있다. " * 12) for i in range(20)]
    before = len(json.dumps(tools, ensure_ascii=False))

    compacted = _compact_tool_descriptions(tools)
    after = len(json.dumps(compacted, ensure_ascii=False))

    assert after < before * 0.8  # 구조(이름·타입)는 그대로라 설명문만큼만 준다
    assert all(len(t["function"]["description"]) <= 140 for t in compacted)


# --- 언제 켜지나 ------------------------------------------------------------------

def _agent_with(config: JarvisConfig) -> BrowserAgent:
    agent = BrowserAgent.__new__(BrowserAgent)  # 이 판정은 설정만 본다 — 나머지 배선이 필요 없다
    agent.config = config
    return agent


def test_it_switches_on_by_context_size() -> None:
    small = JarvisConfig(tool_surface_compact_max_ctx=40_000, model_num_ctx={"chat": 32_768})
    big = JarvisConfig(tool_surface_compact_max_ctx=40_000, model_num_ctx={"chat": 131_072})

    assert _agent_with(small)._compact_tool_surface("chat") is True
    assert _agent_with(big)._compact_tool_surface("chat") is False


def test_zero_or_an_unknown_window_means_off() -> None:
    off = JarvisConfig(tool_surface_compact_max_ctx=0, model_num_ctx={"chat": 8_192})
    assert _agent_with(off)._compact_tool_surface("chat") is False

    agent = BrowserAgent.__new__(BrowserAgent)

    class _Broken:
        tool_surface_compact_max_ctx = 40_000

        @staticmethod
        def num_ctx_for(role="chat"):
            raise RuntimeError("못 잰다")

    agent.config = _Broken()
    assert agent._compact_tool_surface("chat") is False  # 못 재면 큰 쪽 동작


def test_the_default_and_the_override(monkeypatch) -> None:
    assert JarvisConfig().tool_surface_compact_max_ctx == 40_000
    monkeypatch.setenv("JARVIS_TOOL_SURFACE_COMPACT_MAX_CTX", "16000")
    assert JarvisConfig.from_env().tool_surface_compact_max_ctx == 16_000


def test_the_loop_actually_uses_it() -> None:
    """만들어 놓고 부르는 자리가 없으면 아무 일도 안 일어난다."""
    source = inspect.getsource(BrowserAgent.run)

    assert "self._compact_tool_surface(model_role)" in source
    assert "compact=compact_surface" in source and "_compact_tool_descriptions(available_model_tools)" in source
