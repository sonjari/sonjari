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


# ── 어느 컴퓨터의 호스트인가 (2026-11-12 대표: 맥 앞에서 「누가 끼어드노」 — PC 의 클로드가 맥 손자리에 맡긴 줄 몰랐다) ──
from alture_jarvis.delegation import is_claude_code  # noqa: E402
from alture_jarvis.mcp_server import caller_place  # noqa: E402


def test_the_place_says_ssh_when_the_server_was_started_from_another_computer() -> None:
    assert caller_place({"SSH_CONNECTION": "100.1.2.3 50000 100.4.5.6 22"}) == "ssh"
    assert caller_place({"SSH_CLIENT": "100.1.2.3 50000 22"}) == "ssh"
    assert caller_place({}) == ""


def test_a_named_place_wins_and_is_kept_short() -> None:
    assert caller_place({"JARVIS_MCP_FROM": " 윈도우 PC ", "SSH_CONNECTION": "x"}) == "윈도우 PC"
    assert len(caller_place({"JARVIS_MCP_FROM": "가" * 100})) == 40


def test_the_place_never_changes_the_host_name_the_rest_matches_on() -> None:
    # 이름에 붙이면 `is_claude_code` 와 영수증이 클로드를 못 알아본다 — 그래서 칸을 따로 둔다.
    assert is_claude_code("Claude Code")
    assert not is_claude_code("Claude Code · 다른 컴퓨터")


def test_the_place_reaches_the_message_and_the_conversation_list(tmp_path) -> None:
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    runtime._learn_facts = lambda *_a, **_k: None
    runtime.agent.run = lambda *_a, **_k: AgentRunResult(
        answer="열었습니다.", steps=[{"tool": "browser_open", "ok": True}],
        verification={"completion_state": "complete"}, plan={},
        contract={"version": "task-contract-shadow-v1", "clauses": []},
    )
    job = runtime.enqueue("chat", "맡긴 일", {
        "prompt": "example.com 열어 제목", "display_prompt": "바깥 AI 가 맡긴 일 · example.com 열어 제목",
        "session_id": "mcp-far", "origin": "mcp", "agent_mode": "browser",
        "caller": "Claude Code", "caller_place": "ssh",
    })
    runtime._chat_job(runtime.store.get_job(job["id"]))
    runtime.memory.add_exchange("plain", "안녕", "안녕하세요")

    rows = {row["session_id"]: row for row in runtime.memory.list_sessions()}
    assert rows["mcp-far"]["caller"] == "Claude Code"
    assert rows["mcp-far"]["caller_place"] == "ssh"
    assert rows["plain"]["caller_place"] == ""
    asked = [m for m in runtime.memory.history("mcp-far") if m["role"] == "user"]
    assert asked and asked[0]["metadata"].get("caller_place") == "ssh"


def _sent_body(monkeypatch, env: dict[str, str]) -> dict:
    import asyncio
    import json

    import httpx

    from alture_jarvis.mcp_server import JarvisMcpBridge

    for key in ("JARVIS_MCP_FROM", "SSH_CONNECTION", "SSH_CLIENT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat":
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "j1"})
        return httpx.Response(404)

    async def run() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        bridge = JarvisMcpBridge("http://ontelic.test", "t0ken", client=client)
        _text, error = await bridge._delegate("sonjari_task", {"task": "example.com 열어 제목"}, caller="Claude Code")
        assert not error
        await client.aclose()

    asyncio.run(run())
    return sent[0]


def test_the_bridge_sends_the_place_only_when_it_runs_over_ssh(monkeypatch) -> None:
    far = _sent_body(monkeypatch, {"SSH_CONNECTION": "100.1.2.3 50000 100.4.5.6 22"})
    assert far["caller"] == "Claude Code" and far["caller_place"] == "ssh"
    near = _sent_body(monkeypatch, {})
    assert near["caller"] == "Claude Code" and "caller_place" not in near
