"""출력 한도에 걸려 잘린 도구 인자는 실행하지 않고 「잘렸다」고 돌려준다 · 긴 글은 이어 쓰기로 나눠 쓴다 (2026-11-09 · 하네스 후보 20).

맥 손자리(Strata 다리)에게 「유튜브 자막 전체(약 2.2만 자)를 md 로 저장」을 두 번 맡겼고 두 번 다 파일이 안 생겼다.
job 9391c6fc · 1f75fb4a: 모델이 긴 본문을 `local_write_document` 인자에 담다 한 번 쓰기 한도(8,192토큰)에서 끊겼고
(content_cuts: length_limit · had_tool_call · tokens 8192 — 판마다 2~3번), 반쪽 JSON 인자는 `{}` 가 되었다. 하네스는 그것을 그대로
실행해 `path_required`(어디에 쓸지 없다)라는 **틀린 까닭**을 돌려줬고, 모델은 같은 긴 호출을 되풀이하다 partial 로 끝났다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import ToolResult
from alture_jarvis.truncated_call import truncated_tool_call

_CUT = {"done_reason": "length", "eval_count": 8192}

_DEFS = [
    {"type": "function", "function": {"name": "local_write_document", "description": "d", "parameters": {
        "type": "object", "properties": {"path": {"type": "string"}, "text": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "local_write_file", "description": "d", "parameters": {
        "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "browser_snapshot", "description": "d", "parameters": {
        "type": "object", "properties": {}}}},
]


def _call(name: str, arguments: Any) -> dict:
    return {"function": {"name": name, "arguments": arguments}}


# ── 판정 하나만 ───────────────────────────────────────────────────────────────────


def test_a_cut_turn_with_empty_arguments_is_truncated() -> None:
    calls = [_call("local_write_document", {})]
    found = truncated_tool_call({"_metrics": _CUT, "tool_calls": calls}, calls[0], calls, _DEFS)
    assert found and found["tool"] == "local_write_document"
    assert found["missing"] == ["path"] and found["limit_tokens"] == 8192


def test_a_cut_turn_with_unreadable_json_string_is_truncated() -> None:
    calls = [_call("local_write_file", '{"path": "a.md", "content": "앞부분만 오다가')]
    assert truncated_tool_call({"_metrics": _CUT}, calls[0], calls, _DEFS)


def test_without_the_length_cut_a_missing_path_is_not_called_truncated() -> None:
    """한도에 안 닿았으면 모델이 정말 빠뜨린 것이다 — 예전처럼 도구가 path_required 로 답한다."""
    calls = [_call("local_write_document", {})]
    assert truncated_tool_call({"_metrics": {"done_reason": "stop", "eval_count": 120}}, calls[0], calls, _DEFS) is None
    assert truncated_tool_call({}, calls[0], calls, _DEFS) is None


def test_a_cut_turn_whose_last_call_is_whole_is_not_truncated() -> None:
    calls = [_call("local_write_file", {"path": "a.md", "content": "다 왔다"})]
    assert truncated_tool_call({"_metrics": _CUT}, calls[0], calls, _DEFS) is None


def test_a_tool_with_nothing_required_is_not_called_truncated() -> None:
    calls = [_call("browser_snapshot", {})]
    assert truncated_tool_call({"_metrics": _CUT}, calls[0], calls, _DEFS) is None


def test_only_the_last_call_of_a_cut_turn_can_be_the_cut_one() -> None:
    calls = [_call("local_write_file", {}), _call("local_write_file", {"path": "b.md", "content": "x"})]
    assert truncated_tool_call({"_metrics": _CUT}, calls[0], calls, _DEFS) is None


# ── 판 안에서 ────────────────────────────────────────────────────────────────────


class _Tools:
    names = {"local_write_document", "local_write_file", "browser_snapshot"}
    ollama_tools = _DEFS


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name, arguments, *, job_id=""):  # noqa: ANN001, ANN201
        self.calls.append((name, dict(arguments)))
        if not str(arguments.get("path") or "").strip():
            return ToolResult(False, name, error="path_required — 어디에 쓸지(path)가 없다")
        return ToolResult(True, name, result={"action": name, "path": str(arguments["path"]), "verified": True})


class _Model:
    def __init__(self, first: dict) -> None:
        self.first = first
        self.calls = 0
        self.seen: list[str] = []

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if self.calls == 1:
            return self.first
        self.seen.append("\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "tool"))
        return {"role": "assistant", "content": "알겠습니다. 여기까지 했습니다."}


def _run(tmp_path: Path, first: dict) -> tuple[Any, _Gateway, _Model]:
    cfg = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                       browser_enabled=True, agent_stream_enabled=False)
    store = JobStore(tmp_path / "jarvis.db")
    gateway, model = _Gateway(), _Model(first)
    agent = BrowserAgent(cfg, model, gateway, SimpleNamespace(status=lambda: {"started": True}), _Tools(), store, EventBus())
    job = store.create_job("chat", "맡긴 일", {"prompt": "메모를 notes.md 로 저장해 줘"})
    store.claim_next()
    result = agent.run("메모를 notes.md 로 저장해 줘", job_id=job["id"], origin="mcp")
    return result, gateway, model


def test_a_cut_write_is_not_run_and_the_model_hears_it_was_cut(tmp_path: Path) -> None:
    first = {"role": "assistant", "content": "", "_metrics": dict(_CUT),
             "tool_calls": [_call("local_write_document", {})]}
    _result, gateway, model = _run(tmp_path, first)

    assert gateway.calls == [], "잘린 인자로 도구를 실행했다"
    told = model.seen[0]
    assert "tool_arguments_truncated" in told and "8192" in told
    assert "append" in told and "local_write_document" in told, "나눠 쓸 길(이어 쓰기)을 정확히 가리켜야 한다"
    assert "path_required" not in told


def test_a_missing_path_without_a_cut_still_goes_to_the_tool(tmp_path: Path) -> None:
    first = {"role": "assistant", "content": "", "_metrics": {"done_reason": "stop", "eval_count": 300},
             "tool_calls": [_call("local_write_document", {"text": "짧은 메모"})]}
    _result, gateway, model = _run(tmp_path, first)

    assert gateway.calls and gateway.calls[0][0] == "local_write_document", "평소 호출은 그대로 실행돼야 한다"
    assert "tool_arguments_truncated" not in model.seen[0]
    assert "path_required" in model.seen[0]


# ── 이어 쓰기 ────────────────────────────────────────────────────────────────────


def _local(tmp_path: Path, monkeypatch) -> LocalComputerTools:
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: None, raising=False)
    return LocalComputerTools(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "documents", local_computer_enabled=True,
    ))


_PART1 = "# 자막\n\n" + "가나다라마바사 " * 300
_PART2 = "아자차카타파하 " * 300 + "\n끝."


def test_write_file_in_two_parts_keeps_the_whole_text(tmp_path: Path, monkeypatch) -> None:
    tools = _local(tmp_path, monkeypatch)
    target = tools.documents_root / "자막.md"
    tools.write_file({"path": str(target), "content": _PART1, "__job_id": "j1"})
    tools.write_file({"path": str(target), "content": _PART2, "append": True, "__job_id": "j1"})
    assert target.read_text(encoding="utf-8") == _PART1 + _PART2


def test_write_file_without_append_still_replaces(tmp_path: Path, monkeypatch) -> None:
    tools = _local(tmp_path, monkeypatch)
    target = tools.documents_root / "a.md"
    tools.write_file({"path": str(target), "content": "옛 글", "__job_id": "j1"})
    tools.write_file({"path": str(target), "content": "새 글", "__job_id": "j1"})
    assert target.read_text(encoding="utf-8") == "새 글"


def test_write_document_md_in_two_parts_keeps_both_in_order(tmp_path: Path, monkeypatch) -> None:
    tools = _local(tmp_path, monkeypatch)
    first = tools.write_document_file({"path": "자막.md", "format": "md", "text": _PART1, "__job_id": "j1"})
    second = tools.write_document_file({"path": "자막.md", "format": "md", "text": _PART2, "append": True, "__job_id": "j1"})
    assert first["path"] == second["path"]
    body = Path(second["path"]).read_text(encoding="utf-8")
    assert "가나다라마바사" in body and "아자차카타파하" in body and body.rstrip().endswith("끝.")
    assert body.index("가나다라마바사") < body.index("아자차카타파하")
    assert second.get("appended") is True


def test_write_document_md_without_append_still_replaces(tmp_path: Path, monkeypatch) -> None:
    tools = _local(tmp_path, monkeypatch)
    tools.write_document_file({"path": "b.md", "format": "md", "text": "옛 글", "__job_id": "j1"})
    second = tools.write_document_file({"path": "b.md", "format": "md", "text": "새 글", "__job_id": "j1"})
    body = Path(second["path"]).read_text(encoding="utf-8")
    assert "새 글" in body and "옛 글" not in body


def test_append_is_refused_for_binary_documents(tmp_path: Path, monkeypatch) -> None:
    tools = _local(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="append_text_only"):
        tools.write_document_file({"path": "c.docx", "format": "docx", "text": "x", "append": True, "__job_id": "j1"})
