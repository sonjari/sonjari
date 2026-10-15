"""접기 전 정리 한 장 — 실제 호출 길에서 (2026-10-10 · 재기 전 · 기본은 끔).

이 시험이 지키는 것: 꺼져 있으면 예전과 한 글자도 같다 · 켜면 접기 **전의** 대화로 정리를 청하고, 접은 뒤 요청 메시지 앞에
싣는다 · 정리를 못 받아도 판은 간다 · 접은 뒤 걸음에서 대화 앞쪽이 안 바뀐다.
이 시험이 **못** 지키는 것: 정리가 있으면 다시 읽는 걸음이 줄어드는가. 그것은 긴 판을 돌려 봐야 안다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.transcript import FOLD_SHEET_CLOSE, FOLD_SHEET_OPEN, FOLD_SHEET_REQUEST, needs_step_fold, transcript_chars

from test_transcript_folds_in_steps_1009 import _agent, _budget, _call, _conversation, _read

REQUEST = "agent.py 를 동작 그대로 줄여줘"
SHEET = "## 목표\n300줄 줄이기\n## 다시 읽지 않아도 되게\nsrc/module_3.py 의 x 는 1"


def _asks_for_a_sheet(messages: list[dict[str, Any]]) -> bool:
    return any(FOLD_SHEET_REQUEST[:40] in str(item.get("content") or "") for item in messages[-2:])


class _WritesSheets:
    """정리를 청하면 정리를, 아니면 다음 걸음을 낸다."""

    def __init__(self, sheet: Any = SHEET) -> None:
        self.sheet = sheet
        self.sent: list[list[dict]] = []

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.sent.append([dict(item) for item in messages])
        if _asks_for_a_sheet(messages):
            if isinstance(self.sheet, Exception):
                raise self.sheet
            if isinstance(self.sheet, dict):
                return self.sheet
            return {"role": "assistant", "content": self.sheet}
        return {"role": "assistant", "content": "다음 걸음"}


def _delegated(tmp_path: Path, model: _WritesSheets, *, on: bool):  # noqa: ANN202
    agent, _, store = _agent(tmp_path)
    agent.ollama = model
    agent.config.fold_summary_enabled = on
    job = store.create_job("chat", "맡긴 일", {"prompt": "줄여줘", "origin": "mcp"})["id"]
    agent.__dict__.setdefault("_step_fold_jobs", set()).add(job)
    return agent, store, job


def test_off_by_default_it_folds_exactly_as_before(tmp_path: Path) -> None:
    model = _WritesSheets()
    agent, _store, job = _delegated(tmp_path, model, on=False)
    assert agent.config.__class__().fold_summary_enabled is False
    messages = _conversation(12)
    before = transcript_chars(messages)
    _call(agent, messages, job)
    assert len(model.sent) == 1, "꺼져 있으면 모델을 한 번 더 부르지 않는다"
    assert transcript_chars(messages) < before
    assert messages[1]["content"] == REQUEST
    assert FOLD_SHEET_OPEN not in str(messages)


def test_on_it_asks_with_the_unfolded_talk_then_carries_the_sheet_in_front_of_the_request(tmp_path: Path) -> None:
    model = _WritesSheets()
    agent, store, job = _delegated(tmp_path, model, on=True)
    messages = _conversation(12)
    unfolded = [dict(item) for item in messages]
    assert needs_step_fold(messages, _budget())

    _call(agent, messages, job)

    assert len(model.sent) == 2
    asked, stepped = model.sent
    assert _asks_for_a_sheet(asked)
    # 정리를 청한 호출은 접기 **전의** 대화를 본다 — 줄어든 대화로 정리를 쓰게 하면 잃을 것을 이미 잃은 뒤다.
    assert transcript_chars(asked) > transcript_chars(stepped)
    assert [item.get("role") for item in asked[:len(unfolded)]] == [item.get("role") for item in unfolded]
    # 접은 뒤: 정리가 요청 메시지 앞에 있고, 요청 글은 그대로 끝에 있다.
    request = messages[1]["content"]
    assert request.endswith(REQUEST)
    assert request.index(FOLD_SHEET_OPEN) < request.index("300줄 줄이기") < request.index(FOLD_SHEET_CLOSE) < request.index(REQUEST)
    assert "300줄 줄이기" in str(stepped[1].get("content")), "다음 걸음의 모델이 정리를 본다"
    assert not _asks_for_a_sheet(stepped), "청하는 글은 대화에 남지 않는다"
    assert not any(FOLD_SHEET_REQUEST[:40] in str(item.get("content") or "") for item in messages)
    folds = [row for row in store.list_audit(limit=50) if row.get("event") == "agent_transcript_step_folded"] if hasattr(store, "list_audit") else None
    if folds is not None:
        assert len(folds) == 1, "정리를 청한 호출이 접기를 한 번 더 적지 않는다"


def test_after_the_fold_the_front_of_the_talk_stays_put(tmp_path: Path) -> None:
    model = _WritesSheets()
    agent, _store, job = _delegated(tmp_path, model, on=True)
    messages = _conversation(12)
    _call(agent, messages, job)
    first = model.sent[-1]
    for index in (100, 101, 102):
        messages += _read(index, chars=600)
        _call(agent, messages, job)
        assert model.sent[-1][:len(first)] == first, "접은 뒤의 걸음에서 대화 앞쪽이 바뀌었다 — 서버가 전체를 다시 읽는다"
    assert sum(1 for sent in model.sent if _asks_for_a_sheet(sent)) == 1, "접을 때만 청한다"


def test_the_next_fold_replaces_the_sheet(tmp_path: Path) -> None:
    model = _WritesSheets()
    agent, _store, job = _delegated(tmp_path, model, on=True)
    messages = _conversation(12)
    _call(agent, messages, job)
    model.sheet = "## 목표\n둘째 정리"
    index = 200
    while not needs_step_fold(messages, _budget()):
        messages += _read(index)
        index += 1
    _call(agent, messages, job)
    request = messages[1]["content"]
    assert request.count(FOLD_SHEET_OPEN) == 1
    assert "둘째 정리" in request and "300줄 줄이기" not in request
    assert request.endswith(REQUEST)


def test_a_tool_call_instead_of_a_sheet_is_dropped_and_the_fold_still_happens(tmp_path: Path) -> None:
    wants_a_tool = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "local_delete_file", "arguments": {"path": "x"}}}]}
    model = _WritesSheets(wants_a_tool)
    agent, _store, job = _delegated(tmp_path, model, on=True)
    executed: list[str] = []
    agent.gateway.execute = lambda name, *a, **k: executed.append(name)  # type: ignore[attr-defined]
    messages = _conversation(12)
    before = transcript_chars(messages)
    _call(agent, messages, job)
    assert not executed, "정리 대신 부른 도구는 실행하지 않는다"
    assert transcript_chars(messages) < before
    assert messages[1]["content"] == REQUEST


def test_a_failing_sheet_call_does_not_break_the_job(tmp_path: Path) -> None:
    model = _WritesSheets(RuntimeError("서버가 답하지 않았다"))
    agent, _store, job = _delegated(tmp_path, model, on=True)
    messages = _conversation(12)
    before = transcript_chars(messages)
    _call(agent, messages, job)
    assert transcript_chars(messages) < before
    assert messages[1]["content"] == REQUEST
    assert model.sent[-1][-1].get("role") == "tool", "판의 걸음은 평소대로 갔다"
