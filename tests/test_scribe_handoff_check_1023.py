"""서기 3차 (2026-10-23 밤) — 압축 뒤 다시 넣은 「남은 일」 넷이 이미 끝났거나 뒤집힌 채였다(세션 794912da).

원인과 고침:
1. 새 카드 쓰기와 닫기를 한 부르기에 같이 시켰더니, 끝낸 말이 바로 다음 조각에 있어도 닫지 않았다 → 닫기를 따로 부른다.
   확실하지 않으면 닫지 않고 「이 뒤 줄 N에서 같은 이야기 — 확인」 표시만(대표 제안 「넘기기 전에 대조」). 규칙이 바뀌면 최근 구간을 한 번 다시 읽는다.
2. 클로드가 일하는 동안 사람이 친 말 · 알림은 `attachment`(queued_command)로만 남는데 서기가 안 읽었다(사람 말 799개) → 읽는다.
3. 훅이 「일하는 방식」 파일을 넣는데 CLAUDE.md 가 이미 `@` 로 끼워 넣고 있었다(두 번) → CLAUDE.md 에 있으면 훅은 뺀다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis import claude_hooks
from alture_jarvis.scribe import (CLOSE_VERSION, Scribe, Turn, _turn_of, card_id, check_cards, offset_of_line, read_turns_from,
                                  render)


def _user(text: str, **extra) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}, **extra}, ensure_ascii=False) + "\n"


def _queued(text: str, *, sidechain: bool = False) -> list[str]:
    """실제 기록 꼴 그대로 — 넣기(queue-operation) · 붙임(attachment) · 빼기 · 요청 사본(api-request-blob) 넷이 찍힌다."""
    stamp = "2026-10-23T13:39:57.747Z"
    return [json.dumps(row, ensure_ascii=False) + "\n" for row in (
        {"type": "queue-operation", "operation": "enqueue", "timestamp": stamp, "content": text},
        {"type": "attachment", "isSidechain": sidechain, "timestamp": stamp,
         "attachment": {"type": "queued_command", "prompt": text, "commandMode": "prompt"}},
        {"type": "queue-operation", "operation": "remove", "timestamp": stamp, "content": text},
        {"type": "api-request-blob", "message": {"role": "user", "content": text}},
    )]


# ── 2. 일하는 중에 친 사람 말 ───────────────────────────────────────────────────────────────────


def test_a_message_typed_while_claude_works_is_read_once_as_the_person(tmp_path: Path) -> None:
    log = tmp_path / "s1.jsonl"
    log.write_text(_user("처음 말") + "".join(_queued("젬마 4 26B는 우리가 별로라서 안했다이가")) + _user("다음 말"), encoding="utf-8")
    turns = read_turns_from(log, 0, 0, 50)[0]
    assert [(t.line, t.role, t.text) for t in turns] == [
        (0, "사람", "처음 말"), (2, "사람", "젬마 4 26B는 우리가 별로라서 안했다이가"), (5, "사람", "다음 말")], \
        "붙임 줄 하나만 읽는다(넣기 · 빼기 · 요청 사본은 사본이라 안 읽는다)"
    assert turns[1].at, "그 말의 시각도 단다"


def test_queued_notifications_and_block_prompts_are_read_but_side_chains_are_not() -> None:
    blocks = json.dumps({"type": "attachment", "timestamp": "2026-10-23T13:39:57Z", "attachment": {
        "type": "queued_command", "prompt": [{"type": "text", "text": "스위치 판 끝남 2/3"}, {"type": "image", "source": {}}]}},
        ensure_ascii=False)
    assert _turn_of(7, blocks).text == "스위치 판 끝남 2/3"
    side = _queued("곁가지 말", sidechain=True)[1]
    assert _turn_of(1, side) is None
    hook = json.dumps({"type": "attachment", "attachment": {"type": "hook_success", "stdout": "queued_command"}})
    assert _turn_of(1, hook) is None, "다른 붙임은 그대로 안 읽는다"


def test_the_open_line_hand_shows_queued_messages_too(tmp_path: Path) -> None:
    log = tmp_path / "s1.jsonl"
    log.write_text(_user("처음 말") + "".join(_queued("한국어 3개는 통과")) + _user("다음 말"), encoding="utf-8")
    shown = claude_hooks.open_line(str(log), 2)
    assert "▶ [2] 사람: 한국어 3개는 통과" in shown and shown.count("한국어 3개는 통과") == 1


# ── 1. 닫기를 따로 · 확실하지 않으면 「확인」 표시 ─────────────────────────────────────────────────


GEMMA = {"kind": "open", "text": "Gemma 4 26B-A4B 를 1순위로 잰다", "line": 10, "quote": "Gemma", "session": "s1"}
DRAFT = {"kind": "open", "text": "레딧 본문 초안을 쓴다", "line": 12, "quote": "초안", "session": "s1"}


def _turns(*texts: str, start: int = 20) -> list[Turn]:
    return [Turn(start + i, "사람" if i % 2 == 0 else "클로드", text, "10-23 22:24") for i, text in enumerate(texts)]


def test_unsure_cards_get_a_check_mark_not_a_close() -> None:
    turns = _turns("젬마 4 26B는 우리가 별로라서 안했다이가", "초안입니다: 제목 … 본문 …", "젬마 얘기 다시")
    reply = json.dumps({"closes": [{"id": "c2", "status": "done", "line": 21, "quote": "초안입니다"}],
                        "mentions": [{"id": "c1", "line": 20, "quote": "젬마 4 26B는 우리가"},
                                     {"id": "c1", "line": 22, "quote": "젬마 얘기 다시"},
                                     {"id": "c2", "line": 21, "quote": "초안입니다"},          # 닫힌 카드는 표시 안 함
                                     {"id": "c1", "line": 22, "quote": "지어낸 인용"}]}, ensure_ascii=False)
    closes, mentions = check_cards(turns, lambda s, u: reply, [GEMMA, DRAFT])
    assert [c["card_text"] for c in closes] == [DRAFT["text"]]
    assert [(m["id"], m["line"]) for m in mentions] == [(card_id(GEMMA), 22)], "카드마다 가장 뒤의 줄 하나 · 근거 인용 필수"


def test_a_quote_without_the_bold_marks_still_counts_but_a_made_up_one_does_not() -> None:
    """재생에서 실제로: 원문 「한국어 3개는 **통과로 봅니다.**」 · 모델 인용 「한국어 3개는 통과로 봅니다」가 버려졌다."""
    turns = _turns("2비트 결과입니다. 한국어 3개는 **통과로 봅니다.** `IQ2_M` 기준")
    reply = json.dumps({"closes": [{"id": "c1", "status": "done", "line": 20, "quote": "한국어 3개는 통과로 봅니다"}],
                        "mentions": [{"id": "c2", "line": 20, "quote": "IQ2_M 기준"}]}, ensure_ascii=False)
    card = {**GEMMA, "text": "2비트 한국어 품질을 잰다"}
    closes, mentions = check_cards(turns, lambda s, u: reply, [card, DRAFT])
    assert len(closes) == 1 and len(mentions) == 1
    fake = json.dumps({"closes": [{"id": "c1", "status": "done", "line": 20, "quote": "한국어 3개는 실패로 봅니다"}]},
                      ensure_ascii=False)
    assert check_cards(turns, lambda s, u: fake, [card]) == ([], [])


def test_a_mention_before_the_card_is_ignored() -> None:
    reply = json.dumps({"mentions": [{"id": "c1", "line": 5, "quote": "젬마 얘기"}]}, ensure_ascii=False)
    assert check_cards(_turns("젬마 얘기", start=5), lambda s, u: reply, [GEMMA]) == ([], [])


def test_the_check_mark_is_rendered_and_the_hook_still_drops_quotes(tmp_path: Path) -> None:
    data = tmp_path / "data" / "scribe"
    data.mkdir(parents=True)
    card = {**GEMMA, "id": card_id(GEMMA), "at": "10-23 22:21"}
    mention = {"op": "mention", "id": card["id"], "line": 320864, "quote": "젬마", "session": "s1"}
    (data / "cards.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (card, mention)) + "\n", encoding="utf-8")
    book = Scribe(tmp_path / "data", [])
    text = render(book.recent(session="s1"), book.closed(session="s1"))
    assert "[확인: 이 뒤 줄 320864에서 같은 이야기]" in text
    hooked = claude_hooks.newest_first_without_quotes(text)
    assert "[확인: 이 뒤 줄 320864에서 같은 이야기]  (10-23 22:21 · 줄 10)" in hooked and "「Gemma」" not in hooked
    assert book.all_cards("s1") == [card], "표시 줄은 카드가 아니다"


def test_a_new_rule_version_rereads_only_the_recent_stretch_once(tmp_path: Path) -> None:
    rows = [_user(f"사람 말 {i}: " + "가" * 200) for i in range(400)]
    log = tmp_path / "proj" / "s1.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("".join(rows), encoding="utf-8")
    data = tmp_path / "data" / "scribe"
    data.mkdir(parents=True)
    old = {"kind": "open", "text": "아주 옛 일", "line": 5, "quote": "사람 말 5", "session": "s1", "folder": "proj"}
    new = {"kind": "open", "text": "최근 일", "line": 390, "quote": "사람 말 390", "session": "s1", "folder": "proj"}
    (data / "cards.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (old, new)) + "\n", encoding="utf-8")
    end = offset_of_line(log, 400)
    # 옛 규칙으로 다 따라온 상태(되읽기도 끝 · 판 표시 없음).
    (data / "state.json").write_text(json.dumps({str(log): {"offset": end, "line": 400, "rc_offset": end, "rc_line": 400}}),
                                     encoding="utf-8")
    book = Scribe(tmp_path / "data", [log.parent])
    book.REWIND_BYTES = 30 * len(rows[0].encode("utf-8"))  # 끝 30줄쯤만
    found = book.next_reconcile_chunk()
    assert found is not None
    _, turns, _, earlier = found
    assert 365 <= turns[0].line <= 372, "가장 오래된 열린 카드(줄 5)까지 가지 않고 최근 구간만"
    assert {c["text"] for c in earlier} == {"아주 옛 일", "최근 일"}, "덩어리 중간(줄 390)에 생긴 카드도 그 뒤 말로 대 본다"
    state = json.loads((data / "state.json").read_text(encoding="utf-8"))[str(log)]
    assert state["rc_ver"] == CLOSE_VERSION and state["line"] == 400
    state.update(rc_offset=end, rc_line=400)  # 다 따라왔다고 치면
    (data / "state.json").write_text(json.dumps({str(log): state}), encoding="utf-8")
    assert book.next_reconcile_chunk() is None, "같은 판에서는 다시 되감지 않는다"


def test_a_log_read_from_the_start_under_the_new_rules_is_not_rewound(tmp_path: Path) -> None:
    log = tmp_path / "proj" / "s1.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("".join(_user(f"말 {i}") for i in range(20)), encoding="utf-8")
    book = Scribe(tmp_path / "data", [log.parent])
    book.MIN_NEW = 1
    book.run_once(lambda s, u: json.dumps({"items": [{"kind": "open", "text": "일 하나", "line": 3, "quote": "말 3"}]},
                                          ensure_ascii=False) if "새 카드를 쓰지 않는다" not in s else "{}")
    state = json.loads((tmp_path / "data" / "scribe" / "state.json").read_text(encoding="utf-8"))[str(log)]
    assert state["rc_ver"] == CLOSE_VERSION and state["rc_line"] == state["line"]


# ── 3. 「일하는 방식」 파일이 두 번 들어가지 않게 ──────────────────────────────────────────────────


def _home(tmp_path: Path, claude_md: str) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    (home / ".claude" / "작업방식.md").write_text("말투: 한국어로만\n" * 50, encoding="utf-8")
    return home


def test_style_imported_by_claude_md_is_detected(tmp_path: Path) -> None:
    home = _home(tmp_path, "# 지침\n\n@~/.claude/작업방식.md\n")
    style = str(home / ".claude" / "작업방식.md")
    assert claude_hooks.style_already_loaded(style, home=home)
    other = _home(tmp_path / "b", "# 지침\n```\n@~/.claude/작업방식.md\n```\n이 파일을 읽어라: ~/.claude/작업방식.md\n")
    assert not claude_hooks.style_already_loaded(str(other / ".claude" / "작업방식.md"), home=other), \
        "코드 칸 안의 @ 나 「읽어라」 안내는 끼워 넣기가 아니다"


def test_a_project_claude_md_import_counts_too(tmp_path: Path) -> None:
    home = _home(tmp_path, "# 없음\n")
    project = tmp_path / "proj" / "sub"
    project.mkdir(parents=True)
    (tmp_path / "proj" / "CLAUDE.md").write_text("@docs/style.md\n", encoding="utf-8")
    (tmp_path / "proj" / "docs").mkdir()
    (tmp_path / "proj" / "docs" / "style.md").write_text("방식", encoding="utf-8")
    assert claude_hooks.style_already_loaded(str(tmp_path / "proj" / "docs" / "style.md"), cwd=str(project), home=home)


@pytest.mark.parametrize("imported", [True, False])
def test_after_compact_puts_the_style_only_when_claude_md_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                   imported: bool) -> None:
    home = _home(tmp_path, "@~/.claude/작업방식.md\n" if imported else "# 끼워 넣기 없음\n")
    monkeypatch.setattr(claude_hooks.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(claude_hooks, "_story", lambda *_: {"enabled": True, "count": 1, "index": "",
                                                             "card": "## 남은 일\n- 일  (줄 1 · 「일」)"})
    out = claude_hooks.after_compact({"session_id": "s1", "source": "compact", "cwd": str(tmp_path)},
                                     {"token-file": "x", "style-file": str(home / ".claude" / "작업방식.md")})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert ("일하는 방식" in text) is (not imported)
    assert "- 일" in text, "카드는 그대로 넣는다"
