"""「시스템 메시지는 맨 앞에만」 템플릿 (2026-10-01 밤 Ornith 1.5 35B 운영 판).

모델을 Ornith 로 바꾸자 운영 판이 `ollama_500: … raise_exception('System message must be at the beginning')` 로 죽었다.
손자리는 일하는 도중에 시스템 안내를 끼운다 — Qwen 3.6 템플릿은 받아 줬다. 실측(같은 밤): 중간 시스템이 든 대화를 그대로
보내면 500, `fold_late_system_messages` 로 접으면 200(답 「17」). 받아 주는 모델은 그대로 둔다(프롬프트가 바뀌면 성적이 흔들린다).
"""

from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis import ollama as ollama_mod
from alture_jarvis.ollama import fold_late_system_messages

MSGS = [
    {"role": "system", "content": "A"},
    {"role": "system", "content": "B"},
    {"role": "user", "content": "q"},
    {"role": "assistant", "content": "a"},
    {"role": "system", "content": "되받기"},
    {"role": "user", "content": "q2"},
]


def test_only_late_system_notes_move_and_the_head_is_merged() -> None:
    folded = fold_late_system_messages(MSGS)
    assert folded[0] == {"role": "system", "content": "A\n\nB"}
    assert [m["role"] for m in folded] == ["system", "user", "assistant", "user", "user"]
    assert folded[3]["content"] == "[시스템 안내]\n되받기"
    assert fold_late_system_messages([{"role": "user", "content": "x"}]) == [{"role": "user", "content": "x"}]


def test_a_refusing_template_is_remembered_and_retried_folded(monkeypatch) -> None:
    sent: list[list[str]] = []

    def post(url, json):
        roles = [m["role"] for m in json["messages"]]
        sent.append(roles)
        if roles.count("system") > 1 or (roles and "system" in roles[1:]):
            return SimpleNamespace(status_code=500, text='{"error":"... System message must be at the beginning ..."}')
        return SimpleNamespace(status_code=200, text="{}")

    client = ollama_mod.OllamaClient.__new__(ollama_mod.OllamaClient)
    client.config = SimpleNamespace(ollama_base_url="http://127.0.0.1:11434")
    monkeypatch.setattr(client, "_make_room_for", lambda model: None, raising=False)
    monkeypatch.setattr(client, "_note_prefix_break", lambda body: None, raising=False)
    monkeypatch.setattr(ollama_mod, "_SYSTEM_FIRST_ONLY", set())
    body = {"model": "strict-model", "messages": [dict(m) for m in MSGS]}
    response = client._post_chat(SimpleNamespace(post=post), body)
    assert response.status_code == 200
    assert "strict-model" in ollama_mod._SYSTEM_FIRST_ONLY
    # 두 번째 판부터는 처음부터 접어서 보낸다 — 500 을 다시 맞지 않는다.
    sent.clear()
    client._post_chat(SimpleNamespace(post=post), {"model": "strict-model", "messages": [dict(m) for m in MSGS]})
    assert len(sent) == 1 and sent[0].count("system") == 1


def test_a_template_that_accepts_is_left_alone(monkeypatch) -> None:
    sent: list[list[str]] = []
    client = ollama_mod.OllamaClient.__new__(ollama_mod.OllamaClient)
    client.config = SimpleNamespace(ollama_base_url="http://127.0.0.1:11434")
    monkeypatch.setattr(client, "_make_room_for", lambda model: None, raising=False)
    monkeypatch.setattr(client, "_note_prefix_break", lambda body: None, raising=False)
    monkeypatch.setattr(ollama_mod, "_SYSTEM_FIRST_ONLY", set())
    client._post_chat(SimpleNamespace(post=lambda url, json: sent.append([m["role"] for m in json["messages"]]) or
                                      SimpleNamespace(status_code=200, text="{}")),
                      {"model": "qwen3.6:35b-a3b", "messages": [dict(m) for m in MSGS]})
    assert sent == [[m["role"] for m in MSGS]]


def test_a_stream_refusal_is_caught_even_when_the_phrase_is_past_300_chars(monkeypatch) -> None:
    """2026-10-02 대표 운영 판: 첫 호출이 스트림인 코워크 조사가 매번 500 으로 죽었다.

    스트림 길은 본문을 300자로 잘라 문구를 찾았는데, 실제 Ollama 본문에서는 문구가 정확히 그 경계에서
    「Jinja Exception: System 」까지만 남았다. 사다리(첫 호출이 비스트림)는 멀쩡해서 못 봤다.
    """
    from test_streaming_404_retries_too import DONE, _Client, _client, _Response

    said = (
        '{"error":"{\\"error\\":{\\"code\\":500,\\"message\\":\\"\\n------------\\nWhile executing CallExpression '
        "at line 85, column 32 in source:\\n...first %}\u21b5            {{- raise_exception('System message must be at "
        "the beginnin...\\n                                           ^\\nError: Jinja Exception: System message must "
        'be at the beginning.\\",\\"type\\":\\"server_error\\"}}"}'
    )
    assert len(said) > 300
    client, module = _client(monkeypatch, [_Response(500, [], text=said), _Response(200, [DONE])], installed=True)
    monkeypatch.setattr(module, "_SYSTEM_FIRST_ONLY", set())
    result = client.chat_messages_stream([dict(m) for m in MSGS])
    assert _Client.opened == 2, "접어서 다시 열지 않았다"
    assert "답" in str(result.get("content") or "")
