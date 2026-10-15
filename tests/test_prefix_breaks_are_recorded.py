"""앞부분이 바뀐 요청은 **어디가 바뀌었는지** 남는다 (2026-09-28 레딧 판).

qwen3.6 은 llama.cpp 가 저장한 체크포인트로만 캐시를 되돌린다. 전사 중간이 바뀌면 걸음마다 1만 토큰을 다시 읽는다.
무엇이 앞을 바꾸는지 추측 대신 기록으로 잡는다. 뒤에 붙기만 한 요청은 적지 않는다(소음이 되면 아무도 안 읽는다).
"""

import json
from types import SimpleNamespace

from alture_jarvis.ollama import OllamaClient

SYSTEM = {"role": "system", "content": "규칙"}
TASK = {"role": "user", "content": "레딧 댓글 정리"}


def _client(tmp_path):
    return SimpleNamespace(config=SimpleNamespace(data_dir=str(tmp_path)))


def _call(client, messages, tools=("browser_extract",)):
    OllamaClient._note_prefix_break(client, {"model": "m", "messages": messages, "tools": list(tools)})


def _rows(tmp_path):
    path = tmp_path / "prefix_breaks.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_appending_is_not_a_break(tmp_path):
    client = _client(tmp_path)
    _call(client, [SYSTEM, TASK])
    _call(client, [SYSTEM, TASK, {"role": "assistant", "content": ""}, {"role": "tool", "content": "본문"}])
    assert _rows(tmp_path) == []


def test_a_rewritten_middle_message_is_recorded_with_its_place(tmp_path):
    client = _client(tmp_path)
    snapshot = {"role": "tool", "tool_name": "browser_snapshot", "content": "버튼 96개 " * 50}
    _call(client, [SYSTEM, TASK, snapshot, {"role": "tool", "tool_name": "browser_extract", "content": "본문"}])
    folded = {"role": "tool", "tool_name": "browser_snapshot", "content": "(접힘) browser_snapshot"}
    _call(client, [SYSTEM, TASK, folded, {"role": "tool", "tool_name": "browser_extract", "content": "본문"}])
    [row] = _rows(tmp_path)
    assert row["index"] == 2 and row["tool_name"] == "browser_snapshot"
    assert row["keys_changed"] == ["content"] and row["new_head"].startswith("(접힘)")


def test_a_changed_tool_list_is_a_break_even_when_messages_only_grow(tmp_path):
    client = _client(tmp_path)
    _call(client, [SYSTEM, TASK], tools=("a",))
    _call(client, [SYSTEM, TASK, {"role": "tool", "content": "x"}], tools=("a", "b"))
    [row] = _rows(tmp_path)
    assert row["tools_changed"] is True and "index" not in row


def test_the_recorder_never_breaks_a_run(tmp_path):
    broken = SimpleNamespace(config=SimpleNamespace(data_dir=str(tmp_path / "없는" / "\0")))
    _call(broken, [SYSTEM, TASK])
    _call(broken, [SYSTEM, {"role": "user", "content": "다른 요청"}])  # 적기에 실패해도 예외가 안 나야 한다


def test_a_changed_option_is_recorded_with_its_values(tmp_path):
    """2026-09-28 C1: 판 안에서 옵션이 바뀌어 32K 러너가 128K 로 갈렸는데 어느 값인지 기록에 없었다."""
    client = _client(tmp_path)
    OllamaClient._note_prefix_break(client, {"model": "m", "messages": [SYSTEM, TASK], "options": {"num_ctx": 32768}})
    OllamaClient._note_prefix_break(client, {"model": "m", "messages": [SYSTEM, TASK, {"role": "assistant", "content": "x"}],
                                             "options": {"num_ctx": 131072}})

    assert _rows(tmp_path)[-1]["options_diff"] == {"num_ctx": [32768, 131072]}
