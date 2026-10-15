"""폼을 채우는 도중은 끝이 아니다 — 폼 벤치 넷째 판이 찾은 셋 (2026-10-07, Gemma 4 26B · 과제 E 0/3 · 과제 A 1/3).

1. 「대상 실제로 읽기」 하나뿐인 계획은 폼의 **첫 칸을 채운 순간** 충족된다. 루프는 그 순간 모델에게 「★ 시킨 것을 다 채웠다.
   더 찾지 말고 답해라」를 끼워 넣었고, 걸음 상한(14)에서는 `goal_met` 으로 접었다. 칸 여섯 개짜리 지원서가 넷을 채운
   13걸음에서 끝났다(세 판 중 세 판).
2. 그 마무리 답이 두 번 비자 `agent_empty_response` — 작업 실패, 답 없음. 화면에는 넣은 값이 그대로 있었다(두 판).
3. `ui_find_target("자기소개서 1 내용")` 이 화면 밖의 그 칸 대신 화면에 보이는 유일한 글상자(경력기술서)를 골랐다. 이름이
   정확히 맞는 칸은 페이지에 있었지만 그림 도구가 내준 목록(400개)에 없었다(세 판 중 두 판이 엉뚱한 칸에 썼다).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from alture_jarvis.agent import (
    _NO_CLOSING_ANSWER_NOTE,
    BrowserAgent,
    what_was_done_lines,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult
from alture_jarvis.plan import Requirement, all_met, check, enough_to_stop, satisfied_note
from alture_jarvis.tool_gateway import ToolGateway
from alture_jarvis.ui_vision import UiVision

OBSERVE = [Requirement("observe", "근거가 되는 대상 실제로 읽기", "any")]


def _fill(name: str) -> dict[str, Any]:
    return {"tool": "browser_fill", "ok": True, "arguments": {"ref": "j4"}, "evidence": {"action": "filled", "field": name}}


def _click(name: str) -> dict[str, Any]:
    return {"tool": "browser_click", "ok": True, "arguments": {"ref": "j9"}, "evidence": {"action": "clicked", "label": name}}


def _snapshot() -> dict[str, Any]:
    return {"tool": "browser_snapshot", "ok": True, "arguments": {}, "evidence": {"action": "snapshot"}}


# ── 1. 칸에 넣어 채운 「대상 읽기」는 바닥이지 끝이 아니다 ───────────────────


def test_entering_text_meets_the_floor_but_is_not_a_reason_to_stop() -> None:
    results = check(OBSERVE, sources=[], steps=[_fill("희망연봉")])

    assert all_met(results) is True, "「안 보고 답했다」는 아니다 — 완료 표시는 그대로"
    assert enough_to_stop(results) is False
    assert satisfied_note(results) == "", "첫 칸을 채웠다고 「다 채웠다, 그만하고 답해라」를 끼워 넣지 않는다"


def test_reading_a_source_is_still_enough_to_stop() -> None:
    read = {"tool": "browser_read", "ok": True, "arguments": {}, "evidence": {"url": "https://example.com/a"}}
    results = check(OBSERVE, sources=["https://example.com/a"], steps=[read])

    assert enough_to_stop(results) is True
    assert "다 채웠다" in satisfied_note(results)


def test_an_unmet_plan_is_never_enough() -> None:
    assert enough_to_stop(check(OBSERVE, sources=[], steps=[_click("다음")])) is False
    assert enough_to_stop([]) is False


def _agent() -> BrowserAgent:
    root = Path(tempfile.mkdtemp())
    config = JarvisConfig(runtime_root=root, data_dir=root / "data", output_dir=root / "outputs")
    store = JobStore(root / "jobs.db")
    return BrowserAgent(config, object(), ToolGateway(store, EventBus()), object(), object(), store, EventBus())


def test_a_form_still_being_filled_gets_more_steps_at_the_cap() -> None:
    steps = [_snapshot(), _fill("희망연봉"), _snapshot(), _fill("최종학력"), _snapshot(), _click("자격증 추가"), _snapshot(),
             _fill("자격증명")]
    results = check(OBSERVE, sources=[], steps=steps)

    extra, why = _agent()._autonomous_extension(steps=steps, elapsed=60.0, plan_results=results)

    assert why != "goal_met" and extra > 0, (extra, why)


def test_a_research_run_that_read_what_it_needed_still_stops() -> None:
    read = {"tool": "browser_read", "ok": True, "arguments": {}, "evidence": {"url": "https://example.com/a"}}
    results = check(OBSERVE, sources=["https://example.com/a"], steps=[read])

    extra, why = _agent()._autonomous_extension(steps=[read], elapsed=60.0, plan_results=results)

    assert (extra, why) == (0.0, "goal_met")


# ── 2. 마무리 답이 비어도 한 일은 남긴다 ─────────────────────────────────────


def test_what_was_done_comes_from_the_tool_records_only() -> None:
    steps = [_snapshot(), _fill("희망연봉"), _click("자격증 추가"), {**_fill("발급기관"), "ok": False}, _fill("")]

    assert what_was_done_lines(steps) == ["- 「희망연봉」 칸에 값을 넣음", "- 「자격증 추가」 누름", "- 칸에 값을 넣음"]
    assert what_was_done_lines(steps, english=True)[0] == '- entered a value in the field "희망연봉"'
    assert what_was_done_lines([_snapshot(), {"tool": "browser_read", "ok": True, "evidence": {}}]) == [], "본 것은 한 일이 아니다"


def test_a_long_run_keeps_the_latest_lines() -> None:
    lines = what_was_done_lines([_fill(f"칸 {n}") for n in range(1, 31)], keep=5)

    assert lines[0] == "- (앞의 25개는 줄임)" and lines[-1] == "- 「칸 30」 칸에 값을 넣음" and len(lines) == 6


class _Browser:
    def status(self):
        return {"started": True}


class _FormTools:
    names = {"browser_fill", "browser_click"}
    ollama_tools = [
        {"type": "function", "function": {"name": "browser_fill", "description": "fill",
                                          "parameters": {"type": "object", "properties": {}}}},
    ]


class _FormGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, name, arguments, *, job_id=""):
        self.calls.append(name)
        field = str(arguments.get("field") or "")
        return ToolResult(True, name, result={"action": "filled", "url": "https://jobs.example.com/apply", "title": "지원서",
                                               "ref": arguments.get("ref"), "field": field})


class _FillsThenGoesSilent:
    """칸 둘을 채운 뒤로는 무엇을 물어도 빈 글만 낸다 — 마무리 정리도, 생각을 끈 재시도도."""

    def __init__(self) -> None:
        self.turns = 0

    def chat_messages(self, messages, **_kwargs):
        self.turns += 1
        if self.turns <= 2:
            return {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "browser_fill", "arguments": {"ref": f"j{self.turns}", "value": "값",
                                                                    "field": ("희망연봉", "최종학력")[self.turns - 1]}}}]}
        return {"role": "assistant", "content": ""}


def test_an_empty_closing_answer_keeps_what_was_done(tmp_path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _FormGateway()
    agent = BrowserAgent(config, _FillsThenGoesSilent(), gateway, _Browser(), _FormTools(), store, EventBus())
    prompt = "지원서의 희망연봉과 최종학력 칸을 채워줘"
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()

    result = agent.run(prompt, job_id=job["id"], origin="chat")

    assert gateway.calls == ["browser_fill", "browser_fill"]
    assert result.answer.startswith(_NO_CLOSING_ANSWER_NOTE)
    assert "「희망연봉」 칸에 값을 넣음" in result.answer and "「최종학력」 칸에 값을 넣음" in result.answer
    assert result.verification["completion_state"] == "partial", "끝났다고 찍지 않는다"


class _SilentFromTheStart:
    def chat_messages(self, messages, **_kwargs):
        return {"role": "assistant", "content": ""}


def test_a_run_that_did_nothing_and_said_nothing_still_fails(tmp_path) -> None:
    import pytest

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    agent = BrowserAgent(config, _SilentFromTheStart(), _FormGateway(), _Browser(), _FormTools(), store, EventBus())
    job = store.create_job("chat", "agent", {"prompt": "지원서 칸을 채워줘"})
    store.claim_next()

    with pytest.raises(RuntimeError, match="agent_empty_response"):
        agent.run("지원서 칸을 채워줘", job_id=job["id"], origin="chat")


# ── 3. 그림으로 찾기 전에, 이름이 맞는 것이 페이지 어디에든 있는지 본다 ────────


class _LongFormWorker:
    """화면에는 경력기술서 글상자만 보이고, 「자기소개서 1 내용」은 1,056번째 — 그림 도구의 목록(400개)에 없다."""

    def __init__(self, matches: list[dict[str, Any]], shot: Path) -> None:
        self.matches = matches
        self.shot = shot
        self.calls: list[str] = []

    def execute(self, action: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(action)
        on_screen = [{"ref": "j4", "name": "경력기술서", "tag": "textarea", "role": "textarea", "frame": "main"}]
        if action == "browser_annotate":
            return {"action": "annotated", "path": str(self.shot), "url": "https://jobs.example.com/resume/edit",
                    "elements": on_screen, "candidates": on_screen, "candidate_count": 1}
        if action == "browser_find":
            return {"action": "found", "matches": self.matches, "match_count": len(self.matches)}
        if action == "browser_scroll":
            return {"action": "scrolled"}
        raise AssertionError(action)


class _PicksTheOnlyBox:
    def __init__(self) -> None:
        self.asked = 0

    def chat_message(self, prompt: str, **_kwargs: Any) -> dict[str, Any]:
        self.asked += 1
        return {"content": "4"}


def _vision(tmp_path: Path, matches: list[dict[str, Any]]):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"PNG-bytes")
    worker, eyes = _LongFormWorker(matches, shot), _PicksTheOnlyBox()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    return UiVision(config, worker, eyes), worker, eyes


def test_a_field_named_exactly_so_is_found_off_screen_without_the_picture(tmp_path: Path) -> None:
    target = {"ref": "j1056", "name": "자기소개서 1 내용", "tag": "textarea", "role": "textarea"}
    vision, worker, eyes = _vision(tmp_path, [target])

    found = vision.find({"goal": "자기소개서 1 내용"})

    assert found["ref"] == "j1056" and found["method"] == "name_match_whole_page"
    assert eyes.asked == 0, "이름이 딱 하나 맞으면 그림에 묻지 않는다"


def test_two_fields_with_that_name_still_go_to_the_picture(tmp_path: Path) -> None:
    twins = [{"ref": "j1056", "name": "자기소개서", "tag": "textarea"}, {"ref": "j1058", "name": "자기소개서", "tag": "textarea"}]
    vision, _worker, eyes = _vision(tmp_path, twins)

    found = vision.find({"goal": "자기소개서"})

    assert eyes.asked == 1 and found["ref"] == "j4", "어느 것인지 고르는 일은 판정이다 — 예전대로 그림이 한다"
