"""바깥 AI 의 과제 방·측정 방에서 배운 것은 사람에 관한 사실이 아니다 (2026-10-08 전수조사 3-7).

임시 방 표가 이름 가운데의 `-bench-` 만 봐서, `bench…` 로 시작하는 방과 바깥 AI 가 맡긴 과제 방(`mcp-…`)이 통째로 샜다.
살아 있는 사실 1,277개 가운데 `bench…` 방 것이 400개, `mcp-…` 방 것이 67개였다(합쳐 37%).

그 방에서는 이제 배우지 않고, 이미 들어가 있는 것은 **지우지 않고** 모델에게 실을 때만 거른다(서랍은 그대로다).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.fact_extract import ephemeral_session
from alture_jarvis.memory import ConversationMemory


@pytest.mark.parametrize("room", ["mcp-3f9a1c20", "MCP-list-77aa", "bench-form-a", "benchA-0921", "code-repo-bench-7", "x-bench-y", "smoke-1"])
def test_a_task_room_or_a_measuring_room_is_ephemeral(room: str) -> None:
    assert ephemeral_session(room)


@pytest.mark.parametrize("room", ["office-main", "jarvis-muzgvuhr", "", "workbench-notes", "my-mcp-ideas"])
def test_a_room_where_a_person_talks_is_not(room: str) -> None:
    assert ephemeral_session(room) == ""


@pytest.fixture()
def memory(tmp_path: Path) -> ConversationMemory:
    return ConversationMemory(tmp_path / "m.db")


def _fact(memory: ConversationMemory, room: str, subject: str, fact: str) -> int:
    message = memory.add_message(room, "user", f"{subject} {fact}")
    return memory.add_fact(kind="product", subject=subject, fact=fact, source_message_id=message, session_id=room)


def test_what_was_learned_in_a_task_room_is_not_carried_into_every_turn(memory: ConversationMemory) -> None:
    _fact(memory, "office-main", "사무실", "2층에 있다")
    _fact(memory, "mcp-3f9a1c20", "과제", "시험 파일은 고치지 않는다")
    _fact(memory, "bench-form-a", "벤치", "출력 폴더는 임시다")

    block = memory.learned_block()

    assert "2층에 있다" in block
    assert "시험 파일은 고치지 않는다" not in block and "출력 폴더는 임시다" not in block


def test_the_drawer_itself_is_left_as_it_is(memory: ConversationMemory) -> None:
    """거르는 것이지 지우는 것이 아니다 — 사람이 화면에서 보고 직접 지울 수 있어야 한다."""
    _fact(memory, "mcp-3f9a1c20", "과제", "시험 파일은 고치지 않는다")
    assert [row["fact"] for row in memory.live_facts()] == ["시험 파일은 고치지 않는다"]
