"""누가 손자리를 불렀나 (2026-09-30) — 클로드·코덱스를 같이 쓰면 누가 맡긴 일인지 몰랐다.

MCP `initialize` 의 clientInfo 를 과제에 실어 보내고, 대화 기록·목록에 남겨 화면이 출처 이음선을 두른다.
"""
from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis.agent import AgentRunResult
from alture_jarvis.api import create_app
from alture_jarvis.mcp_server import caller_of

from test_api import _config


def _context(info):
    return SimpleNamespace(session=SimpleNamespace(client_params=SimpleNamespace(client_info=info)))


def test_the_host_name_comes_from_client_info() -> None:
    assert caller_of(_context(SimpleNamespace(name="claude-code", title=None))) == "claude-code"
    assert caller_of(_context(SimpleNamespace(name="codex-mcp-client", title="Codex"))) == "Codex"


def test_a_missing_or_odd_session_never_blocks_the_task() -> None:
    assert caller_of(_context(None)) == ""
    assert caller_of(SimpleNamespace(session=SimpleNamespace(client_params=None))) == ""
    assert caller_of(object()) == ""


def test_the_caller_reaches_the_conversation_list(tmp_path) -> None:
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    runtime._learn_facts = lambda *_a, **_k: None
    runtime.agent.run = lambda *_a, **_k: AgentRunResult(
        answer="열었습니다.", steps=[{"tool": "browser_open", "ok": True}],
        verification={"completion_state": "complete"}, plan={},
        contract={"version": "task-contract-shadow-v1", "clauses": []},
    )
    job = runtime.enqueue("chat", "맡긴 일", {
        "prompt": "example.com 열어 제목", "display_prompt": "바깥 AI 가 맡긴 일 · example.com 열어 제목",
        "session_id": "mcp-abc", "origin": "mcp", "agent_mode": "browser", "caller": "claude-code",
    })
    runtime._chat_job(runtime.store.get_job(job["id"]))
    runtime.memory.add_exchange("plain", "안녕", "안녕하세요")

    rows = {row["session_id"]: row for row in runtime.memory.list_sessions()}
    assert rows["mcp-abc"]["caller"] == "claude-code"
    assert rows["plain"]["caller"] == ""
