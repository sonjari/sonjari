"""같은 종류 요청끼리 앞머리가 어디서 갈라지나 — 계측이 실제로 찍는가 (2026-09-30).

새 질문의 첫 에이전트 호출이 직전 에이전트 프롬프트와 65토큰만 겹쳐 2만 6천 토큰을 다시 읽었다. 바로 앞 요청과만
비교하던 계측으로는 이유가 안 보였다. 판마다 **무엇이** 달라지는지(도구 이름·도구 설명·시스템 지시 위치)를 찍는다.
"""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient


def _tool(name: str, description: str = "d") -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {}}}


def _body(system: str, user: str, tools: list[dict]) -> dict:
    return {"model": "m", "options": {}, "tools": tools,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}


def _rows(tmp_path: Path) -> list[dict]:
    path = tmp_path / "prefix_same_kind.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_changed_tool_description_and_system_tail_are_named(tmp_path: Path) -> None:
    client = OllamaClient(JarvisConfig(data_dir=tmp_path))
    system = "너는 손자리다. 고정 계약 " * 10
    client._note_prefix_break(_body(system + "목표: 첫 질문", "첫 질문", [_tool("a"), _tool("b", "옛 설명")]))
    client._note_prefix_break(_body(system + "목표: 둘째 질문", "둘째 질문", [_tool("a"), _tool("b", "새 설명")]))

    (row,) = _rows(tmp_path)
    assert row["tools_described_differently"] == ["b"]
    assert row["system_diverges_at"] == len(system) + len("목표: ")
    assert "첫 질문" in row["system_old"] and "둘째 질문" in row["system_new"]


def test_steps_of_the_same_run_are_left_to_the_other_ledger(tmp_path: Path) -> None:
    """같은 판의 다음 걸음(첫 사용자 메시지가 같다)은 여기 적지 않는다 — 판 중간 깨짐은 `prefix_breaks.jsonl` 이 본다."""
    client = OllamaClient(JarvisConfig(data_dir=tmp_path))
    client._note_prefix_break(_body("sys", "같은 질문", [_tool("a")]))
    client._note_prefix_break(_body("sys", "같은 질문", [_tool("a"), _tool("b")]))

    assert _rows(tmp_path) == []


def test_other_kinds_do_not_count_as_the_previous_agent_call(tmp_path: Path) -> None:
    """라우터·사실 추출 같은 곁가지는 **다른 종류**다 — 에이전트끼리의 비교를 흐리지 않는다."""
    client = OllamaClient(JarvisConfig(data_dir=tmp_path))
    agent = "에이전트 계약 " * 10
    client._note_prefix_break(_body(agent, "질문 하나", [_tool("a")]))
    client._note_prefix_break(_body("사실만 뽑는 도구다", "추출", []))
    client._note_prefix_break(_body(agent, "질문 둘", [_tool("a")]))

    assert _rows(tmp_path) == []
