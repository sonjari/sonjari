"""화면을 다시 본 걸음은 자율 걸음 상한을 덜 쓴다 (2026-10-08).

운영 판 하나(조회 폼: 출발지 · 도착지 · 달력 · 인원 · 정렬 · 시간대)가 48번째 걸음에 거르개 「적용」을 누르고 상한에 닿아,
결과 목록을 못 읽은 채 「덜 끝남」으로 닫혔다. 실패 걸음 0 · 48걸음 중 21걸음이 「보기」(조작할 요소 보기 · 화면에서 찾기)였다.
누르고 확인하는 모델일수록 상한에 빨리 닿는 구조였다.

- 상한이 막으려는 것은 헛도는 조사(새 쪽을 계속 여는 꼬리)다 — 열기 · 읽기 · 검색 · 누르기는 예전처럼 다 센다.
- 열려 있는 화면을 다시 본 걸음은 상한의 **절반까지** 세지 않는다. 그 위는 센다 — 보기만 되풀이해도 끝은 있다.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from alture_jarvis.agent import BrowserAgent, cap_room, steps_against_cap
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.tool_gateway import ToolGateway


def _agent(**overrides: Any) -> BrowserAgent:
    root = Path(tempfile.mkdtemp())
    config = JarvisConfig(runtime_root=root, data_dir=root / "data", output_dir=root / "outputs", **overrides)
    store = JobStore(root / "jobs.db")
    return BrowserAgent(config, object(), ToolGateway(store, EventBus()), object(), object(), store, EventBus())


def _step(tool: str, number: int = 1) -> dict[str, Any]:
    return {"step": number, "tool": tool, "arguments": {"ref": f"e{number}"}, "ok": True, "status": "", "error": "",
            "evidence": {"url": "https://shop.example/search"}}


def _form_run(pairs: int) -> list[dict[str, Any]]:
    """누르고 → 확인하고 를 되풀이하는 판."""
    steps: list[dict[str, Any]] = []
    for index in range(pairs):
        steps.append(_step("browser_click", len(steps) + 1))
        steps.append(_step("browser_snapshot" if index % 2 else "browser_find", len(steps) + 1))
    return steps


def test_looks_are_left_out_up_to_half_the_cap() -> None:
    assert steps_against_cap(_form_run(24), 48) == 24, "48걸음 중 보기 24 — 한 일은 24"
    assert steps_against_cap([_step("browser_snapshot")] * 40, 48) == 16, "보기만 40번이면 24까지만 뺀다"
    assert steps_against_cap([], 48) == 0


def test_opening_reading_searching_and_clicking_all_count() -> None:
    """조사 판은 예전 그대로다 — 새 쪽을 열고 읽는 걸음은 하나도 빠지지 않는다."""
    research = [_step(tool) for tool in ("browser_search", "browser_open_result", "browser_extract", "browser_open",
                                         "browser_read", "browser_click", "browser_fill", "browser_scroll")]
    assert steps_against_cap(research, 48) == len(research)


def test_a_form_run_that_checks_after_each_click_is_not_cut_at_the_raw_cap() -> None:
    agent = _agent(agent_autonomous_max_steps=48)

    extra, why = agent._autonomous_extension(steps=_form_run(24), elapsed=440.0)

    assert why != "autonomous_step_cap" and extra > 0, why
    assert cap_room(agent.config, _form_run(24)) == 24


def test_a_research_run_still_stops_at_the_cap() -> None:
    agent = _agent(agent_autonomous_max_steps=48)
    steps = [_step("browser_open" if index % 2 else "browser_extract", index + 1) for index in range(48)]

    extra, why = agent._autonomous_extension(steps=steps, elapsed=440.0)

    assert (extra, why) == (0.0, "autonomous_step_cap")


def test_looking_alone_cannot_go_on_for_ever() -> None:
    """안 세는 몫은 상한의 절반까지 — 48 이면 72걸음에서 닫힌다."""
    agent = _agent(agent_autonomous_max_steps=48)

    assert cap_room(agent.config, _form_run(35)) > 0, "70걸음(누르기 35 · 보기 35) — 아직 자리가 있다"
    extra, why = agent._autonomous_extension(steps=_form_run(36), elapsed=600.0)
    assert (extra, why) == (0.0, "autonomous_step_cap"), "72걸음 — 누르기 36 + 센 보기 12 = 48"
