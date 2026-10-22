"""서기(2026-10-21) — 클로드 코드 대화 기록에서 손자리가 「이야기 카드」 초안을 쌓는다.

지키는 것:
- 사람의 말과 클로드의 글만 읽는다(도구 결과 · 시스템 안내 · 잘릴 때 요약 · 곁가지는 뺀다). 비밀값은 모델에게 가기 전에 걷는다.
- 인용이 그 말에 글자 그대로 없으면 버린다(지어낸 줄 차단).
- 1.3GB 기록에서도 매번 처음부터 읽지 않는다 — 바이트 자리로 잇고, 처음 보는 기록은 끝에서만.
- 사람 일이 오면 끊기고, 끊기면 읽은 자리를 옮기지 않는다.
- 기본 꺼짐 · 고른 폴더만 · 켠 PC 에서만 클로드에게 문이 보인다.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alture_jarvis import scribe
from alture_jarvis.scribe import Scribe, draft, read_turns_from, tail_start

# 시험용 가짜 키 — 파일에는 키 모양 글자를 두지 않는다(공개본 검사가 막는다). 실행할 때 붙여 만든다.
_FAKE_KEY = "sk-" + "ant-" + "abcdef" + "x" * 24


def _row(kind: str, text: str | list[Any], **extra: Any) -> str:
    return json.dumps({"type": kind, "message": {"role": kind, "content": text}, **extra}, ensure_ascii=False) + "\n"


def _log(tmp_path: Path, rows: list[str], name: str = "s1.jsonl") -> Path:
    path = tmp_path / "proj" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(rows), encoding="utf-8")
    return path


def _talk(n: int, start: int = 0) -> list[str]:
    rows = []
    for index in range(start, start + n):
        rows.append(_row("user", f"사람 말 {index}: 이건 {index}번으로 정하자"))
        rows.append(_row("assistant", [{"type": "text", "text": f"클로드 답 {index}: 그렇게 하겠습니다"}]))
    return rows


def test_only_the_words_of_the_person_and_claude_are_read(tmp_path: Path) -> None:
    rows = [
        _row("user", "첫 말 <system-reminder>숨은 안내</system-reminder>"),
        _row("user", [{"type": "tool_result", "content": "도구 결과 수 MB"}]),
        _row("assistant", [{"type": "tool_use", "name": "Bash"}]),
        _row("user", "잘릴 때 요약", isCompactSummary=True),
        _row("assistant", [{"type": "text", "text": "곁가지 답"}], isSidechain=True),
        _row("assistant", [{"type": "text", "text": "열쇠는 " + _FAKE_KEY + " 입니다"}]),
        json.dumps({"type": "progress"}) + "\n",
    ]
    path = _log(tmp_path, rows)
    turns, offset, line = read_turns_from(path, 0, 0, 100)
    assert [(t.line, t.role) for t in turns] == [(0, "사람"), (5, "클로드")]
    assert "숨은 안내" not in turns[0].text
    assert _FAKE_KEY not in turns[1].text, "비밀값은 모델에게 가기 전에 걷는다"
    assert offset == path.stat().st_size and line == len(rows)


def test_a_half_written_last_line_is_not_read_or_skipped(tmp_path: Path) -> None:
    """클로드가 아직 쓰는 줄을 읽고 자리를 넘기면 그 말을 잃는다."""
    path = _log(tmp_path, _talk(1))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"user","message":{"role":"user","content":"쓰는 중')
    turns, offset, line = read_turns_from(path, 0, 0, 100)
    assert len(turns) == 2 and line == 2
    assert offset < path.stat().st_size


def test_byte_offsets_continue_where_the_last_chunk_stopped(tmp_path: Path) -> None:
    path = _log(tmp_path, _talk(10))
    first, offset, line = read_turns_from(path, 0, 0, 7)
    rest, _, _ = read_turns_from(path, offset, line, 100)
    assert [t.line for t in first + rest] == list(range(20)), "이어 읽어도 빠지거나 겹치는 말이 없다"


def test_a_new_log_is_read_from_its_tail_with_true_line_numbers(tmp_path: Path) -> None:
    path = _log(tmp_path, _talk(200))
    offset, line = tail_start(path, 2000)
    assert 0 < offset < path.stat().st_size
    turns, _, _ = read_turns_from(path, offset, line, 5)
    with path.open(encoding="utf-8") as handle:
        lines = handle.readlines()
    for turn in turns:
        assert turn.text.split(":")[0] in lines[turn.line], "줄 번호는 근거 자리 — 실제 그 줄이어야 한다"


def test_quotes_that_are_not_in_the_turn_are_dropped(tmp_path: Path) -> None:
    turns, _, _ = read_turns_from(_log(tmp_path, _talk(2)), 0, 0, 100)
    reply = json.dumps({"items": [
        {"kind": "decided", "text": "0번으로 정함", "line": 0, "quote": "이건 0번으로 정하자"},
        {"kind": "decided", "text": "지어냄", "line": 0, "quote": "3번으로 바꾸자"},
        {"kind": "decided", "text": "다른 줄 인용", "line": 1, "quote": "이건 0번으로 정하자"},
        {"kind": "made_up_kind", "text": "칸 없음", "line": 0, "quote": "이건 0번으로 정하자"},
    ]}, ensure_ascii=False)
    kept = draft(turns, lambda system, user: reply)
    assert [item["text"] for item in kept] == ["0번으로 정함"]


def _reply_for(user: str) -> str:
    first = user.split("\n", 1)[0]
    line = int(first[1:first.index("]")])
    quote = first.split(": ", 1)[1][:10]
    # 줄마다 다른 글 — 2차부터 같은 말은 또 적지 않는다(`_same_story`).
    return json.dumps({"items": [{"kind": "open", "text": f"남은 일 {line}", "line": line, "quote": quote}]}, ensure_ascii=False)


def test_one_chunk_per_run_and_the_place_moves_only_when_done(tmp_path: Path) -> None:
    path = _log(tmp_path, _talk(50))
    book = Scribe(tmp_path / "data", [path.parent])

    # 사람 일이 와서 끊기면(None) 자리를 옮기지 않는다.
    assert book.run_once(lambda s, u: None)["why"] == "사람 일이 와서 비켰다"
    assert book.recent() == []
    first = book.run_once(lambda s, u: _reply_for(u))
    assert first["done"] and first["turns"] == Scribe.CHUNK and first["items"] == 1
    second = book.run_once(lambda s, u: _reply_for(u))
    assert second["done"] and second["turns"] == Scribe.CHUNK
    lines = [item["line"] for item in book.recent()]
    assert lines[0] == 0 and lines[1] == Scribe.CHUNK, "끊긴 판 뒤에도 처음부터 — 말을 잃지 않는다"
    assert book.recent(session="s1")[0]["session"] == "s1" and book.recent(session="zz") == []


def test_too_few_new_words_wait_and_old_logs_are_left_alone(tmp_path: Path) -> None:
    short = _log(tmp_path, _talk(3), "short.jsonl")
    old = _log(tmp_path, _talk(30), "old.jsonl")
    week_ago = time.time() - 7 * 86400
    os.utime(old, (week_ago, week_ago))
    book = Scribe(tmp_path / "data", [short.parent])
    assert book.run_once(lambda s, u: _reply_for(u)) == {"done": False, "why": "읽을 새 말이 없음"}


def test_the_first_sight_of_a_huge_log_saves_its_start_at_once(tmp_path: Path, monkeypatch) -> None:
    """말이 모자란 동안 매번 1.3GB 줄바꿈을 다시 세지 않는다."""
    path = _log(tmp_path, _talk(2))
    counted = []
    real = scribe.tail_start
    monkeypatch.setattr(scribe, "tail_start", lambda p, n: counted.append(p) or real(p, n))
    book = Scribe(tmp_path / "data", [path.parent])
    book.run_once(lambda s, u: _reply_for(u))
    book.run_once(lambda s, u: _reply_for(u))
    assert len(counted) == 1


# ---- 모델 서버 · 설정 · 클로드 문 ----------------------------------------------------------


def test_a_person_request_cancels_the_background_call() -> None:
    from alture_jarvis.ollama import OllamaClient

    client = OllamaClient.__new__(OllamaClient)
    closed = []
    client.__dict__["_background_client"] = SimpleNamespace(close=lambda: closed.append(True))
    client.__dict__["_front_prime_client"] = None
    client._front_seen({"model": "m", "messages": [{"role": "user", "content": "x"}]})
    assert closed == [True] and client.__dict__["_background_cancelled"] is True


def test_scribe_is_off_by_default_and_settable_live(tmp_path: Path) -> None:
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.settings import BY_KEY, SettingsService

    config = JarvisConfig(data_dir=tmp_path)
    assert config.scribe_enabled is False and config.scribe_folders == ""
    assert BY_KEY["scribe_enabled"].live and BY_KEY["scribe_folders"].live
    result = SettingsService(config).patch({"scribe_enabled": True, "scribe_folders": [str(tmp_path / "a"), str(tmp_path / "b")]})
    assert result.get("ok") is not False
    assert config.scribe_enabled is True and config.scribe_folders == f"{tmp_path / 'a'};{tmp_path / 'b'}"


def test_the_runtime_story_reads_the_cards(tmp_path: Path) -> None:
    from alture_jarvis.runtime import JarvisRuntime

    path = _log(tmp_path, _talk(20))
    Scribe(tmp_path / "data", [path.parent]).run_once(lambda s, u: _reply_for(u))
    fake = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path / "data", scribe_enabled=True, scribe_folders=str(path.parent)))
    fake._scribe_folders = lambda: JarvisRuntime._scribe_folders(fake)
    story = JarvisRuntime.scribe_story(fake, limit=10)
    assert story["enabled"] and story["count"] == 1 and "## 남은 일 · 약속" in story["card"]


class _Response:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _Client:
    def __init__(self, story: dict[str, Any]) -> None:
        self.story = story

    async def get(self, url: str, **kwargs: Any) -> Any:
        if url.endswith("/v1/scribe/story"):
            return _Response(self.story)
        if url.endswith("/v1/tools"):
            return _Response([])
        return _Response({"packs": []})


def _names(story: dict[str, Any]) -> list[str]:
    from alture_jarvis.mcp_server import JarvisMcpBridge

    return [tool["name"] for tool in asyncio.run(JarvisMcpBridge(token="t", client=_Client(story)).list_tools())]


def test_the_story_door_shows_only_where_the_scribe_is_on(monkeypatch) -> None:
    """09-23 에 비용을 재서 정한 기본 문 셋은 그대로 — 서기를 켠 PC 에서만 넷째 문이 보인다."""
    monkeypatch.delenv("JARVIS_MCP_TOOLSET", raising=False)
    assert "sonjari_story" not in _names({"enabled": False, "count": 0})
    assert "sonjari_story" in _names({"enabled": True, "count": 0})


def test_the_story_door_says_why_it_is_empty() -> None:
    from alture_jarvis.mcp_server import JarvisMcpBridge

    off, failed = asyncio.run(JarvisMcpBridge(token="t", client=_Client({"enabled": False, "count": 0})).call("sonjari_story", {}))
    assert not failed and "꺼져 있습니다" in off and "대신 켜지 마세요" in off
    empty, _ = asyncio.run(JarvisMcpBridge(token="t", client=_Client({"enabled": True, "count": 0})).call("sonjari_story", {}))
    assert "「정한 것이 없었다」는 뜻이 아닙니다" in empty
    full, _ = asyncio.run(JarvisMcpBridge(token="t", client=_Client(
        {"enabled": True, "count": 1, "card": "## 정한 것\n- x  (줄 3 · 「y」)"})).call("sonjari_story", {"limit": 5}))
    assert full.startswith("서기 카드 1줄") and "(줄 3" in full


def test_the_story_door_is_described_in_english_without_korean() -> None:
    import re

    from alture_jarvis.delegation import STORY_TOOL, localized_tool

    en = localized_tool(STORY_TOOL, "en")
    assert not re.search(r"[가-힣]", json.dumps(en, ensure_ascii=False))
    assert set(en["parameters"]["properties"]) == set(STORY_TOOL["parameters"]["properties"])


def test_the_tick_waits_for_idle_and_a_quiet_model(tmp_path: Path) -> None:
    """사람이 일하는 중이거나 방금 모델을 썼으면 서기는 돌지 않는다 — 10-21 새벽 15.8초 기다림의 재발 방지."""
    from alture_jarvis.runtime import JarvisRuntime

    path = _log(tmp_path, _talk(20))
    asked = []
    state = SimpleNamespace(state="busy")
    fake = SimpleNamespace(
        config=SimpleNamespace(data_dir=tmp_path / "data", scribe_enabled=True, scribe_folders=str(path.parent),
                               model_for=lambda role: "m", num_ctx_for=lambda role: 8192),
        state=SimpleNamespace(snapshot=lambda: state),
        ollama=SimpleNamespace(background_chat=lambda s, u, **k: asked.append(u) or _reply_for(u)),
        SCRIBE_QUIET_SEC=JarvisRuntime.SCRIBE_QUIET_SEC,
    )
    fake._scribe_folders = lambda: JarvisRuntime._scribe_folders(fake)
    assert JarvisRuntime._scribe_tick(fake) == {"skipped": "일하는 중"}
    from alture_jarvis.models import JarvisState

    state.state = JarvisState.IDLE
    fake.ollama.__dict__["_last_send_at"] = time.monotonic()
    assert JarvisRuntime._scribe_tick(fake) == {"skipped": "방금 모델을 썼다"}
    fake.ollama.__dict__["_last_send_at"] = time.monotonic() - JarvisRuntime.SCRIBE_QUIET_SEC - 1
    ran = JarvisRuntime._scribe_tick(fake)
    assert ran["ran"] and ran["done"] and len(asked) == 1
