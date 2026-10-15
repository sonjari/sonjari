"""창이 차기 전에 한 번에 크게 접어 대화를 작게 둔다 (2026-10-09 낮).

맡긴 코드 판(13,795줄 파일을 줄이는 일)이 10만 토큰을 넘자 서버가 걸음마다 대화 전체를 다시 읽었다(한 걸음 150초).
대표: 「컨텍스트 눌려서 그런 거 아니가 — 접는 방식으로 방법 있지 않나」.

이 시험이 지키는 것: 접기는 **한 번**이고 그 결과가 대화에 남는다 · 그 뒤 걸음은 뒤에 붙기만 한다 · 사람이 시킨 판은 그대로다.
이 시험이 **못** 지키는 것: 서버가 실제로 덜 읽는가. 그것은 긴 판을 다시 돌려 서버 기록으로만 볼 수 있다.
(처음엔 「기능이 없으면 걸음마다 앞쪽이 바뀐다」고 봤는데, 기능을 끄고 돌려도 앞쪽은 안 바뀌었다 — 진단이 틀렸다. `transcript.py` 의 설명.)
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alture_jarvis.agent import BrowserAgent, code_transcript_budget
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.transcript import (
    STEP_FOLD_CEILING_CHARS, STEP_FOLD_FULLNESS, STEP_FOLD_TARGET, needs_step_fold, step_fold_trigger_chars, transcript_chars,
)

_WINDOW = 22_000   # 토큰 — 예산이 약 28,800자가 된다


def test_the_trigger_comes_before_the_ordinary_fold_and_the_target_leaves_room() -> None:
    assert 0.3 < STEP_FOLD_TARGET < STEP_FOLD_FULLNESS < 1.0
    assert STEP_FOLD_FULLNESS - STEP_FOLD_TARGET >= 0.4, "작은 창에서는 접고 나서 다음 접기까지 예산의 5분의 2는 가야 한다"
    # 큰 창(131,072 · 코드 예산 342,927자): 접는 자리는 예전 그대로 — 되돌리기가 실패하기 시작한 자리(약 10만 토큰)보다 넉넉히 앞.
    big = code_transcript_budget(131_072, "balanced")
    assert step_fold_trigger_chars(big) == STEP_FOLD_CEILING_CHARS
    assert 0.70 * big < step_fold_trigger_chars(big) < 0.80 * big
    assert step_fold_trigger_chars(big) - int(big * STEP_FOLD_TARGET) >= 0.2 * big, "큰 창도 다음 접기까지 예산의 5분의 1은 간다"
    # 작은 창(49,152 — 16GB 조건): 거의 찰 때까지 쓴다. 예전에는 75% 에서 접어 창의 3분의 1을 안 썼다(판 569e0929 · 200걸음에 30번).
    small = code_transcript_budget(49_152, "balanced")
    assert step_fold_trigger_chars(small) == int(small * STEP_FOLD_FULLNESS) < STEP_FOLD_CEILING_CHARS
    assert step_fold_trigger_chars(small) > 0.9 * small


def test_size_counts_what_the_model_gets_not_our_private_marks() -> None:
    plain = [{"role": "user", "content": "가" * 100}]
    marked = [{"role": "user", "content": "가" * 100, "_metrics": {"x": "y" * 500}, "_inference": {"z": 1}}]
    assert transcript_chars(plain) == transcript_chars(marked)
    assert needs_step_fold(plain, 100) is True and needs_step_fold(plain, 10_000) is False
    assert needs_step_fold(plain, 0) is False


# ── 실제 호출 길 ───────────────────────────────────────────────────────────────


class _Model:
    def __init__(self) -> None:
        self.sent: list[list[dict]] = []

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.sent.append([dict(item) for item in messages])
        return {"role": "assistant", "content": "다음 걸음"}


def _agent(tmp_path: Path) -> tuple[BrowserAgent, _Model, JobStore]:
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False,
    )
    store = JobStore(tmp_path / "jarvis.db")
    model = _Model()
    tools = SimpleNamespace(names=set(), ollama_tools=[])
    agent = BrowserAgent(config, model, SimpleNamespace(), SimpleNamespace(status=lambda: {}), tools, store, EventBus())
    agent._window = lambda role: _WINDOW   # type: ignore[method-assign]
    return agent, model, store


def _read(index: int, chars: int = 2_400) -> list[dict[str, Any]]:
    """파일을 읽은 걸음 하나 — 부른 메시지와 그 결과."""
    path = f"src/module_{index}.py"
    body = json.dumps({"ok": True, "result": {"action": "local_read_text_file", "path": path, "text": f"# {index}\n" + "x = 1\n" * (chars // 6)}})
    return [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "local_read_text_file", "arguments": {"path": path}}}]},
        {"role": "tool", "tool_name": "local_read_text_file", "content": body},
    ]


def _conversation(steps: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "코드 작업 규칙."},
        {"role": "user", "content": "agent.py 를 동작 그대로 줄여줘"},
    ]
    for index in range(steps):
        messages += _read(index)
    return messages


def _call(agent: BrowserAgent, messages: list[dict[str, Any]], job_id: str) -> None:
    agent._model_message(messages, job_id=job_id, tools=None, think=False, model_role="code", inference_profile="balanced")


def _budget() -> int:
    return code_transcript_budget(_WINDOW, "balanced")


def test_a_full_window_is_folded_once_and_the_next_steps_only_add_to_the_end(tmp_path: Path) -> None:
    agent, model, store = _agent(tmp_path)
    job = store.create_job("chat", "맡긴 일", {"prompt": "줄여줘", "origin": "mcp"})["id"]
    agent.__dict__.setdefault("_step_fold_jobs", set()).add(job)
    messages = _conversation(12)
    assert needs_step_fold(messages, _budget()), "시험 대화가 예산을 넘겨야 한다"
    before = transcript_chars(messages)

    _call(agent, messages, job)

    after = transcript_chars(messages)
    assert after < before and after < step_fold_trigger_chars(_budget()), "한 번에 접는 선 아래로 내려갔다 — 대화에 그대로 남는다"
    assert after <= int(_budget() * 0.75), "접을 때는 넉넉히 내린다 — 다음 접기까지 갈 자리가 있어야 한다"
    assert messages[1]["content"] == "agent.py 를 동작 그대로 줄여줘", "시킨 일은 접지 않는다"
    first = model.sent[-1]

    # 걸음이 이어진다 — 예산을 다시 넘기 전까지는 **앞쪽이 그대로**다.
    for index in (100, 101, 102):
        messages += _read(index, chars=600)
        _call(agent, messages, job)
        assert not needs_step_fold(messages[:-2], _budget())
        sent = model.sent[-1]
        assert sent[:len(first)] == first, "접은 뒤의 걸음에서 대화 앞쪽이 바뀌었다 — 서버가 전체를 다시 읽는다"
    folds = [row for row in store.list_audit(limit=50) if row.get("event") == "agent_transcript_step_folded"] if hasattr(store, "list_audit") else None
    if folds is not None:
        assert len(folds) == 1, "접기는 한 번이다"


def test_a_job_a_person_started_is_bounded_exactly_as_before(tmp_path: Path) -> None:
    """사람이 시킨 판은 아직 그대로다 — 접은 것을 대화에 남기지 않는다(근거 대조가 원문을 본다). 재 보고 옮긴다."""
    agent, model, store = _agent(tmp_path)
    job = store.create_job("chat", "사람이 시킨 일", {"prompt": "줄여줘", "origin": "workspace"})["id"]
    messages = _conversation(12)
    snapshot = json.dumps(messages, ensure_ascii=False)

    _call(agent, messages, job)

    assert json.dumps(messages, ensure_ascii=False) == snapshot, "대화 원문을 건드리지 않는다"
    assert transcript_chars(model.sent[-1]) < transcript_chars(messages), "보낼 때만 접는다 — 지금까지와 같다"


def test_a_window_with_room_is_left_alone(tmp_path: Path) -> None:
    agent, model, store = _agent(tmp_path)
    job = store.create_job("chat", "맡긴 일", {"prompt": "줄여줘", "origin": "mcp"})["id"]
    agent.__dict__.setdefault("_step_fold_jobs", set()).add(job)
    messages = _conversation(3)
    snapshot = json.dumps(messages, ensure_ascii=False)
    _call(agent, messages, job)
    assert json.dumps(messages, ensure_ascii=False) == snapshot
