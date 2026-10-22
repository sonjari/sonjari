"""서기 2차(2026-10-21 저녁) — 카드를 지우지 않고 「닫는다」.

첫 점검: 이 세션 「남은 일」 28장 중 적어도 15장이 이미 끝났거나 뒤집혔는데 열린 채였다. 압축 뒤 그걸 믿으면 끝난 일을 다시 한다.
지키는 것:
- 닫기도 새 카드와 같은 규칙 — 그 조각 안의 글자 그대로 인용, 카드보다 뒤의 말, 아는 이름표만.
- 닫힌 카드는 열린 목록에서 빠지고, 닫힌 까닭과 함께 따로 남는다(지우지 않는다).
- 2차 이전 기록은 노는 시간에 지나간 말을 다시 읽어 닫는다(새 카드를 쓴 자리는 넘지 않는다).
- 같은 말은 또 적지 않는다 · 훅이 넣은 말(isMeta)은 사람 말이 아니다 · 카드에 그 말의 시각을 단다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alture_jarvis.scribe import (Scribe, Turn, _same_story, close_only, draft_and_close, offset_of_line, read_turns_from,
                                  render)


def _row(kind: str, text: Any, **extra: Any) -> str:
    return json.dumps({"type": kind, "message": {"role": kind, "content": text}, **extra}, ensure_ascii=False) + "\n"


def _turns(*texts: str, start: int = 10) -> list[Turn]:
    return [Turn(start + index, "사람" if index % 2 == 0 else "클로드", text, "10-21 17:05") for index, text in enumerate(texts)]


OPEN_CARD = {"kind": "open", "text": "README PR 을 하위 에이전트가 만드는 중", "line": 3, "quote": "README", "session": "s1"}
CLOUD_CARD = {"kind": "decided", "text": "클라우드플레어 터널로 설계", "line": 5, "quote": "클라우드플레어", "session": "s1"}


def test_a_close_needs_a_real_quote_a_later_line_and_a_known_tag() -> None:
    turns = _turns("README PR 합쳤습니다. 다음으로 갑니다", "테일스케일로 가자, 클라우드플레어는 안 한다")
    reply = json.dumps({"items": [], "closes": [
        {"id": "c1", "status": "done", "line": 10, "quote": "README PR 합쳤습니다"},
        {"id": "c2", "status": "superseded", "line": 11, "quote": "테일스케일로 가자"},
        {"id": "c9", "status": "done", "line": 10, "quote": "README PR 합쳤습니다"},       # 모르는 이름표
        {"id": "c1", "status": "done", "line": 10, "quote": "지어낸 인용입니다"},           # 인용 없음
        {"id": "c2", "status": "finished", "line": 11, "quote": "테일스케일로 가자"},       # 모르는 까닭
    ]}, ensure_ascii=False)
    items, closes = draft_and_close(turns, lambda s, u: reply, [OPEN_CARD, CLOUD_CARD])
    assert items == []
    assert [(c["card_text"], c["status"]) for c in closes] == [(OPEN_CARD["text"], "done"), (CLOUD_CARD["text"], "superseded")]
    assert closes[0]["at"] == "10-21 17:05"


def test_a_card_cannot_be_closed_by_words_said_before_it() -> None:
    turns = _turns("README PR 합쳤습니다", start=1)
    reply = json.dumps({"closes": [{"id": "c1", "status": "done", "line": 1, "quote": "README PR 합쳤습니다"}]}, ensure_ascii=False)
    assert close_only(turns, lambda s, u: reply, [OPEN_CARD]) == []


def test_the_open_cards_go_after_the_talk_so_line_numbers_lead() -> None:
    seen: dict[str, str] = {}

    def ask(system: str, user: str) -> str:
        seen.update(system=system, user=user)
        return "{}"

    draft_and_close(_turns("첫 말"), ask, [OPEN_CARD])
    assert seen["user"].startswith("[10] 사람: 첫 말")
    assert "=== 지금 열린 카드 ===" in seen["user"] and "[c1]" in seen["user"] and "closes" in seen["system"]
    draft_and_close(_turns("첫 말"), ask, [])
    assert "closes" not in seen["system"] and "지금 열린 카드" not in seen["user"], "열린 카드가 없으면 1차와 같은 프롬프트"


def test_closed_cards_leave_the_open_list_and_are_shown_with_why(tmp_path: Path) -> None:
    # (10-22: 카드 글이 「README PR 만드는 중」이었는데 진행 보고 거르기에 걸려 「README PR 을 만든다」로 — 시험의 뜻은 닫기다.)
    rows = [_row("user", f"사람 말 {i}: README PR 은 {i}번째로 이야기함") for i in range(30)]
    log = tmp_path / "proj" / "s1.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("".join(rows), encoding="utf-8")
    book = Scribe(tmp_path / "data", [log.parent])

    def first(system: str, user: str) -> str:
        return json.dumps({"items": [{"kind": "open", "text": "README PR 을 만든다", "line": 0, "quote": "README PR 은 0번째"}]},
                          ensure_ascii=False)

    book.CHUNK = 15
    assert book.run_once(first)["items"] == 1
    assert [c["text"] for c in book.recent(session="s1")] == ["README PR 을 만든다"]

    def second(system: str, user: str) -> str:
        assert "README PR 을 만든다" in user, "열린 카드를 같이 보여 준다"
        return json.dumps({"items": [{"kind": "open", "text": "README PR 을 만든다", "line": 15, "quote": "README PR 은 15번째"}],
                           "closes": [{"id": "c1", "status": "done", "line": 16, "quote": "README PR 은 16번째"}]},
                          ensure_ascii=False)

    result = book.run_once(second)
    assert result["closed"] == 1
    assert book.recent(session="s1") == [], "닫힌 카드는 빠지고, 같은 말은 또 적지 않는다(닫힌 것과 같은 말이라도)"
    shut = book.closed(session="s1")
    assert shut[0]["status"] == "done" and shut[0]["card_text"] == "README PR 을 만든다"
    card = render(book.recent(session="s1"), shut)
    assert "최근 닫힌 것" in card and "[끝남] README PR 을 만든다" in card
    raw = (tmp_path / "data" / "scribe" / "cards.jsonl").read_text(encoding="utf-8")
    assert raw.count("README PR 을 만든다") >= 2, "원래 카드도 닫힌 줄도 남는다(지우지 않는다)"


def test_old_logs_are_reread_to_close_cards_without_passing_the_draft_place(tmp_path: Path) -> None:
    rows = [_row("user", f"사람 말 {i}: 일 {i}") for i in range(40)]
    log = tmp_path / "proj" / "s1.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("".join(rows), encoding="utf-8")
    data = tmp_path / "data" / "scribe"
    data.mkdir(parents=True)
    # 2차 이전 상태 — 카드 하나(줄 2, 이름표 없음), 새 카드는 줄 30 까지 썼고 되읽기 자리는 없다.
    (data / "cards.jsonl").write_text(json.dumps({"kind": "open", "text": "일 2 하기", "line": 2, "quote": "일 2",
                                                  "session": "s1", "folder": "proj"}, ensure_ascii=False) + "\n", encoding="utf-8")
    (data / "state.json").write_text(json.dumps({str(log): {"offset": offset_of_line(log, 30), "line": 30}}), encoding="utf-8")
    book = Scribe(tmp_path / "data", [log.parent])
    book.MIN_NEW = 50  # 새 말은 없다고 치고 되읽기만
    asked: list[str] = []

    def ask(system: str, user: str) -> str:
        asked.append(user)
        assert "새 카드를 쓰지 않는다" in system
        first_line = int(user.split("]", 1)[0][1:])
        assert first_line == 3, "가장 오래된 열린 카드 다음 줄부터"
        return json.dumps({"closes": [{"id": "c1", "status": "done", "line": 9, "quote": "사람 말 9: 일 9"}]}, ensure_ascii=False)

    result = book.run_once(ask)
    assert result["reconciled"] and result["closed"] == 1
    assert book.recent(session="s1") == []
    state = json.loads((data / "state.json").read_text(encoding="utf-8"))[str(log)]
    assert state["rc_line"] == 30 and state["line"] == 30, "새 카드를 쓴 자리를 넘지 않는다"
    # 10-22 주제 색인: 다 따라온 뒤의 노는 시간에는 주제 없는 옛 카드에 주제를 붙인다(못 붙이면 「주제 없음」 표시 — 맴돌지 않게).
    assert book.run_once(lambda system, user: "{}")["tagged"] == 1
    assert book.run_once(ask) == {"done": False, "why": "읽을 새 말이 없음"}


def test_hook_words_are_not_the_person_and_turns_carry_their_time(tmp_path: Path) -> None:
    rows = [
        _row("user", "Stop hook feedback:\n최종 답이 영어입니다. 다시 쓰세요", isMeta=True, timestamp="2026-10-21T08:00:00Z"),
        _row("user", "진짜 사람 말", timestamp="2026-10-21T08:05:00Z"),
    ]
    log = tmp_path / "s.jsonl"
    log.write_text("".join(rows), encoding="utf-8")
    turns, _, _ = read_turns_from(log, 0, 0, 10)
    assert [t.text for t in turns] == ["진짜 사람 말"]
    assert turns[0].at.endswith(":05") and len(turns[0].at) == len("10-21 17:05")


def test_same_story_is_strict_for_short_lines_and_loose_for_long_ones() -> None:
    assert not _same_story("남은 일 3", "남은 일 4")
    assert _same_story("영수증 카드를 운영에 반영하고 앱을 굽기로 했다.", "영수증 카드를 운영에 반영하고 앱을 구우기로 했다.")
    assert not _same_story("영수증 카드를 운영에 반영한다", "원격 연결 첫 판을 테일스케일로 만든다")


def test_offset_of_line_points_at_the_start_of_that_line(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_bytes("".join(f"줄 {i}\n" for i in range(100)).encode("utf-8"))  # 윈도우 write_text 는 \r\n 으로 바꾼다
    with path.open("rb") as handle:
        handle.seek(offset_of_line(path, 37))
        assert handle.readline().decode("utf-8") == "줄 37\n"
    assert offset_of_line(path, 0) == 0


def test_a_wrong_close_can_be_reopened_with_a_reason_and_both_lines_stay(tmp_path: Path) -> None:
    """10-21 18:00 운영 첫 바퀴: 「영수증 뒤 원격 첫 판」이 영수증만 끝났는데 닫혔다 — 되돌릴 길이 있어야 한다."""
    data = tmp_path / "scribe"
    data.mkdir()
    card = {"kind": "open", "text": "영수증 카드 뒤 원격 설계와 첫 판", "line": 5, "quote": "원격", "session": "s1", "folder": "p"}
    close = {"op": "close", "id": "s1-5-x", "status": "done", "line": 9, "quote": "영수증 운영", "session": "s1", "folder": "p"}
    from alture_jarvis.scribe import card_id
    close["id"] = card_id(card)
    (data / "cards.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (card, close)) + "\n", encoding="utf-8")
    book = Scribe(tmp_path, [])
    assert book.recent(session="s1") == []
    assert book.reopen([close["id"]], "") == 0, "까닭 없이는 못 연다"
    assert book.reopen([close["id"], "없는-이름표"], "B(원격)가 안 끝났는데 A(영수증)로 닫힘") == 1
    assert [c["text"] for c in book.recent(session="s1")] == [card["text"]] and book.closed(session="s1") == []
    raw = (data / "cards.jsonl").read_text(encoding="utf-8")
    assert '"op": "close"' in raw and '"op": "reopen"' in raw, "닫기도 다시 열기도 남는다"


def test_the_prompt_carries_the_three_rules_from_the_first_live_round() -> None:
    from alture_jarvis import scribe

    assert "B 가 끝나야" in scribe._CLOSE_RULES and "전부" in scribe._CLOSE_RULES and "하는 중" in scribe._CLOSE_RULES
    assert "한 카드에 한 일" in scribe._SYSTEM and "바로 다음에 할 걸음" in scribe._SYSTEM


def test_a_reopened_card_cannot_be_closed_again_by_words_already_read(tmp_path: Path) -> None:
    """10-21 저녁: 다시 연 2장을 새 규칙 되읽기가 같은 옛 근거로 또 닫았다. 다시 연 뒤의 말로만 닫을 수 있다."""
    from alture_jarvis.scribe import card_id

    log = tmp_path / "proj" / "s1.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("x\n" * 60, encoding="utf-8")
    data = tmp_path / "data" / "scribe"
    data.mkdir(parents=True)
    card = {"kind": "open", "text": "영수증 뒤 원격 첫 판", "line": 5, "quote": "원격", "session": "s1", "folder": "proj"}
    close = {"op": "close", "id": card_id(card), "status": "done", "line": 20, "quote": "영수증 운영", "session": "s1", "folder": "proj"}
    (data / "cards.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (card, close)) + "\n", encoding="utf-8")
    (data / "state.json").write_text(json.dumps({str(log): {"offset": 100, "line": 50, "rc_offset": 100, "rc_line": 50}}), encoding="utf-8")
    book = Scribe(tmp_path / "data", [log.parent])
    assert book.reopen([card_id(card)], "B 가 안 끝남") == 1
    active = book.active("s1")
    assert active and active[0]["reopen_after"] == 50

    old = _turns("영수증 운영에 들어갔습니다", start=20)
    reply = json.dumps({"closes": [{"id": "c1", "status": "done", "line": 20, "quote": "영수증 운영에 들어갔습니다"}]}, ensure_ascii=False)
    assert close_only(old, lambda s, u: reply, active) == [], "다시 열기 전에 읽은 말로는 못 닫는다"
    new = _turns("원격 첫 판 끝났습니다", start=55)
    reply = json.dumps({"closes": [{"id": "c1", "status": "done", "line": 55, "quote": "원격 첫 판 끝났습니다"}]}, ensure_ascii=False)
    assert len(close_only(new, lambda s, u: reply, active)) == 1, "그 뒤의 말로는 닫을 수 있다"
