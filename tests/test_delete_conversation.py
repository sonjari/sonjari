"""대화 지우기 (2026-09-24 사용자 요청: 「채팅창 삭제가 없다」). 목록·기록이 사라지고, 다른 대화는 그대로다."""

from __future__ import annotations

from alture_jarvis.memory import ConversationMemory


def test_deleting_a_conversation_removes_it_and_only_it(tmp_path):
    memory = ConversationMemory(tmp_path / "m.db")
    memory.add_message("a", "user", "사람인에서 공고 3개 찾아줘")
    memory.add_message("a", "assistant", "표")
    memory.add_message("b", "user", "안녕")
    assert {row["session_id"] for row in memory.list_sessions()} == {"a", "b"}

    removed = memory.delete_session("a")
    assert removed["conversation_messages"] == 2
    assert [row["session_id"] for row in memory.list_sessions()] == ["b"]
    assert memory.history("a") == []
    # 다시 열어도(백필이 돌아도) 살아나지 않는다.
    again = ConversationMemory(tmp_path / "m.db")
    assert [row["session_id"] for row in again.list_sessions()] == ["b"]
