"""대화 제목 · 앱 안 Claude 가 맡긴 방 (2026-10-26 대표 첫 실제 판).

- 목록 제목이 첫 말 앞부분이라 한눈에 뭔지 몰랐다 → 첫 답이 끝나면 내 PC 모델이 짧은 제목을 짓는다(쉴 때 · 생각 끔 · 짧게).
- 사람이 바꾼 제목은 모델이 덮지 않는다 · 못 지으면 첫 말 앞부분 그대로.
- 앱 안 Claude 가 손자리에게 맡긴 판(via=app)은 제 방(`mcp-…`)을 받지만 목록에 따로 세우지 않는다.
"""
from __future__ import annotations

import sqlite3

from alture_jarvis import conversation_title
from alture_jarvis.agent import AgentRunResult
from alture_jarvis.api import create_app
from alture_jarvis.memory import ConversationMemory

from test_api import _config


def test_model_title_replaces_the_first_words_and_person_title_wins(tmp_path):
    memory = ConversationMemory(tmp_path / "m.db")
    memory.add_exchange("a", "test_price.py 시험이 왜 실패하는지 찾아서 price.py를 고쳐 줘", "고쳤습니다")
    assert memory.list_sessions()[0]["title"].startswith("test_price.py 시험이")
    assert memory.set_title("a", "  price.py   합계 버그 수정 ", source="model")
    row = memory.list_sessions()[0]
    assert (row["title"], row["title_source"]) == ("price.py 합계 버그 수정", "model")
    # 사람이 바꾸면 그 뒤로 모델은 못 덮는다.
    assert memory.set_title("a", "내 가격 고치기", source="person")
    assert not memory.set_title("a", "다른 제목", source="model")
    assert memory.title_of("a") == {"title": "내 가격 고치기", "source": "person"}
    # 요약을 고쳐 써도 제목은 남고, 요약 유무 표시는 제목 때문에 켜지지 않는다.
    assert memory.list_sessions()[0]["has_summary"] is False
    memory.save_summary("a", "요약", 1)
    assert memory.title_of("a")["title"] == "내 가격 고치기"
    # 빈 제목 · 모르는 출처는 안 단다.
    assert not memory.set_title("b", "   ", source="model")
    assert not memory.set_title("b", "x", source="robot")
    # 서버에 글이 없는 대화(Claude)도 제목을 받는다 — 목록 문이 아니라 제목 문으로.
    assert memory.set_title("claude-only", "AI 에이전트 소식 장표", source="model")
    assert memory.titles()["claude-only"] == {"title": "AI 에이전트 소식 장표", "source": "model"}
    # 지우면 같이 지워진다.
    memory.delete_session("a")
    assert "a" not in memory.titles()


def test_old_database_gets_the_title_columns(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE conversation_summaries (session_id TEXT PRIMARY KEY, content TEXT NOT NULL, "
                 "through_message_id INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL)")
    conn.execute("INSERT INTO conversation_summaries VALUES ('s', '옛 요약', 3, 1.0)")
    conn.commit()
    conn.close()
    memory = ConversationMemory(path)
    assert memory.title_of("s") == {"title": "", "source": ""}
    assert memory.set_title("s", "새 제목")
    assert memory.summary("s")["content"] == "옛 요약"


def test_rooms_of_jobs_the_in_app_claude_handed_over_are_not_listed(tmp_path):
    memory = ConversationMemory(tmp_path / "m.db")
    memory.add_exchange("mcp-1a2b", "바깥 AI 가 맡긴 일 · 소식 3개 → 장표", "장표 4장",
                        user_metadata={"job_id": "c81a", "caller": "claude-code", "via": "app"})
    memory.add_exchange("mcp-3c4d", "바깥 AI 가 맡긴 일 · 레딧 조사", "표", user_metadata={"job_id": "d9", "caller": "claude-code"})
    memory.add_exchange("jarvis-x", "안녕", "안녕하세요", user_metadata={"job_id": "e1"})
    rows = {row["session_id"]: row for row in memory.list_sessions()}
    # 앱 안 Claude 가 맡긴 방은 빠지고, 바깥 클로드가 맡긴 방은 지금처럼 선다.
    assert set(rows) == {"mcp-3c4d", "jarvis-x"}
    assert rows["mcp-3c4d"]["caller"] == "claude-code"
    assert rows["mcp-3c4d"]["via"] == ""
    assert rows["jarvis-x"]["job_id"] == "e1"


def test_in_app_claude_handoff_keeps_its_door_in_the_record(tmp_path):
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    runtime._learn_facts = lambda *_a, **_k: None
    runtime.agent.run = lambda *_a, **_k: AgentRunResult(
        answer="열었습니다.", steps=[{"tool": "browser_open", "ok": True}],
        verification={"completion_state": "complete"}, plan={},
        contract={"version": "task-contract-shadow-v1", "clauses": []},
    )
    job = runtime.enqueue("chat", "맡긴 일", {
        "prompt": "example.com 열어 제목", "display_prompt": "바깥 AI 가 맡긴 일 · example.com 열어 제목",
        "session_id": "mcp-app1", "origin": "mcp", "agent_mode": "browser", "caller": "claude-code", "via": "app",
    })
    runtime._chat_job(runtime.store.get_job(job["id"]))
    assert "mcp-app1" not in {row["session_id"] for row in runtime.memory.list_sessions()}
    summary = next(row for row in runtime.store.list_job_summaries(10) if row["id"] == job["id"])
    assert summary["via"] == "app"


def test_title_parsing_keeps_only_a_short_title():
    assert conversation_title.parse('{"title": "price.py 합계 버그 수정"}', "ko") == "price.py 합계 버그 수정"
    assert conversation_title.parse('{"title": "「국내 AI 에이전트 소식 장표」."}', "ko") == "국내 AI 에이전트 소식 장표"
    assert conversation_title.parse('앞말 {"title": "가격 계산 고치기"} 뒷말', "ko") == "가격 계산 고치기"
    assert conversation_title.parse("", "ko") == ""
    assert conversation_title.parse("{}", "ko") == ""
    assert conversation_title.parse('{"title": "' + "가" * 40 + '"}', "ko") == ""
    assert conversation_title.parse('{"title": "Fix the price total bug"}', "en") == "Fix the price total bug"
    system, user = conversation_title.messages("가" * 5000, "답", "en")
    assert "English title" in system and len(user) < 2_000
    assert "15자 안팎" in conversation_title.messages("a", "b", "ko")[0]


class _QuietModel:
    """`background_chat` 만 흉내 — 무엇을 어떤 칸으로 불렀는지 적는다."""

    def __init__(self, answer: str | None):
        self.answer = answer
        self.calls: list[dict] = []

    def __call__(self, system, user, *, model, options, rewarm=True):
        self.calls.append({"system": system, "user": user, "model": model, "options": options, "rewarm": rewarm})
        return self.answer


def _runtime_with(tmp_path, answer):
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    runtime.__dict__["_title_sync"] = True
    model = _QuietModel(answer)
    runtime.ollama.background_chat = model
    published: list[tuple[str, dict]] = []
    original = runtime.events.publish
    runtime.events.publish = lambda name, payload: (published.append((name, payload)), original(name, payload))[1]
    return runtime, model, published


def test_first_answer_gets_a_model_title_with_thinking_off_and_a_short_call(tmp_path):
    runtime, model, published = _runtime_with(tmp_path, '{"title": "price.py 합계 버그 수정"}')
    runtime.memory.add_exchange("jarvis-1", "test_price.py 시험이 왜 실패하는지 찾아서 고쳐 줘", "고쳤습니다")
    assert runtime._title_soon("jarvis-1", "test_price.py 시험이 왜 실패하는지 찾아서 고쳐 줘", "고쳤습니다")
    assert runtime.memory.list_sessions()[0]["title"] == "price.py 합계 버그 수정"
    assert ("conversation_titled", {"session_id": "jarvis-1", "title": "price.py 합계 버그 수정"}) in published
    call = model.calls[0]
    assert call["options"]["num_predict"] == conversation_title.NUM_PREDICT
    assert call["rewarm"] is False
    # 대화 모델과 같은 창 크기(다른 크기로 부르면 모델을 다시 올린다).
    assert call["options"]["num_ctx"] == runtime.ollama._options(0.0, model=call["model"], role="chat")["num_ctx"]
    # 둘째 답부터는 안 짓는다 · 이미 제목이 있으면 안 짓는다.
    runtime.memory.add_exchange("jarvis-1", "하나 더", "네")
    assert not runtime._title_soon("jarvis-1", "하나 더", "네")
    assert not runtime._title_soon("jarvis-1", "x", "y", force=True)
    assert len(model.calls) == 1


def test_unusable_or_cut_off_title_leaves_the_first_words(tmp_path):
    runtime, _model, published = _runtime_with(tmp_path, "제목은 이렇습니다")
    runtime.memory.add_exchange("jarvis-2", "국내 AI 에이전트 소식 3개 찾아서 장표 4장으로 만들어 줘", "만들었습니다")
    runtime._title_soon("jarvis-2", "국내 AI 에이전트 소식 3개 찾아서 장표 4장으로 만들어 줘", "만들었습니다")
    assert runtime.memory.list_sessions()[0]["title"].startswith("국내 AI 에이전트 소식")
    assert any(name == "conversation_title_skipped" for name, _ in published)
    # 사람 일이 와서 끊긴 부르기(None)도 제목을 안 단다.
    runtime2, _m, _p = _runtime_with(tmp_path / "b", None)
    runtime2.memory.add_exchange("jarvis-3", "안녕", "안녕하세요")
    runtime2._title_soon("jarvis-3", "안녕", "안녕하세요")
    assert runtime2.memory.title_of("jarvis-3")["title"] == ""


def test_test_runtime_does_not_call_the_model_unless_asked(tmp_path):
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    model = _QuietModel('{"title": "x"}')
    runtime.ollama.background_chat = model
    runtime.memory.add_exchange("jarvis-4", "안녕", "안녕하세요")
    assert not runtime._title_soon("jarvis-4", "안녕", "안녕하세요")
    assert model.calls == []


def test_auto_title_door_for_claude_conversations(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    runtime.__dict__["_title_sync"] = True
    runtime.ollama.background_chat = _QuietModel('{"title": "AI 에이전트 소식 장표"}')
    client = TestClient(app)
    headers = {"X-JARVIS-TOKEN": runtime.config.control_token}
    response = client.post("/v1/conversations/jarvis-claude/auto-title", json={"user": "국내 AI 에이전트 소식 3개 찾아서 장표", "answer": "장표 4장"}, headers=headers)
    assert response.status_code == 200, response.text
    titles = client.get("/v1/conversation-titles", headers=headers).json()["items"]
    assert titles["jarvis-claude"]["title"] == "AI 에이전트 소식 장표"
    renamed = client.post("/v1/conversations/jarvis-claude/title", json={"title": "내 장표"}, headers=headers).json()
    assert renamed["source"] == "person"
    again = client.post("/v1/conversations/jarvis-claude/auto-title", json={"user": "x", "answer": "y"}, headers=headers).json()
    assert again == {"scheduled": False, "title": "내 장표"}
